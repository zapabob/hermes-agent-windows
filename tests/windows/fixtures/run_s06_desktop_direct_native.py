"""Observe and reap only this native fixture's PID/birth/executable identities."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import select
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
sys.dont_write_bytecode = True
try:
    import psutil
except ModuleNotFoundError:
    psutil = None  # Pure checks are stdlib-only; native mode fails closed.


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class FinalPathAudit:
    """One final audit caches paths only; every cached realpath is rechecked."""
    def __init__(self, deadline=None):
        self.deadline,self.paths = deadline,{}

    def check(self):
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise TimeoutError('Final realpath audit exhausted the original deadline')

    def resolve(self, value):
        self.check()
        key=str(Path(value))
        if key not in self.paths:
            resolved=Path(value).resolve()
            self.check()
            self.paths[key]=resolved
        return self.paths[key]

    def verify(self):
        for raw,expected in self.paths.items():
            self.check()
            current=Path(raw).resolve()
            self.check()
            if current != expected:
                raise RuntimeError('Final realpath binding changed during classification')
        self.check()


def owned_command(item, operation, allowed, root, launches=None, *, deadline=None, resolver=None):
    """Match a full registered launch, never an argv token or incidental path.

    The retained Job owns cleanup. These records only classify observed launches;
    neither a registry file nor a bare PID authorizes signalling a process.
    """
    if not isinstance(allowed, dict) or not isinstance(launches, list):
        return False
    resolve=resolver or (lambda value:Path(value).resolve())
    try:
        exe, cwd, argv = resolve(item['exe']), resolve(item['cwd']), item['cmd']
        digest = allowed.get(str(exe).casefold())
        if not digest or not isinstance(argv, list) or not argv:
            return False
        for launch in launches:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError('Exact registry classification exhausted the original deadline')
            if not isinstance(launch, dict):
                return False
            if (launch.get('operation') == str(operation) and launch.get('id')
                    and resolve(launch['exe']) == exe and launch.get('sha256') == digest
                    and registered_cwd(launch, cwd, operation, root, resolve) and launch.get('cmd') == argv
                    and (cwd == root or cwd.is_relative_to(operation))):
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError('Exact registry match crossed the original deadline')
                return True
    except TimeoutError:
        if deadline is not None:
            raise
        return False
    except (KeyError, TypeError, OSError, ValueError):
        return False
    return False


def registered_cwd(launch, cwd, operation, root, resolver=None):
    """The exact registered Git worker may apply its one bound -C transition."""
    resolve=resolver or (lambda value:Path(value).resolve())
    initial = resolve(launch['cwd'])
    if initial == cwd:
        return True
    repo = operation / 'owned spaced repo'
    runtime_roots = {root, operation / 'missing-static-controls owned runtime',
                     operation / 'changed-static-controls owned runtime'}
    argv = launch['cmd']
    return (Path(launch['exe']).name.casefold() == 'git.exe' and initial in runtime_roots
            and cwd == repo and len(argv) > 3 and argv[1] == '-C'
            and Path(argv[2]).is_absolute() and resolve(argv[2]) == repo
            and argv.count('-C') == 1)


def owned_console_aux(item, operation, trust, parent, parent_registered, job_scope):
    """In-memory kernel evidence only; no launch-registry file grants OS authority."""
    try:
        child_kernel, parent_kernel = item['kernel_identity'], parent['kernel_identity']
        live = (parent_kernel['exit_filetime'] == 0 and parent_kernel['wait_result'] == 258
                and parent_kernel.get('console_host_pid') == item['pid'])
        retired = (parent_kernel.get('association') == 'RETIRED_PARENT_INTERVAL'
                   and parent_kernel.get('prior_live_identity') is True
                   and child_kernel.get('prior_live_identity') is True
                   and parent_kernel['wait_result'] == 0 and parent_kernel['exit_filetime'] > 0
                   and parent_kernel['creation_filetime'] <= child_kernel['creation_filetime']
                       <= parent_kernel['exit_filetime'])
        return bool(parent_registered is True and isinstance(job_scope, str) and job_scope
            and trust['operation'] == str(operation)
            and Path(item['exe']).resolve() == Path(trust['exe']).resolve()
            and item['cmd'] == trust['cmd'] and item['cwd'].casefold() == trust['cwd'].casefold()
            and item['exe_sha256'] == trust['sha256']
            and child_kernel['pid'] == item['pid'] and parent_kernel['pid'] == parent['pid']
            and child_kernel['parent_pid'] == parent['pid']
            and Path(child_kernel['exe']).resolve() == Path(item['exe']).resolve()
            and Path(parent_kernel['exe']).resolve() == Path(parent['exe']).resolve()
            and child_kernel['job_scope'] == parent_kernel['job_scope'] == job_scope
            and child_kernel['creation_filetime'] >= parent_kernel['creation_filetime'] > 0
            and child_kernel['exit_filetime'] >= 0 and parent_kernel['exit_filetime'] >= 0
            and (live or retired))
    except (KeyError, TypeError, OSError, ValueError, AttributeError):
        return False


class RetainedJobObservation:
    """Owns observation HANDLEs only. Existing product Job/Popen owns all cleanup."""
    def __init__(self, job, *, verified_manifest=None):
        import ctypes
        from ctypes import wintypes
        self.ctypes, self.types, self.job = ctypes, wintypes, job
        self.scope = uuid.uuid4().hex
        self.handles, self.digests, self.generations, self.identities = {}, {}, {}, {}
        if verified_manifest is not None:
            self.digests = frozen_observation_digests(verified_manifest)
        self.identity_handles = {}
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.native = ctypes.WinDLL('ntdll')
        signatures = [
            ('OpenProcess',[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD],wintypes.HANDLE),
            ('CloseHandle',[wintypes.HANDLE],wintypes.BOOL),
            ('GetProcessTimes',[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4,wintypes.BOOL),
            ('QueryFullProcessImageNameW',[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)],wintypes.BOOL),
            ('IsProcessInJob',[wintypes.HANDLE,wintypes.HANDLE,ctypes.POINTER(wintypes.BOOL)],wintypes.BOOL),
            ('WaitForSingleObject',[wintypes.HANDLE,wintypes.DWORD],wintypes.DWORD),
        ]
        for name, arguments, result in signatures:
            function = getattr(self.kernel,name)
            function.argtypes, function.restype = arguments,result
        self.native.NtQueryInformationProcess.argtypes = [wintypes.HANDLE,wintypes.ULONG,wintypes.LPVOID,
                                                         wintypes.ULONG,ctypes.POINTER(wintypes.ULONG)]
        self.native.NtQueryInformationProcess.restype = wintypes.LONG

    def checked(self, value, api='Windows observation'):
        if not value:
            error = self.ctypes.WinError(self.ctypes.get_last_error())
            error.observation_api = api
            raise error
        return value

    def proof(self, pid):
        c,t,k = self.ctypes,self.types,self.kernel
        if pid not in self.handles:
            self.handles[pid] = self.checked(k.OpenProcess(0x00101000,False,pid), 'OpenProcess')
        handle = self.handles[pid]
        times = [t.FILETIME() for _ in range(4)]
        self.checked(k.GetProcessTimes(handle,*(c.byref(value) for value in times)), 'GetProcessTimes')
        raw = lambda value: (value.dwHighDateTime << 32) | value.dwLowDateTime
        born, exited = raw(times[0]), raw(times[1])
        if self.generations.setdefault(pid,born) != born:
            raise RuntimeError('Retained HANDLE creation generation changed')
        wait = k.WaitForSingleObject(handle,0)
        if wait not in (0,258):
            raise RuntimeError('Retained HANDLE wait state is UNKNOWN')
        known = self.identities.get(pid)
        if wait == 0:
            # No PID lookup or dead image query. Only a prior live full capture
            # on this continuously retained HANDLE may supply immutable metadata.
            if (not known or self.identity_handles.get(pid) != handle or exited <= 0
                    or known['kernel_identity'].get('prior_live_identity') is not True
                    or known['kernel_identity']['creation_filetime'] != born
                    or not all(known.get(key) for key in ('exe','cwd','cmd','exe_sha256'))):
                raise RuntimeError('Retired HANDLE has no complete prior live identity')
            image = known['exe']
        else:
            buffer,size = c.create_unicode_buffer(32768),t.DWORD(32768)
            self.checked(k.QueryFullProcessImageNameW(handle,0,buffer,c.byref(size)), 'QueryFullProcessImageNameW')
            image = buffer.value
        member = t.BOOL()
        self.checked(k.IsProcessInJob(handle,self.job,c.byref(member)), 'IsProcessInJob')
        if not member.value:
            raise RuntimeError('Observation HANDLE is not in the exact retained Job')
        class Basic(c.Structure):
            _fields_ = [('reserved1',t.LPVOID),('peb',t.LPVOID),('reserved2',t.LPVOID*2),
                        ('pid',c.c_size_t),('parent',c.c_size_t)]
        info,size = Basic(),t.ULONG()
        status = self.native.NtQueryInformationProcess(handle,0,c.byref(info),c.sizeof(info),c.byref(size))
        if status < 0 or info.pid != pid:
            raise RuntimeError('Retained HANDLE process identity is UNKNOWN')
        return {'pid':pid,'creation_filetime':born,'exit_filetime':exited,
                'exe':image,'parent_pid':info.parent,'job_scope':self.scope,'wait_result':wait,
                'prior_live_identity':bool(known and known['kernel_identity'].get('prior_live_identity') is True)}

    def observe(self, process):
        proof = self.proof(process.pid)
        if proof['wait_result'] == 0:
            return dict(self.identities[process.pid],kernel_identity=proof)
        item = process_identity(process)
        if (abs(item['birth']-(proof['creation_filetime']/10000000-11644473600)) > 0.00001
                or Path(item['exe']).resolve() != Path(proof['exe']).resolve() or not item['cmd']):
            raise RuntimeError('Metadata differs from retained HANDLE generation')
        exe = str(Path(item['exe']).resolve())
        digest_key = exe.casefold()
        if digest_key not in self.digests:
            self.digests[digest_key] = sha256(exe)
        if proof['exit_filetime'] != 0 or self.kernel.WaitForSingleObject(self.handles[process.pid],0) != 258:
            raise RuntimeError('Initial full metadata was not captured on a live retained HANDLE')
        proof['prior_live_identity'] = True
        item = dict(item,kernel_identity=proof,exe_sha256=self.digests[digest_key])
        self.identities[process.pid] = item
        self.identity_handles[process.pid] = self.handles[process.pid]
        return item

    def associate(self, item, parent):
        c,t = self.ctypes,self.types
        if parent['pid'] not in self.handles:
            raise RuntimeError('Registered parent HANDLE was not continuously retained')
        proof = self.proof(parent['pid'])
        if proof['creation_filetime'] != parent['kernel_identity']['creation_filetime']:
            raise RuntimeError('Retained parent generation changed')
        if proof['wait_result'] == 0:
            for record in (parent,item):
                pid = record['pid']
                known = self.identities.get(pid)
                if (not known or pid not in self.handles
                        or self.identity_handles.get(pid) != self.handles[pid]
                        or known['kernel_identity'].get('prior_live_identity') is not True
                        or any(record.get(key) != known.get(key) for key in
                               ('pid','birth','exe','cwd','cmd','exe_sha256'))):
                    raise RuntimeError('Retired association lacks exact prior live metadata and HANDLE')
            child_proof = self.proof(item['pid'])
            if (child_proof['creation_filetime'] != item['kernel_identity']['creation_filetime']
                    or child_proof['parent_pid'] != parent['pid']
                    or child_proof['job_scope'] != proof['job_scope']
                    or not 0 < proof['creation_filetime'] <= child_proof['creation_filetime'] <= proof['exit_filetime']
                    or self.kernel.WaitForSingleObject(self.handles[parent['pid']],0) != 0):
                raise RuntimeError('Retired parent interval or exact child generation is UNKNOWN')
            proof['association'] = 'RETIRED_PARENT_INTERVAL'
            return dict(parent,kernel_identity=proof)
        if (proof['exit_filetime'] != 0
                or self.kernel.WaitForSingleObject(self.handles[parent['pid']],0) != 258):
            raise RuntimeError('Console parent is not still alive in its retained generation')
        value,size = c.c_size_t(),t.ULONG()
        status = self.native.NtQueryInformationProcess(self.handles[parent['pid']],49,c.byref(value),
                                                     c.sizeof(value),c.byref(size))
        if status < 0:
            raise RuntimeError('Console association is UNKNOWN')
        proof['console_host_pid'] = value.value & ~3
        proof['wait_result'] = self.kernel.WaitForSingleObject(self.handles[parent['pid']],0)
        if proof['wait_result'] != 258:
            raise RuntimeError('Console parent exited during association query')
        parent = dict(parent,kernel_identity=proof)
        return parent

    def close(self):
        rows,errors = [],[]
        for pid,handle in self.handles.items():
            state = self.kernel.WaitForSingleObject(handle,0)
            rows.append({'pid':pid,'handle':int(handle),'creation_filetime':self.generations.get(pid),
                         'identity':self.identities.get(pid),'wait_result':state,
                         'state':'EXITED' if state == 0 else 'UNKNOWN'})
            if state != 0:
                errors.append({'phase':'retained_observation','pid':pid,'status':'UNKNOWN'})
            if not self.kernel.CloseHandle(handle):
                errors.append({'phase':'observation_close','pid':pid,'status':'UNKNOWN'})
        self.handles.clear()
        self.identity_handles.clear()
        return rows,errors


def console_auxiliary_binding(operation):
    """Pin the one canonical Windows console host; never a System32 wildcard."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32',use_last_error=True)
    for name in ('GetSystemDirectoryW','GetWindowsDirectoryW'):
        function = getattr(kernel,name)
        function.argtypes,function.restype = [wintypes.LPWSTR,wintypes.UINT],wintypes.UINT
    system,windows = ctypes.create_unicode_buffer(32768),ctypes.create_unicode_buffer(32768)
    if not 0 < kernel.GetSystemDirectoryW(system,len(system)) < len(system):
        raise ctypes.WinError(ctypes.get_last_error())
    if not 0 < kernel.GetWindowsDirectoryW(windows,len(windows)) < len(windows):
        raise ctypes.WinError(ctypes.get_last_error())
    exe = (Path(system.value)/'conhost.exe').resolve()
    return {'operation':str(operation),'exe':str(exe),'sha256':sha256(exe),'cwd':windows.value,
            'cmd':['\\??\\'+str(Path(system.value)/'conhost.exe'),'0x4']}


