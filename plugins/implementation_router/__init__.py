"""Sequential engineering inside Hermes; native picker and parent-owned inference."""
from __future__ import annotations


def register(ctx):
    from .configuration import ROLES, SLOTS

    for role in ROLES:
        ctx.register_auxiliary_task(
            key=SLOTS[role], display_name=f'Engineering {role}',
            description=f'Sequential implementation workflow: {role}',
            defaults={'provider':'auto', 'model':'', 'timeout':120},
        )

    def run(args, **kwargs):
        from .entrypoint import run_workflow
        return run_workflow(ctx, args)

    def slash(raw):
        import json
        return run(json.loads(raw))

    ctx.register_command('engineer', handler=slash,
                         description='Run a credential-free sequential engineering workflow',
                         args_hint='{"workspace":"configured-name","task":"..."}')
    ctx.register_tool(
        name='engineering_run', toolset='engineering',
        schema={'name':'engineering_run','description':(
            'Plan, implement and verify in an isolated workspace. Uses operator-selected native models. '
            'Returns a verified copy; never edits the original checkout or publishes a PR.'),
            'parameters':{'type':'object','properties':{
                'workspace':{'type':'string'}, 'task':{'type':'string'}},
                'required':['workspace','task'],'additionalProperties':False}},
        handler=run, check_fn=lambda: ctx.get_config('enabled', False) is True,
    )
