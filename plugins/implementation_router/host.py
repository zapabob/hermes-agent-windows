"""Parent-owned engineering host using Hermes's native inference and tools.

Stages are data-only conversations. No credential-bearing AIAgent is created.
The native measured Docker backend is the descendant execution boundary.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shlex

from downstream.implementation_router.kernel import CheckReceipt, StageResult
from downstream.implementation_router.security import CredentialFreeAdmission
from tools.environments.docker import DockerEnvironment
from tools.terminal_tool import bind_credential_free_environment

from .actors import run_actor
from .configuration import picker_routes
from .workspace import digest, import_sources, read_sources, snapshot, write_result


class NativeEngineeringHost:
    def __init__(self, *, ctx, routes, workspace: dict, data_dir: Path, binding,
                 max_actor_calls: int = 32):
        self.ctx, self.routes, self.workspace = ctx, routes, workspace
        self.data_dir, self.binding = data_dir, binding
        self.max_actor_calls = max_actor_calls
        self.env = None
        self.last_verified = None
        self.result_dir = None
        self.run_dir = data_dir / binding.run_id
        self._journal = None
        self._failure_logs = {}
        self._guards = {}
        self._source = {}

    def _routes_still_selected(self):
        from hermes_cli.config import load_config_readonly
        if picker_routes(load_config_readonly()).fingerprint() != self.routes.fingerprint():
            raise RuntimeError('Native picker selection changed')
        if self.ctx.get_config('enabled', False) is not True:
            raise RuntimeError('Engineering permission was revoked')

    def admit(self, binding, routes):
        if binding != self.binding or routes != self.routes or self.env is None:
            raise RuntimeError('No active native execution boundary')
        self._routes_still_selected()
        self.env.assert_credential_free()
        self.env.assert_quiescent()
        return CredentialFreeAdmission(binding.run_id, binding.workspace_id, routes.fingerprint())

    def cancellation_requested(self, binding):
        from tools.interrupt import is_interrupted
        return is_interrupted()

    def checkpoint(self, binding, event):
        if binding != self.binding:
            raise ValueError('Incorrect workflow identity')
        if self._journal is None:
            raise RuntimeError('No durable journal is available')
        record = json.dumps(asdict(event), sort_keys=True) + '\n'
        self._journal.write(record)
        self._journal.flush()
        os.fsync(self._journal.fileno())

    @contextmanager
    def lease(self, binding):
        if binding != self.binding:
            raise ValueError('Incorrect workflow identity')
        self._routes_still_selected()
        source_root = Path(self.workspace['path']).resolve(strict=True)
        lock_id = hashlib.sha256(str(source_root).encode()).hexdigest()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        lease_path = self.data_dir / (lock_id + '.lease')
        # A surviving lease after interruption blocks replay. It is deliberately
        # not expired on a timer; the operator must inspect any uncertain run.
        descriptor = os.open(lease_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as lease:
            lease.write(binding.run_id)
            lease.flush()
            os.fsync(lease.fileno())
        clean = False
        try:
            self.run_dir.mkdir(mode=0o700)
            self._journal = (self.run_dir / 'events.jsonl').open('x', encoding='utf-8')
            self._source = read_sources(source_root, tuple(self.workspace['source_paths']))
            self.env = DockerEnvironment.credential_free(
                image=self.workspace['image'], task_id=binding.run_id, timeout=60)
            with bind_credential_free_environment(binding.run_id, self.env):
                self._guards = import_sources(self.env, self._source, tuple(self.workspace['protected_paths']))
                if snapshot(self.env) != self._source:
                    raise RuntimeError('Source transfer does not match the admitted snapshot')
                yield
                self.env.assert_quiescent()
                if self.last_verified is not None and not self.cancellation_requested(binding):
                    final = snapshot(self.env)
                    if digest(final) != self.last_verified:
                        raise RuntimeError('Workspace changed after verification')
                    self._check_guards(final)
                    self.result_dir = self.run_dir / 'verified-workspace'
                    write_result(self.result_dir, final)
                    receipt = {'run_id': binding.run_id, 'workspace_digest': self.last_verified,
                               'original_digest': digest(self._source), 'route_fingerprint': self.routes.fingerprint()}
                    (self.run_dir / 'workspace-receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
            clean = True
        finally:
            # Keep journal open for the kernel's final, post-cleanup completion
            # checkpoint. close() is called by the entrypoint after run returns.
            if clean:
                lease_path.unlink()
            else:
                # Do not claim an uncertain cleanup released the writer. The
                # unique lease and journal remain available for operator recovery.
                if self.env is not None:
                    self.env.cleanup()

    def close(self):
        if self._journal is not None:
            self._journal.close()
            self._journal = None

    def _check_guards(self, files):
        if any(files.get(name) != content for name, content in self._guards.items()):
            raise RuntimeError('Protected acceptance evidence changed')

    def _dispatch(self, name, args):
        if self.env is None:
            raise RuntimeError('No isolated environment')
        self.env.assert_credential_free()
        return self.ctx.dispatch_tool(name, args, task_id=self.binding.run_id)

    def stage(self, request):
        if request.binding != self.binding or request.route != self.routes.for_role(request.role):
            raise ValueError('Stage is not bound to the selected route')
        self.last_verified = None
        from tools.registry import registry
        # Native schemas and dispatch stay authoritative; no shell or file-tool
        # reimplementation is supplied to a model. Only these bounded tools exist.
        from tools import file_tools, terminal_tool  # noqa: F401
        names = ('read_file',) if request.role != 'worker' else ('read_file', 'write_file', 'patch', 'terminal')
        schemas = {name: registry.get_schema(name) for name in names}
        if any(schema is None for schema in schemas.values()):
            raise RuntimeError('Native engineering tools are not registered')
        payload = json.loads(request.handoff_json)
        payload['workspace_files'] = list(self._source)
        if self._failure_logs:
            payload['verification_details'] = self._failure_logs
        text = run_actor(
            llm=self.ctx.llm, route=request.route, role=request.role,
            handoff=json.dumps(payload, ensure_ascii=False), dispatch=self._dispatch,
            schemas=schemas, cancelled=lambda: self.cancellation_requested(self.binding),
            max_calls=self.max_actor_calls,
        )
        self.env.assert_quiescent()
        files = snapshot(self.env)
        self._check_guards(files)
        return StageResult(request.attempt_id, 'SUCCEEDED', True, text, digest(files))

    def verify(self, request):
        from tools.approval import check_all_command_guards

        if request.binding != self.binding:
            raise ValueError('Verification binding mismatch')
        checks = {row['id']: row for row in self.workspace['checks']}
        if tuple(checks) != request.required_checks:
            raise ValueError('Verification policy changed')
        receipts = []
        self._failure_logs = {}
        for check_id in request.required_checks:
            if self.cancellation_requested(self.binding):
                raise InterruptedError('Host cancelled verification')
            self.env.assert_quiescent()
            before = snapshot(self.env)
            self._check_guards(before)
            if digest(before) != request.workspace_digest:
                raise RuntimeError('Writer changed before verification')
            argv = tuple(checks[check_id]['argv'])
            approval = check_all_command_guards(shlex.join(argv), 'docker', has_host_access=False)
            if approval.get('approved') is not True:
                raise PermissionError('Native approval policy did not permit the check')
            result = self.env.execute_clean(argv, timeout=120)
            code = result.get('returncode')
            if type(code) is not int:
                raise RuntimeError('No conclusive verifier exit status')
            self.env.assert_quiescent()
            after = snapshot(self.env)
            self._check_guards(after)
            receipt = CheckReceipt(
                check_id, request.attempt_id, self.binding.run_id, self.binding.workspace_id,
                request.revision, code, True, code == 124, True, digest(before), digest(after))
            receipts.append(receipt)
            if code != 0:
                self._failure_logs[check_id] = str(result.get('output', ''))[-8000:]
        if all(r.exit_code == 0 and r.snapshot_before == r.snapshot_after == request.workspace_digest
               and not r.timed_out for r in receipts):
            self.last_verified = request.workspace_digest
        return tuple(receipts)