def frozen_observation_digests(manifest):
    """Only the supervisor's prevalidated executable manifest seeds this cache."""
    if not isinstance(manifest, dict):
        raise TypeError('Verified executable manifest must be a mapping')
    result = {}
    for executable, digest in manifest.items():
        if (not isinstance(executable, str) or not Path(executable).is_absolute()
                or not isinstance(digest, str) or re.fullmatch('[0-9a-f]{64}',digest) is None):
            raise ValueError('Verified executable manifest has an invalid binding')
        key = str(Path(executable).resolve()).casefold()
        if key in result and result[key] != digest:
            raise ValueError('Verified executable manifest has conflicting canonical bindings')
        result[key] = digest
    return result


def read_launches(operation):
    return [json.loads(p.read_text(encoding='utf-8'))
            for p in sorted((operation / 'owned launch registry').glob('*.json'))]


def load_process_owner(root):
    path = root / 'downstream/security/bounded_process.py'
    before = sha256(path)
    spec = importlib.util.spec_from_file_location('s06_bounded_process_owner', path)
    owner = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = owner  # dataclass module lookup; no product package imports.
    spec.loader.exec_module(owner)
    if sha256(path) != before:
        raise RuntimeError('Process owner source changed while loading')
    owner.source_sha256 = before
    return owner


def process_identity(process):
    birth = process.create_time()
    item = {'pid': process.pid, 'birth': birth, 'exe': process.exe(),
            'cwd': process.cwd(), 'cmd': process.cmdline()}
    if process.create_time() != birth:
        raise RuntimeError('Process birth changed during identity probe')
    return item


def receipt_matches(recorded, source_hashes, go_binding):
    return (isinstance(recorded, dict) and recorded.get('source_unchanged') is True
            and recorded.get('sha256') == source_hashes and recorded.get('go_fixture') == go_binding
            and isinstance(recorded.get('results'), list) and bool(recorded['results'])
            and all(isinstance(result, dict) and result.get('result') == 'PASS' for result in recorded['results']))


