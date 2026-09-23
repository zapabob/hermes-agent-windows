"""Opt-in public entrypoint; task text cannot select credentials or host paths."""
from __future__ import annotations

import json
from pathlib import Path
import re
import uuid

from downstream.implementation_router.i18n import normalise_locale
from downstream.implementation_router.kernel import ImplementationRouter, Policy, RunBinding, RunResult
from .configuration import picker_routes
from .workspace import relative_path


_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z')


def _workspace(value):
    if type(value) is not dict or set(value) != {'path', 'image', 'source_paths', 'protected_paths', 'checks'}:
        raise ValueError('Invalid operator workspace policy')
    if not isinstance(value['path'], str) or not Path(value['path']).is_absolute():
        raise ValueError('Workspace path must be absolute')
    for key in ('source_paths', 'protected_paths'):
        entries = value[key]
        if type(entries) is not list or not 1 <= len(entries) <= 128:
            raise ValueError('Explicit source and acceptance paths are required')
        for name in entries:
            relative_path(name)
    checks = value['checks']
    if type(checks) is not list or not 1 <= len(checks) <= 16:
        raise ValueError('Explicit deterministic checks are required')
    names = set()
    for check in checks:
        if (type(check) is not dict or set(check) != {'id', 'argv'}
                or not isinstance(check['id'], str) or not _NAME.fullmatch(check['id'])
                or check['id'] in names):
            raise ValueError('Invalid check identifier')
        names.add(check['id'])
        argv = check['argv']
        if (type(argv) is not list or not 1 <= len(argv) <= 64
                or any(not isinstance(arg, str) or '\0' in arg or len(arg) > 2048 for arg in argv)
                or not argv[0].startswith(('/usr/bin/', '/usr/local/bin/', '/bin/'))):
            raise ValueError('Check executable must come from the trusted image')
    return value


def run_workflow(ctx, args, *, run_id=None, operation_id=None):
    language = 'en'
    host = None
    try:
        from hermes_cli.config import load_config_readonly
        config = load_config_readonly()
        language = normalise_locale(config.get('display', {}).get('language', config.get('language', 'en')))
        if ctx.get_config('enabled', False) is not True:
            return json.dumps(RunResult('BLOCKED', 'routing_disabled', 0, 1, ()).to_dict(locale=language), ensure_ascii=False)
        if (type(args) is not dict or set(args) != {'workspace', 'task'}
                or not isinstance(args['workspace'], str) or not _NAME.fullmatch(args['workspace'])
                or not isinstance(args['task'], str) or not args['task'].strip() or len(args['task']) > 16000):
            raise ValueError('Invalid workflow request')
        workspaces = ctx.get_config('workspaces', {})
        if type(workspaces) is not dict or args['workspace'] not in workspaces:
            raise ValueError('Unknown operator workspace')
        workspace = _workspace(workspaces[args['workspace']])
        routes = picker_routes(config)
        from plugins.plugin_storage import plugin_data_dir
        from .host import NativeEngineeringHost

        if run_id is not None and (type(run_id) is not str or not re.fullmatch(r'eng-[a-f0-9]{32}', run_id)):
            raise ValueError('Invalid host run identity')
        if operation_id is not None and (type(operation_id) is not str
                                          or not re.fullmatch(r'op-[a-f0-9]{32}', operation_id)
                                          or run_id is None):
            raise ValueError('Invalid host operation identity')
        binding = RunBinding(run_id or 'eng-' + uuid.uuid4().hex, args['workspace'])
        host = NativeEngineeringHost(ctx=ctx, routes=routes, workspace=workspace,
                                     data_dir=plugin_data_dir('implementation_router'), binding=binding,
                                     operation_id=operation_id)
        result = ImplementationRouter(Policy(), routing=routes).run(
            task=args['task'], binding=binding, required_checks=tuple(c['id'] for c in workspace['checks']), host=host)
        if host.run_dir.is_dir():
            host.record_result(result)
        output = result.to_dict(locale=language)
        output['run_id'] = binding.run_id
        if result.state == 'SUCCEEDED' and host.result_dir is not None:
            output['verified_workspace'] = str(host.result_dir)
        return json.dumps(output, ensure_ascii=False)
    except Exception:
        # Never return SDK/driver exception text, host environment or credentials.
        return json.dumps(RunResult('BLOCKED', 'credential_boundary_unavailable', 0, 1, ()).to_dict(locale=language), ensure_ascii=False)
    finally:
        if host is not None:
            host.close()