def debug_epoch_complete(part, accounting):
    """Validate CREATE/EXIT evidence, rather than trusting a serialized PASS flag."""
    try:
        if (not isinstance(part,dict) or part.get('coverage_complete') is not True
                or not isinstance(accounting,(list,tuple)) or len(accounting) != 2
                or any(type(n) is not int for n in accounting)
                or not 0 < accounting[0] < 256 or accounting[1] != 0
                or list(part['job_counts']) != list(accounting)
                or any(type(n) is not int for n in part['job_counts'])
                or type(part['create_count']) is not int or part['create_count'] != accounting[0]):
            return False
        identities,exited = part['capture_identities'],part['exit_pids']
        if (not isinstance(identities,list) or not isinstance(exited,list)
                or len(identities) != accounting[0] or len(exited) != accounting[0]
                or any(type(pid) is not int or pid <= 0 for pid in exited)):
            return False
        pids,scopes = set(),set()
        for item in identities:
            proof = item['kernel_identity']
            pid = item['pid']
            if (type(pid) is not int or pid <= 0 or pid in pids
                    or item.get('captured_before_continue') is not True
                    or not all(item.get(k) for k in ('birth','exe','cwd','cmd','exe_sha256'))
                    or not isinstance(item['cmd'],list)
                    or type(proof['pid']) is not int or proof['pid'] != pid
                    or type(proof['creation_filetime']) is not int or proof['creation_filetime'] <= 0
                    or type(proof['wait_result']) is not int or proof['wait_result'] != 258
                    or proof.get('prior_live_identity') is not True or not proof['job_scope']):
                return False
            pids.add(pid)
            scopes.add(proof['job_scope'])
        return len(scopes) == 1 and pids == set(exited)
    except (KeyError,TypeError,ValueError):
        return False


def debug_observation_complete(record, before=None, after=None):
    try:
        if not isinstance(record,dict) or record.get('enabled') is not True:
            return False
        final = record['after_cleanup']
        before = record['job_counts'] if before is None else before
        after = final['job_counts'] if after is None else after
        return (debug_epoch_complete(record,before) and debug_epoch_complete(final,after)
                and list(before) == list(after)
                and record['capture_identities'] == final['capture_identities'])
    except (KeyError,TypeError,ValueError):
        return False


def acceptance_exit(returncode, timed_out, before, alive, listeners, receipt_ok, errors,
                    debug_observation=None):
    if timed_out:
        return 124
    if (before or alive or errors or not receipt_ok
            or not debug_observation_complete(debug_observation)
            or any(item.get('open') is not False for item in listeners)):
        return 1
    return returncode if isinstance(returncode, int) else 1


def gh_stages_passed(stages):
    """All former GH assertions, on three independently retained, bounded Jobs."""
    required = {
        'gh-large': {'hermes:git:review:diff-preserves-large-no-index-exit-one',
                     'hermes:git:fileDiff-preserves-large-no-index-exit-one'},
        'gh-positive': {'gh-preserves-operator-token-selected-git-and-noninteractive-policy',
                        'gh-ordinary-authentication-failure-remains-unavailable'},
        'gh-deadline': {'direct-gh-owned-descendant-deadline'},
    }
    try:
        if not isinstance(stages, list) or len(stages) != 3:
            return False
        receipts, operations = {}, set()
        for stage in stages:
            receipt, ledger = stage['receipt'], stage['ledger']
            mode = receipt['mode']
            if mode not in required or mode in receipts:
                return False
            if (receipt.get('native_os') != 'win32' or receipt.get('backend_started') is not False
                    or not receipt_matches(receipt, ledger['sha256'], ledger['go_fixture'])
                    or ledger.get('classification') != 'COMPLETED'
                    or ledger.get('exit_code') != 0 or ledger.get('child_exit_code') != 0
                    or ledger.get('timed_out') is not False or ledger.get('receipt_valid') is not True
                    or ledger.get('identity_errors') != []
                    or ledger.get('before_fixture_cleanup') != []
                    or ledger.get('remaining_after_fixture_cleanup') != []
                    or not debug_observation_complete(ledger.get('debug_observation'),
                        ledger.get('job_before_cleanup'),ledger.get('job_after_cleanup'))
                    or not stage_quiescent(stage)):
                return False
            if not required[mode].issubset({r['name'] for r in receipt['results']}):
                return False
            for key in ('job_before_cleanup', 'job_after_cleanup'):
                accounting = ledger[key]
                if (len(accounting) != 2 or any(type(n) is not int for n in accounting)
                        or not 0 < accounting[0] < 256 or accounting[1] != 0):
                    return False
            if any(p.get('open') is not False for p in ledger['post_fixture_cleanup_listeners']):
                return False
            if receipt['temp'] in operations:
                return False
            operations.add(receipt['temp'])
            receipts[mode] = receipt
        return (len(operations) == 3 and all(
            receipt['sha256'] == receipts['gh-large']['sha256']
            and receipt['go_fixture']['source_sha256'] == receipts['gh-large']['go_fixture']['source_sha256']
            for receipt in receipts.values()))
    except (KeyError, TypeError, ValueError):
        return False


def stage_quiescent(stage):
    """Permit another stage only after retained cleanup, never identity acceptance."""
    try:
        ledger = stage['ledger']
        counts = ledger['job_after_cleanup']
        handles = ledger['retained_handle_final_states']
        unsafe = {'parent_wait', 'parent_terminate', 'job_close', 'observation_close',
                  'retained_observation', 'debug_drain', 'debug_continue', 'popen_close'}
        debug = ledger['debug_observation']
        return (len(counts) == 2 and type(counts[1]) is int and counts[1] == 0
                and isinstance(debug,dict) and debug.get('enabled') is True
                and debug_epoch_complete(debug['after_cleanup'],counts)
                and bool(handles) and all(h['wait_result'] == 0 and h['state'] == 'EXITED' for h in handles)
                and not any(e.get('phase') in unsafe for e in ledger['identity_errors']))
    except (KeyError, TypeError):
        return False


class WindowsDebugEvents:
    """Private owned-root debugger, derived from the source-bound 20e9787 probe.

    Only Popen's DEBUG_PROCESS creates the debug relationship. No attach API,
    write-memory API, or process handle with terminate rights is exposed here.
    """
    def __init__(self):
        import ctypes as c
        from types import SimpleNamespace

        class FileTime(c.Structure):
            _fields_ = [('dwLowDateTime', c.c_uint32), ('dwHighDateTime', c.c_uint32)]

        # Windows LLP64 types must stay fixed-width even when the ABI is
        # decoded by a mocked adapter on a POSIX test host (LP64).
        t = SimpleNamespace(HANDLE=c.c_void_p, LPVOID=c.c_void_p,
                            DWORD=c.c_uint32, WORD=c.c_uint16,
                            BOOL=c.c_int32, FILETIME=FileTime)
        self.c, self.t = c, t
        self.thread = threading.get_ident()
        self.kernel = c.WinDLL('kernel32',use_last_error=True)
        class CreateInfo(c.Structure):
            _fields_ = [('file',t.HANDLE),('process',t.HANDLE),('thread',t.HANDLE),
                        ('base',t.LPVOID),('offset',t.DWORD),('size',t.DWORD),
                        ('tls',t.LPVOID),('start',t.LPVOID),('image',t.LPVOID),('unicode',t.WORD)]
        class ExceptionRecord(c.Structure):
            _fields_ = [('code',t.DWORD),('flags',t.DWORD),('record',t.LPVOID),
                        ('address',t.LPVOID),('count',t.DWORD),('information',c.c_size_t*15)]
        class ExceptionInfo(c.Structure):
            _fields_ = [('record',ExceptionRecord),('first_chance',t.DWORD)]
        class EventUnion(c.Union):
            _fields_ = [('create',CreateInfo),('exception',ExceptionInfo),('file',t.HANDLE),('exit_code',t.DWORD)]
        class DebugEvent(c.Structure):
            _fields_ = [('code',t.DWORD),('pid',t.DWORD),('tid',t.DWORD),('data',EventUnion)]
        if (c.sizeof(c.c_void_p) != 8 or c.sizeof(DebugEvent) != 176
                or DebugEvent.data.offset != 16 or c.sizeof(CreateInfo) != 72):
            raise RuntimeError('Unsupported native debug event ABI')
        self.Event = DebugEvent
        for name,args,result in [
            ('WaitForDebugEventEx',[c.POINTER(DebugEvent),t.DWORD],t.BOOL),
            ('ContinueDebugEvent',[t.DWORD,t.DWORD,t.DWORD],t.BOOL),
            ('GetCurrentProcess',[],t.HANDLE),
            ('GetProcessId',[t.HANDLE],t.DWORD),
            ('DuplicateHandle',[t.HANDLE,t.HANDLE,t.HANDLE,c.POINTER(t.HANDLE),t.DWORD,t.BOOL,t.DWORD],t.BOOL),
            ('CloseHandle',[t.HANDLE],t.BOOL),
            ('GetProcessTimes',[t.HANDLE]+[c.POINTER(t.FILETIME)]*4,t.BOOL),
            ('IsProcessInJob',[t.HANDLE,t.HANDLE,c.POINTER(t.BOOL)],t.BOOL),
            ('WaitForSingleObject',[t.HANDLE,t.DWORD],t.DWORD),
        ]:
            function = getattr(self.kernel,name)
            function.argtypes,function.restype = args,result

    def checked(self, value):
        if not value:
            raise self.c.WinError(self.c.get_last_error())
        return value

    def same_thread(self):
        if threading.get_ident() != self.thread:
            raise RuntimeError('Debug events require the creating thread')

    def wait(self, timeout_ms):
        self.same_thread()
        event = self.Event()
        if not self.kernel.WaitForDebugEventEx(self.c.byref(event),timeout_ms):
            if self.c.get_last_error() == 121:
                return None
            raise self.c.WinError(self.c.get_last_error())
        from types import SimpleNamespace
        result = SimpleNamespace(code=int(event.code),pid=int(event.pid),tid=int(event.tid),file=None)
        if event.code == 3:
            result.process,result.file = event.data.create.process,event.data.create.file
        elif event.code == 6:
            result.file = event.data.file
        elif event.code == 1:
            result.exception_code = int(event.data.exception.record.code)
            result.first_chance = int(event.data.exception.first_chance)
        return result

    def duplicate(self, handle):
        duplicate = self.t.HANDLE()
        own = self.kernel.GetCurrentProcess()
        self.checked(self.kernel.DuplicateHandle(own,handle,own,self.c.byref(duplicate),0x00101000,False,0))
        return self.checked(duplicate.value)

    def generation(self, handle, job, pid):
        times = [self.t.FILETIME() for _ in range(4)]
        self.checked(self.kernel.GetProcessTimes(handle,*(self.c.byref(value) for value in times)))
        member = self.t.BOOL()
        self.checked(self.kernel.IsProcessInJob(handle,job,self.c.byref(member)))
        actual_pid = self.checked(self.kernel.GetProcessId(handle))
        wait = self.kernel.WaitForSingleObject(handle,0)
        born = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        if actual_pid != pid or not member.value or wait != 258 or born <= 0:
            raise RuntimeError('CREATE HANDLE identity or retained Job membership is UNKNOWN')
        return {'pid':actual_pid,'creation_filetime':born,'wait_result':wait}

    def close(self, handle):
        self.checked(self.kernel.CloseHandle(handle))

    def continue_event(self, event, status):
        self.same_thread()
        self.checked(self.kernel.ContinueDebugEvent(event.pid,event.tid,status))


class DebugBirthPump:
    """Capture at CREATE, then continue. Classification remains the old registry contract."""
    def __init__(self, api, observer, job, errors, *, clock=time.monotonic):
        self.api,self.observer,self.job,self.errors,self.clock = api,observer,job,errors,clock
        self.thread = threading.get_ident()
        self.births,self.exited,self.breakpoints = {},set(),set()
        self.ready,self.events,self.pending = [],[],None
        self.max_events = 65536
        self.event_count = 0
        self.timings = dict(capture_seconds=0.0, continue_seconds=0.0,
                            registry_seconds=0.0, classify_seconds=0.0,
                            registry_reads=0, classification_passes=0)

    def error(self, phase, error, pid=None):
        self.errors.append({'phase':phase,'status':'UNKNOWN','pid':pid,
                            'error':type(error).__name__,'detail':str(error)})

    def handle(self, event, *, capture=True):
        if threading.get_ident() != self.thread:
            raise RuntimeError('Debug pump moved off its creating thread')
        # Failure before the exception branch must never turn an application
        # exception into DBG_CONTINUE. Only the verified first loader trap does.
        status = 0x80010001 if event.code == 1 else 0x00010002
        self.pending = (event,status)
        self.event_count += 1
        overflow = self.event_count > self.max_events
        started = self.clock()
        record = None
        if not overflow:
            record = {'event':event.code,'pid':event.pid,'tid':event.tid,'mono':started}
            if event.code == 1:
                record.update(exception_code=getattr(event,'exception_code',None),
                              first_chance=getattr(event,'first_chance',None),
                              continued_status=None)
            self.events.append(record)
        try:
            if event.code in (3,6) and getattr(event,'file',None):
                self.api.close(event.file)
                event.file = None
            if overflow and capture:
                raise RuntimeError('Debug event budget exceeded')
            if event.code == 3:
                if not capture:
                    raise RuntimeError('CREATE arrived only during cleanup; birth coverage is incomplete')
                if event.pid in self.births:
                    raise RuntimeError('Duplicate or reused CREATE generation')
                if len(self.births)+1 >= 256:
                    raise RuntimeError('CREATE process accounting reached strict 256 limit')
                duplicate = self.api.duplicate(event.process)
                seeded = False
                try:
                    generation = self.api.generation(duplicate,self.job,event.pid)
                    existing = self.observer.handles.get(event.pid)
                    prior_identity = dict(self.observer.identities.get(event.pid,{}))
                    if existing is not None:
                        prior = self.observer.proof(event.pid)
                        if (prior['creation_filetime'] != generation['creation_filetime']
                                or prior['pid'] != event.pid or prior['job_scope'] != self.observer.scope):
                            raise RuntimeError('Root CREATE differs from its retained generation')
                    else:
                        self.observer.handles[event.pid] = duplicate
                        seeded = True
                    item = self.observer.observe(psutil.Process(event.pid))
                    if existing is not None and any(item.get(key) != prior_identity.get(key)
                            for key in ('pid','birth','exe','cwd','cmd','exe_sha256')):
                        raise RuntimeError('Root CREATE changed its prior full identity')
                    proof = item['kernel_identity']
                    if (proof['pid'] != event.pid or proof['creation_filetime'] != generation['creation_filetime']
                            or proof['job_scope'] != self.observer.scope or proof['wait_result'] != 258
                            or proof.get('prior_live_identity') is not True
                            or not all(item.get(key) for key in ('exe','cwd','cmd','exe_sha256','birth'))):
                        raise RuntimeError('CREATE full live identity is UNKNOWN')
                    self.births[event.pid] = dict(item,captured_before_continue=True)
                    self.ready.append((psutil.Process(event.pid),item))
                finally:
                    if not seeded:
                        self.api.close(duplicate)
            elif event.code == 1:
                initial = (getattr(event,'first_chance',None) == 1
                    and getattr(event,'exception_code',None) == 0x80000003
                    and event.pid in self.births and event.pid not in self.breakpoints)
                if initial:
                    self.breakpoints.add(event.pid)
                    status = 0x00010002
                else:
                    status = 0x80010001
            elif event.code == 5:
                self.exited.add(event.pid)
            elif event.code not in (2,4,6,7,8):
                raise RuntimeError('RIP or unexpected debug event')
        except Exception as error:
            self.error('debug_event',error,event.pid)
        finally:
            # Even UNKNOWN metadata must release the producer. It never grants ownership.
            if event.code == 3:
                elapsed = self.clock()-started
                self.timings['capture_seconds'] += elapsed
                if record is not None:
                    record['capture_seconds'] = elapsed
            self.pending = (event,status)
            continued_at = self.clock()
            try:
                self.api.continue_event(event,status)
                if record is not None and event.code == 1:
                    record['continued_status'] = status
            except Exception as error:
                self.error('debug_continue',error,event.pid)
                raise
            finally:
                self.timings['continue_seconds'] += self.clock()-continued_at
            self.pending = None
        if overflow and capture:
            raise RuntimeError('Debug event budget exceeded; producer released for owned cleanup')

    def pump(self, deadline, *, capture=True, burst=64):
        if threading.get_ident() != self.thread:
            raise RuntimeError('Debug pump moved off its creating thread')
        if self.clock() >= deadline:
            raise TimeoutError('Debug pump exhausted its monotonic budget')
        slice_end = min(deadline,self.clock()+0.01)
        processed = 0
        while processed < burst and self.clock() < slice_end:
            remaining = max(0,int((slice_end-self.clock())*1000))
            event = self.api.wait(min(10,remaining) if processed == 0 else 0)
            if event is None:
                break
            self.handle(event,capture=capture)
            processed += 1
            if self.clock() >= deadline:
                raise TimeoutError('Debug event handling crossed the original deadline')
        return processed

    def release_pending(self):
        if self.pending is not None:
            event,status = self.pending
            self.api.continue_event(event,status)
            self.pending = None

    def coverage(self, counts):
        complete = (self.event_count <= self.max_events and counts is not None and len(counts) == 2
            and all(type(n) is int for n in counts) and 0 < counts[0] < 256 and counts[1] == 0
            and len(self.births) == counts[0] and set(self.births) == self.exited)
        return {'enabled':True,'coverage_complete':complete,'create_count':len(self.births),'job_counts':counts,
                'exit_pids':sorted(self.exited),'events':self.events,
                'capture_identities':list(self.births.values()),'event_limit':self.max_events,
                'event_count':self.event_count,'timings':dict(self.timings)}


def drain_debug_events(pump, process, job, owner, errors, deadline):
    """The creating thread continues EXIT before any retained root wait."""
    try:
        pump.release_pending()
        while time.monotonic() < deadline:
            pump.pump(deadline,capture=False)
            counts = owner._windows_job_process_counts(job)
            if counts[0] >= 256:
                # UNKNOWN/accounting overflow stays a refusal, but keep draining owned exits.
                if not any(e.get('phase') == 'debug_drain_accounting' for e in errors):
                    errors.append({'phase':'debug_drain_accounting','status':'UNKNOWN','counts':counts})
            if counts[1] == 0 and process.poll() is not None and process.pid in pump.exited:
                return
        raise TimeoutError('Retained root EXIT/Job quiescence did not drain in budget')
    except Exception as error:
        pump.error('debug_drain',error)


def supervise(command, root, operation, allowed, env, stream, *, owner=None, observer=None, auxiliary=None,
              debug_births=False, debug_api=None):
    observed, pending, errors, before, alive = {}, {}, [], [], []
    process, timed_out = None, False
    job = None
    descendant_state = 'UNKNOWN'
    job_before = job_after = None
    handle_states = []
    pump = None
    debug_record = None
    path_audit = None
    until = time.monotonic() + 90
    root_launch = {'operation':str(operation),'id':'fixture:root','exe':command[0],
                   'cwd':str(operation),'cmd':list(command),
                   'sha256':allowed.get(str(Path(command[0]).resolve()).casefold())}
    owner = owner or load_process_owner(root)
    try:
        job = owner._create_windows_job()
        if debug_births:
            api = debug_api if debug_api is not None else WindowsDebugEvents()
            if observer is None:
                manifest = dict(allowed)
                if auxiliary is not None:
                    manifest[str(Path(auxiliary['exe']).resolve()).casefold()] = auxiliary['sha256']
                observer = RetainedJobObservation(job,verified_manifest=manifest)
            pump = DebugBirthPump(api,observer,job,errors)
        process = subprocess.Popen(command, cwd=operation, env=env, stdin=subprocess.DEVNULL,
            stdout=stream, stderr=subprocess.STDOUT, close_fds=True,
            creationflags=0x08000000 | 0x00000004 | (1 if debug_births else 0))
        # Reuse the existing owner: no child executes before Job assignment.
        owner._assign_windows_job(job, process)
        if auxiliary is not None and observer is None:
            # These executable bytes were hashed by main before launch and are
            # revalidated after the run. Registry data never enters this cache.
            verified_manifest = dict(allowed)
            verified_manifest[str(Path(auxiliary['exe']).resolve()).casefold()] = auxiliary['sha256']
            observer = RetainedJobObservation(job, verified_manifest=verified_manifest)
        identify = observer.observe if observer is not None else process_identity
        parent = psutil.Process(process.pid)
        initial = identify(parent)
        if (Path(initial['exe']).resolve() != Path(command[0]).resolve()
                or initial['cmd'] != command or Path(initial['cwd']).resolve() != operation):
            raise RuntimeError('Initial fixture process identity is unknown')
        if observer is not None and initial['exe_sha256'] != allowed.get(str(Path(initial['exe']).resolve()).casefold()):
            raise RuntimeError('Initial retained executable hash is unknown')
        if observer is not None:
            initial = dict(initial,registered_launch=root_launch)
        observed[(initial['pid'], initial['birth'])] = (parent, initial)
        descendant_state = 'KNOWN'
        owner._resume_suspended_process(process.pid)

        def check_classification_budget():
            if debug_births and time.monotonic() >= until:
                raise TimeoutError('Final classification exhausted the original fixture deadline')

        def matches(item, launches):
            check_classification_budget()
            return owned_command(item,operation,allowed,root,launches,
                                 deadline=until if debug_births else None,
                                 resolver=path_audit.resolve if path_audit is not None else None)

        def classify_pending(launches):
            nonlocal descendant_state
            # First establish ordinary registered parents; then OS auxiliaries.
            for key, (child, item) in list(pending.items()):
                if matches(item, launches):
                    executable=(path_audit.resolve(item['exe']) if path_audit is not None
                                else Path(item['exe']).resolve())
                    if observer is not None and item['exe_sha256'] != allowed.get(str(executable).casefold()):
                        raise RuntimeError('Registered retained executable hash differs')
                    if observer is not None:
                        record = next(record for record in launches
                                      if matches(item,[record]))
                        item = dict(item,registered_launch=record)
                    observed[key] = (child, item)
                    del pending[key]
            if observer is None or auxiliary is None:
                return
            for key, (child, item) in list(pending.items()):
                check_classification_budget()
                if Path(item['exe']).resolve() != Path(auxiliary['exe']).resolve():
                    continue
                parent_pid = item['kernel_identity']['parent_pid']
                parents = [record for _p, record in observed.values()
                           if record['pid'] == parent_pid and record.get('classification') != 'OS_CONSOLE_AUXILIARY']
                if len(parents) != 1:
                    continue
                registered_parent = parents[0]
                parent_bound = (registered_parent is initial
                    or matches(registered_parent, launches))
                try:
                    associated_parent = observer.associate(item, registered_parent)
                except Exception as error:
                    descendant_state = 'UNKNOWN'
                    errors.append({'phase':'console_association','status':'UNKNOWN','identity':item,
                                   'registered_parent_generation':registered_parent,
                                   'error':type(error).__name__,'detail':str(error),
                                   'api':getattr(error,'observation_api',None),
                                   'winerror':getattr(error,'winerror',None),
                                   'errno':getattr(error,'errno',None),'traceback':traceback.format_exc()})
                    continue
                if owned_console_aux(item, operation, auxiliary, associated_parent, parent_bound, observer.scope):
                    item = dict(item, classification='OS_CONSOLE_AUXILIARY',
                                parent_generation=associated_parent)
                    observed[key] = (child,item)
                    del pending[key]

        while debug_births or process.poll() is None:
            if time.monotonic() > until:
                timed_out = True
                break
            if debug_births:
                pump.pump(until)
                for child,item in pump.ready:
                    key = (item['pid'],item['birth'])
                    if item['pid'] == initial['pid']:
                        if any(item.get(k) != initial.get(k) for k in ('pid','birth','exe','cwd','cmd','exe_sha256')):
                            raise RuntimeError('Debug root full identity changed')
                    else:
                        pending[key] = (child,item)
                pump.ready.clear()
                if errors:
                    descendant_state = 'UNKNOWN'
                children = []
                counts = owner._windows_job_process_counts(job)
                if counts[0] >= owner.MAX_BOUNDED_PROCESS_TREE_NODES:
                    raise RuntimeError('Debug Job accounting is UNKNOWN or reached 256')
            else:
                try:
                    children = parent.children(recursive=True)
                except psutil.NoSuchProcess:
                    children = []
            for child in children:
                try:
                    item = identify(child)
                    if observed.get((item['pid'],item['birth']), (None,{}))[1].get('classification') == 'OS_CONSOLE_AUXILIARY':
                        continue
                    pending[(item['pid'], item['birth'])] = (child, item)
                except psutil.NoSuchProcess:
                    if observer is not None:
                        descendant_state = 'UNKNOWN'
                        errors.append({'phase':'metadata_race','pid':child.pid,'status':'UNKNOWN'})
                except Exception as error:
                    # Unknown identity never becomes an ownership grant. Keep the
                    # result producer running within the original fixture budget,
                    # then reap through the same retained Job in finally.
                    descendant_state = 'UNKNOWN'
                    errors.append({'phase':'metadata_observation','pid':child.pid,'status':'UNKNOWN',
                                   'error':type(error).__name__,'detail':str(error),
                                   'api':getattr(error,'observation_api',None),
                                   'winerror':getattr(error,'winerror',None),
                                   'errno':getattr(error,'errno',None),'traceback':traceback.format_exc()})
            # CREATE identities are already retained before Continue. Registry
            # disk reads and exact classification run once in finally, so they
            # cannot hold the next debug event across a product probe deadline.
            if not debug_births:
                launches = read_launches(operation)
                classify_pending(launches)
            if debug_births:
                if process.poll() is not None and process.pid in pump.exited and counts[1] == 0:
                    if not pump.coverage(counts)['coverage_complete']:
                        raise RuntimeError('Terminal root lacks exact CREATE/EXIT coverage for its empty Job')
                    break
            else:
                time.sleep(.03)
    except Exception as error:
        descendant_state = 'UNKNOWN'
        if isinstance(error,TimeoutError):
            timed_out = True
        errors.append({'phase': 'observe', 'status': 'UNKNOWN', 'error': type(error).__name__,
                       'detail':str(error),'api':getattr(error,'observation_api',None),
                       'winerror':getattr(error,'winerror',None),'errno':getattr(error,'errno',None),
                       'traceback':traceback.format_exc()})
    finally:
        # The Go shim publishes immediately after entry. Never convert the
        # pre-publication observation race into an ownership grant or a PASS.
        try:
            if 'check_classification_budget' in locals():
                check_classification_budget()
            started = time.monotonic()
            try:
                launches = read_launches(operation)
                if debug_births:
                    # The fresh final records are an immutable value snapshot.
                    launches=json.loads(json.dumps(launches))
                    path_audit=FinalPathAudit(until)
            finally:
                if pump is not None:
                    pump.timings['registry_seconds'] += time.monotonic()-started
                    pump.timings['registry_reads'] += 1
            if 'check_classification_budget' in locals():
                check_classification_budget()
            if 'classify_pending' in locals():
                started = time.monotonic()
                try:
                    classify_pending(launches)
                finally:
                    if pump is not None:
                        pump.timings['classify_seconds'] += time.monotonic()-started
                        pump.timings['classification_passes'] += 1
            for key, (child, item) in pending.items():
                if matches(item, launches):
                    observed[key] = (child, item)
                else:
                    descendant_state = 'UNKNOWN'
                    errors.append({'phase': 'observe', 'pid': item['pid'], 'status': 'UNOWNED',
                                   'identity': item,
                                   'executable_sha256': allowed.get(str(path_audit.resolve(item['exe'])
                                       if path_audit is not None else Path(item['exe']).resolve()).casefold()),
                                   'previously_owned_identity': observed[key][1] if key in observed else None})
        except Exception as error:
            descendant_state = 'UNKNOWN'
            if isinstance(error,TimeoutError):
                timed_out = True
            errors.append({'phase': 'launch_registry', 'status': 'UNKNOWN', 'error': type(error).__name__})
        for (pid, birth), (child, item) in observed.items():
            try:
                if 'check_classification_budget' in locals():
                    check_classification_budget()
                retained = observer.observe(child) if debug_births else None
                current = ({key:retained[key] for key in ('pid','birth','exe','cwd','cmd')}
                           if debug_births else process_identity(child))
                base = {key:item[key] for key in ('pid','birth','exe','cwd','cmd')}
                changed = current != base
                if changed and all(current[key] == base[key] for key in ('pid','birth','exe','cmd')):
                    changed = not (matches(base,launches) and matches(current,launches))
                if 'check_classification_budget' in locals():
                    check_classification_budget()
                if changed:
                    descendant_state = 'UNKNOWN'
                    errors.append({'phase': 'cleanup', 'pid': pid, 'status': 'IDENTITY_CHANGED'})
                elif (retained['kernel_identity']['wait_result'] == 258 if debug_births else child.is_running()):
                    before.append(item)
            except psutil.NoSuchProcess:
                pass
            except Exception as error:
                descendant_state = 'UNKNOWN'
                if isinstance(error,TimeoutError):
                    timed_out = True
                errors.append({'phase': 'cleanup', 'pid': pid, 'status': 'UNKNOWN', 'error': type(error).__name__})
        try:
            if path_audit is not None:
                path_audit.verify()
                check_classification_budget()
            if job is not None:
                job_before = owner._windows_job_process_counts(job)
                if job_before[0] >= owner.MAX_BOUNDED_PROCESS_TREE_NODES:
                    raise RuntimeError('Job accounting is unknown or exceeded its limit')
                if debug_births and pump is not None:
                    debug_record = pump.coverage(job_before)
                    if not debug_record['coverage_complete']:
                        raise RuntimeError('CREATE/EXIT coverage differs from retained Job accounting before cleanup')
        except Exception as error:
            descendant_state = 'UNKNOWN'
            if isinstance(error,TimeoutError):
                timed_out = True
            errors.append({'phase': 'job_audit', 'status': 'UNKNOWN', 'error': type(error).__name__})
        if process is not None:
            try:
                # Only the retained Job and Popen handle; no PID/taskkill fallback.
                owner._terminate_process_tree(process, job)
            except Exception as error:
                descendant_state = 'UNKNOWN'
                errors.append({'phase':'parent_terminate','status':'UNKNOWN','error':type(error).__name__})
            cleanup_deadline = time.monotonic() + 5
            if pump is not None:
                drain_debug_events(pump,process,job,owner,errors,cleanup_deadline)
            try:
                process.wait(timeout=max(0,cleanup_deadline-time.monotonic()))
                if job is not None:
                    until = time.monotonic() + 2
                    while True:
                        job_after = owner._windows_job_process_counts(job)
                        if job_after[1] == 0 or time.monotonic() >= until:
                            break
                        time.sleep(.03)
                    if job_after[1] or job_after[0] >= owner.MAX_BOUNDED_PROCESS_TREE_NODES:
                        alive.append({'status': 'UNKNOWN', 'job_counts': job_after})
                        descendant_state = 'UNKNOWN'
            except Exception as error:
                descendant_state = 'UNKNOWN'
                errors.append({'phase': 'parent_wait', 'status': 'UNKNOWN', 'error': type(error).__name__})
        try:
            owner._close_windows_job(job)
        except Exception as error:
            descendant_state = 'UNKNOWN'
            errors.append({'phase': 'job_close', 'status': 'UNKNOWN', 'error': type(error).__name__})
        if observer is not None:
            try:
                handle_states, observation_errors = observer.close()
                if observation_errors:
                    descendant_state = 'UNKNOWN'
                    errors.extend(observation_errors)
            except Exception as error:
                descendant_state = 'UNKNOWN'
                errors.append({'phase':'observation_close','status':'UNKNOWN','error':type(error).__name__})
        if debug_births and process is not None:
            try:
                process._handle.Close()
            except Exception as error:
                descendant_state = 'UNKNOWN'
                errors.append({'phase':'popen_close','status':'UNKNOWN','error':type(error).__name__})
        if pump is not None:
            final_coverage = pump.coverage(job_after)
            if debug_record is None:
                debug_record = {'coverage_complete':False}
            debug_record['after_cleanup'] = final_coverage
            if not debug_record['coverage_complete'] or not final_coverage['coverage_complete'] or errors:
                descendant_state = 'UNKNOWN'
                if not any(e.get('phase') == 'debug_coverage' for e in errors):
                    errors.append({'phase':'debug_coverage','status':'UNKNOWN'})
    if descendant_state == 'UNKNOWN' and not alive:
        alive.append({'status': 'UNKNOWN', 'reason': 'incomplete_identity_observation'})
    if job_before is not None and job_before[1] and not before:
        before.append({'status': 'UNOBSERVED_JOB_MEMBER', 'job_counts': job_before})
    return {'identities': [item for _, item in observed.values()], 'before_fixture_cleanup': before,
            'remaining_after_fixture_cleanup': alive, 'identity_errors': errors,
            'descendant_state': descendant_state, 'listener_state': 'UNKNOWN',
            'job_before_cleanup': job_before, 'job_after_cleanup': job_after,
            'retained_handle_final_states': handle_states,
            'debug_observation': debug_record,
            'timed_out': timed_out, 'child_exit_code': process.returncode if process is not None else None}


def listener_probe(port, timeout=4):
    """Observe loopback connection completion; pending/timeout is never closed."""
    result = {'listener_open': None, 'listener_status': 'UNKNOWN', 'listener_errno': None}
    try:
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError('Invalid owned listener port')
        if not 0 < timeout <= 4:
            raise ValueError('Invalid listener observation bound')
        with socket.socket() as connection:
            connection.setblocking(False)
            code = connection.connect_ex(('127.0.0.1', port))
            result['listener_errno'] = code
            writable = code == 0
            if code in (10035, 10036, 10037, 115, 114):
                _, ready, exceptional = select.select([], [connection], [connection], timeout)
                if not ready and not exceptional:
                    return result
                code = connection.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                result['listener_errno'] = code
                writable = bool(ready)
            if code in (10061, 111):
                result.update(listener_open=False, listener_status='CLOSED')
            elif code == 0 and writable:
                result.update(listener_open=True, listener_status='OPEN')
    except Exception as error:
        result.update(listener_open=None, listener_status='UNKNOWN',
                      listener_error=type(error).__name__,
                      listener_errno=getattr(error, 'winerror', None) or getattr(error, 'errno', None))
    return result


def audit_native_receipt(ledger, recorded, hashes, binding):
    if not debug_observation_complete(ledger.get('debug_observation'),
            ledger.get('job_before_cleanup'),ledger.get('job_after_cleanup')):
        ledger.update(receipt_valid=False,descendant_state='UNKNOWN',listener_state='UNKNOWN')
        ledger['identity_errors'].append({'phase':'debug_coverage','status':'UNKNOWN'})
        ledger['post_fixture_cleanup_listeners'].append({'status':'UNKNOWN','open':None})
        return
    ledger['receipt_valid'] = receipt_matches(recorded, hashes, binding)
    if not ledger['receipt_valid']:
        ledger.update(descendant_state='UNKNOWN', listener_state='UNKNOWN')
        ledger['identity_errors'].append({'phase': 'native_receipt', 'status': 'UNKNOWN'})
        ledger['post_fixture_cleanup_listeners'].append({'status': 'UNKNOWN', 'open': None})
        return
    try:
        for result in recorded['results']:
            for identity in result.get('before', []):
                port = identity['port']
                if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
                    raise ValueError('Invalid owned listener port')
                probe = listener_probe(port)
                ledger['post_fixture_cleanup_listeners'].append(
                    dict(probe, port=port, status=probe['listener_status'], open=probe['listener_open']))
        ledger['listener_state'] = ('UNKNOWN' if any(p['open'] is None
            for p in ledger['post_fixture_cleanup_listeners']) else 'KNOWN')
    except Exception as error:
        ledger['listener_state'] = 'UNKNOWN'
        ledger['identity_errors'].append({'phase': 'listener_audit', 'status': 'UNKNOWN', 'error': type(error).__name__})
        ledger['post_fixture_cleanup_listeners'].append({'status': 'UNKNOWN', 'open': None})


def main():
    parser = argparse.ArgumentParser(description='Windows-owned Desktop Git/GH fixture; no external network or installs.')
    parser.add_argument('label')
    parser.add_argument('mode', nargs='?', choices=('git', 'gh', 'gh-large', 'gh-positive', 'gh-deadline', 'output', 'resolver', 'static'), default='git')
    parser.add_argument('--node', required=True, type=Path)
    parser.add_argument('--go', required=True, type=Path)
    parser.add_argument('--desktop-deps', required=True, type=Path)
    options = parser.parse_args()
    if options.mode != 'gh':
        return run_native_case(options)
    # No shared outer Job: each run creates, bounds, terminates and closes its
    # own Job before the next stage. Source equality is required across stages.
    stages = []
    assert re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,81}', options.label)
    for mode in ('gh-large', 'gh-positive', 'gh-deadline'):
        stage_options = argparse.Namespace(**vars(options))
        stage_options.label, stage_options.mode = options.label + '-' + mode, mode
        code = run_native_case(stage_options)
        folder = Path(__file__).resolve().parents[3] / 'tmp/s06-desktop-direct-evidence' / stage_options.label
        try:
            stages.append({'receipt': json.loads((folder / (stage_options.label + '.json')).read_text(encoding='utf-8')),
                           'ledger': json.loads((folder / (stage_options.label + '.ledger.json')).read_text(encoding='utf-8'))})
        except (OSError, ValueError):
            stages.append({'missing_stage': mode, 'exit_code': code})
        if not stage_quiescent(stages[-1]):
            break
    accepted = gh_stages_passed(stages)
    folder = Path(__file__).resolve().parents[3] / 'tmp/s06-desktop-direct-evidence' / options.label
    folder.mkdir(exist_ok=False)
    (folder / (options.label + '.stages.json')).write_text(
        json.dumps({'accepted': accepted, 'stages': stages}, indent=2) + '\n', encoding='utf-8', newline='\n')
    return 0 if accepted else 1


def run_native_case(options):
    assert re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,95}', options.label)
    assert sys.platform == 'win32', 'This fixture requires native Windows'
    assert all(p.is_absolute() and p.exists() for p in (options.node, options.go, options.desktop_deps))
    root = Path(__file__).resolve().parents[3]
    evidence = root / 'tmp/s06-desktop-direct-evidence' / options.label
    evidence.mkdir(parents=True, exist_ok=False)
    log = evidence / (options.label + '.log')
    ledger = {'classification': 'HARNESS_FAILURE_NOT_ACCEPTANCE', 'production_actions': [],
              'identity_errors': [], 'post_fixture_cleanup_listeners': [], 'exit_code': 1,
              'descendant_state': 'UNKNOWN', 'listener_state': 'UNKNOWN', 'receipt_valid': False}
    try:
        if psutil is None:
            raise RuntimeError('Native observer requires psutil')
        spec = importlib.util.spec_from_file_location('framework', root / 'scripts/ci/engineering_repair_mutations.py')
        framework = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(framework)
        operation = Path(tempfile.mkdtemp(prefix='s06-direct-owned-', dir=root / 'tmp')).resolve()
        (operation / 'owned launch registry').mkdir()
        git = shutil.which('git')
        if not git:
            raise RuntimeError('Git is unavailable')
        git = str(Path(git).resolve())
        env = framework.isolated_environment(operation / 'runtime', git)
        env.update(S06_GIT=git, S06_PYTHON=str(Path(sys.executable).resolve()), S06_DESKTOP_DEPS=str(options.desktop_deps),
                   S06_OPERATION_ROOT=str(operation), S06_EVIDENCE_DIR=str(evidence),
                   S06_OPERATION_ID='setup')
        env['GIT_CEILING_DIRECTORIES'] = env['TMP']
        cache = operation / 'go-build'
        cache.mkdir()
        build_env = dict(env, GOCACHE=str(cache / 'cache'), GOTMPDIR=str(cache), GOPROXY='off',
                         GOSUMDB='off', GOTOOLCHAIN='local', GOWORK='off')
        source = root / 'tests/windows/fixtures/s06_git_proxy_windows.go'
        source_hash = sha256(source)
        shim = operation / 'owned-git.exe'
        process_owner = load_process_owner(root)
        build = process_owner.run_bounded([str(options.go), 'build', '-o', str(shim), str(source)],
                                         cwd=operation, env=build_env, timeout=180)
        if build.returncode or build.output_truncated:
            raise RuntimeError('Owned Go fixture build did not complete')
        if sha256(source) != source_hash:
            raise RuntimeError('Go fixture source changed during build')
        binding = {'source_sha256': source_hash, 'exe_sha256': sha256(shim)}
        ledger['go_fixture'] = binding
        env.update(S06_GIT_SHIM=str(shim), S06_GO_SOURCE_SHA256=source_hash,
                   S06_GO_EXE_SHA256=binding['exe_sha256'])
        owners = ['hermes_cli/_subprocess_compat.py', 'agent/deadline.py', 'apps/desktop/electron/git-execution-policy.ts',
                  'downstream/security/bounded_process.py',
                  'apps/desktop/electron/git-ref-ops.ts', 'apps/desktop/electron/git-ipc.ts',
                  'apps/desktop/electron/git-worktree-ops.ts', 'apps/desktop/electron/git-review-ops.ts',
                  'apps/desktop/electron/main.ts', 'apps/desktop/assets/git-transport.cjs',
                  'tests/windows/fixtures/s06_git_proxy_windows.go',
                  'tests/windows/fixtures/s06_desktop_direct_native.mjs',
                  'tests/windows/fixtures/run_s06_desktop_direct_native.py']
        hashes = {owner: sha256(root / owner) for owner in owners}
        if hashes['downstream/security/bounded_process.py'] != process_owner.source_sha256:
            raise RuntimeError('Loaded process owner does not match source receipt')
        ledger['sha256'] = hashes
        git_aliases = [Path(git).parents[1] / flavor / 'bin/git.exe'
                       for flavor in ('ucrt64', 'mingw64')]
        git_aliases = [p.resolve() for p in git_aliases if p.is_file()]
        esbuild = options.desktop_deps / 'node_modules/@esbuild/win32-x64/esbuild.exe'
        taskkill = Path(env['SystemRoot']) / 'System32/taskkill.exe'
        # An explicit pre-existing tool identity; no package installation fallback.
        if not esbuild.is_file():
            raise RuntimeError('Bound Windows x64 esbuild executable is unavailable')
        binaries = [Path(p).resolve() for p in
                    (options.node, sys.executable, sys._base_executable, shim, git, esbuild, taskkill, *git_aliases)]
        allowed = {str(p).casefold(): sha256(p) for p in binaries}
        ledger['executable_bindings'] = allowed
        env.update(S06_EXECUTABLE_BINDINGS=json.dumps(allowed), S06_ESBUILD=str(esbuild.resolve()),
                   S06_TASKKILL=str(taskkill.resolve()), S06_SOURCE_ROOT=str(root),
                   S06_PYTHON_ALIASES=json.dumps([str(Path(sys.executable).resolve()),
                                                str(Path(sys._base_executable).resolve())]),
                   S06_PYTHON_ARGV0_ALIASES=json.dumps([{'exe':str(Path(sys._base_executable).resolve()),
                                                        'argv0':sys._base_executable}]),
                   S06_GIT_ALIASES=json.dumps([str(p) for p in git_aliases]))
        command = [str(options.node.resolve()), str(root / 'tests/windows/fixtures/s06_desktop_direct_native.mjs'),
                   options.label, options.mode]
        auxiliary = console_auxiliary_binding(operation)
        ledger['console_auxiliary_binding'] = auxiliary
        with log.open('wb') as stream:
            ledger.update(supervise(command, root, operation, allowed, env, stream, owner=process_owner,
                                    auxiliary=auxiliary,debug_births=True))
        try:
            recorded = json.loads(log.with_suffix('.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            recorded = None
        audit_native_receipt(ledger, recorded, hashes, binding)
        receipt_ok = ledger['receipt_valid']
        receipt_ok = receipt_ok and all(sha256(root / owner) == digest for owner, digest in hashes.items())
        receipt_ok = receipt_ok and all(sha256(p) == allowed[str(p).casefold()] for p in binaries)
        receipt_ok = receipt_ok and sha256(auxiliary['exe']) == auxiliary['sha256']
        ledger['receipt_valid'] = receipt_ok
        ledger['exit_code'] = acceptance_exit(ledger['child_exit_code'], ledger['timed_out'],
            ledger['before_fixture_cleanup'], ledger['remaining_after_fixture_cleanup'],
            ledger['post_fixture_cleanup_listeners'], receipt_ok, ledger['identity_errors'],
            ledger.get('debug_observation'))
        ledger['classification'] = ('COMPLETED' if ledger['exit_code'] == 0 else
            'HARNESS_TIMEOUT_NOT_ACCEPTANCE' if ledger['timed_out'] else 'HARNESS_FAILURE_NOT_ACCEPTANCE')
    except Exception as error:
        ledger['identity_errors'].append({'phase': 'harness', 'status': 'UNKNOWN', 'error': type(error).__name__})
        ledger['exit_code'] = 1
    finally:
        if ledger['listener_state'] == 'UNKNOWN' and not ledger['post_fixture_cleanup_listeners']:
            ledger['post_fixture_cleanup_listeners'].append({'status': 'UNKNOWN', 'open': None})
        log.with_suffix('.ledger.json').write_text(json.dumps(ledger, indent=2) + '\n', encoding='utf-8', newline='\n')
    if log.exists():
        sys.stdout.write(log.read_text(encoding='utf-8', errors='replace')[-5000:])
    return ledger['exit_code']


def run_self_checks():
    """Pure contracts only: no native build, subprocess, listener or runtime."""
    import pathlib, unittest, json
    from unittest.mock import Mock
    
    ns=globals()
    item={'pid':1,'birth':1.0,'exe':'trusted','cwd':'owned','cmd':['trusted'],
        'exe_sha256':'bound','captured_before_continue':True,
        'kernel_identity':{'pid':1,'creation_filetime':1,'wait_result':258,
            'prior_live_identity':True,'job_scope':'held-job'}}
    epoch={'coverage_complete':True,'create_count':1,'job_counts':[1,0],
        'exit_pids':[1],'capture_identities':[item]}
    debug=dict(epoch,enabled=True,after_cleanup=dict(epoch))
    class Checks(unittest.TestCase):
        def test_wrong_tmp_not_owned(self):
            root=pathlib.Path.cwd(); op=root/'tmp/unique'; exe=root/'node.exe'
            self.assertFalse(ns['owned_command']({'exe':str(exe),'cwd':str(root/'tmp/other'),'cmd':[str(exe),'other.mjs']},op,{str(exe.resolve()).casefold()},root))
        def test_root_python_requires_operation_payload(self):
            root=pathlib.Path.cwd(); op=root/'tmp/unique'; exe=root/'python.exe'
            item={'exe':str(exe),'cwd':str(root),'cmd':[str(exe),'-I','-B','-c','code',str(root)]}
            allowed={str(exe.resolve()).casefold()}
            self.assertFalse(ns['owned_command'](item,op,allowed,root))
            item['cmd'].append(json.dumps({'cwd':str(op/'repo')}))
            self.assertFalse(ns['owned_command'](item,op,allowed,root))
        def test_descendant_owned(self):
            root=pathlib.Path.cwd(); op=root/'tmp/unique'; exe=op/'owned-git.exe'
            item={'exe':str(exe),'cwd':str(op/'repo'),'cmd':[str(exe),'--owned-wait-descendant','1']}
            launch=dict(item,operation=str(op),id='descendant:1',sha256='bound')
            self.assertTrue(ns['owned_command'](item,op,{str(exe.resolve()).casefold():'bound'},root,[launch]))
        def test_precleanup_not_pass(self):
            self.assertNotEqual(ns['acceptance_exit'](0,False,[{'pid':1}],[],[],True,[],debug),0)
        def test_missing_receipt_not_pass(self):
            self.assertNotEqual(ns['acceptance_exit'](0,False,[],[],[],False,[],debug),0)
        def test_unknown_not_pass(self):
            self.assertNotEqual(ns['acceptance_exit'](0,False,[],[],[],True,['unknown'],debug),0)
        def test_valid_pass(self):
            self.assertEqual(ns['acceptance_exit'](0,False,[],[],[],True,[],debug),0)
        def test_changed_source_not_pass(self):
            self.assertFalse(ns['receipt_matches']({'source_unchanged':False,'results':[{'result':'PASS'}],'sha256':{'a':'hash'},'go_fixture':{'source_sha256':'s','exe_sha256':'e'}},{'a':'hash'},{'source_sha256':'s','exe_sha256':'e'}))
        def test_missing_binding_not_pass(self):
            self.assertFalse(ns['receipt_matches']({'source_unchanged':True,'results':[{'result':'PASS'}]}, {'a':'hash'},{'source_sha256':'s','exe_sha256':'e'}))
    return 0 if unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks)).wasSuccessful() else 1

if __name__ == '__main__':
    sys.exit(run_self_checks() if sys.argv[1:] == ['--self-check'] else main())

