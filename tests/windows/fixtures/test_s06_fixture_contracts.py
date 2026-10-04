"""S06 fixture contracts and separately selectable owned loopback controls.

Pure only: python -I -B <this file> OwnershipContracts MarkerSampleContracts.
Owned sockets only: python -I -B <this file> OwnedLoopbackObservationContracts.
The default runs both. Neither selection starts native child trees or builds.
Earlier RED/GREEN records below describe their historical source snapshots.
Repair evidence (2026-10-04; fixture scope only, native acceptance separate):

Input SHA256 before this repair, preserving pre-existing shared WIP:
run_s06_desktop_direct_native.py
  1c1836644353606ce76945480596c4b81c26c426138410c35609ee0be983ce45
s06_desktop_direct_native.mjs
  18328b7131e967f700a447a8aeb27c097f7ca1b17f557143d7727c2e76ec9ca7
s06_git_proxy_windows.go
  a07bcb37d89d2568b24ef872e34176d70b1ffa65778c0b36390fb98c405eb43f

RED: python -I -B test_s06_fixture_contracts.py: exit 1, 7 tests.
Three behavior FAILs: arbitrary Python code with incidental operation path,
Git -C outside the operation, and unknown listener incorrectly accepted.
Four API ERRORs (new registry/owner injection/receipt-audit helpers absent)
are recorded separately, not counted as reproduced behavioral failures.
RED: node --test s06_fixture_contracts.test.mjs: exit 1, 3 tests.
One behavior FAIL: null process/listener state incorrectly accepted.
Two new-helper TypeErrors. MJS had only import-safety/export scaffolding at
this RED step; its intermediate RED-byte hash was not captured.

GREEN: python -I -B test_s06_fixture_contracts.py: 14/14, exit 0.
GREEN: node --test --test-isolation=none s06_fixture_contracts.test.mjs:
  6/6, exit 0.
GREEN: python -I -B run_s06_desktop_direct_native.py --self-check:
  9/9, exit 0.
GREEN: node s06_desktop_direct_native.mjs --self-check: 9/9, exit 0.
Final four-command run used an environment allowlist (Windows OS paths,
unused HOME/USERPROFILE/HERMES_HOME, fixed UTC/LANG, no provider credentials,
no Python/Node injection flags). Python -I -B; Node test isolation disabled.
No product imports, real process probes/kills, sockets or builds in tests.
Fixture hashes were identical before and after the isolated GREEN run.

GREEN fixture SHA256:
run_s06_desktop_direct_native.py
  ecd06417cb63cc6875799df3511796582f3960918e9e5d5a5424185eaa4258e0
s06_desktop_direct_native.mjs
  edead72f2f88be57372b46d223542c6cc8bbef27612935115e7a5e5218659644
s06_git_proxy_windows.go
  b2832be7ad89038af161ef4406d393e15bcd680d3decc9032f7e41798641f203

Existing owner reused: downstream/security/bounded_process.py (retained
Windows Job + Popen handle, suspended creation/assignment/resume, accounting,
termination and close). Registry records only classify observations; they
never authorize bare PID signalling. Product taskkill commands are only
registered for this shim's own PID and exact bound owner cwd/argv; this
fixture never calls taskkill. agent/deadline.py is included in source binding.
Existing CodeGraph queried read-only for navigation; no refresh/index claim.

Unverified: Go compilation, Windows Job/API behavior and native reacceptance.
Additional oct4-final-git-1908 observer repair evidence (2026-10-04):
Old native label remains HARNESS_FAILURE_NOT_ACCEPTANCE: two 9 MiB IPC
diffs PASS; typed deadline refusal at 32855.9398 ms; three dead processes,
three unknown listeners. Job total=213, active=0; 50 UNOWNED observations.
Old pid-only records cannot prove which exact identities failed matching.
RED: Python 21 tests, 5 AssertionError FAIL / 16 PASS, exit 1; Node 7 tests,
1 AssertionError FAIL / 6 PASS, exit 1. Mocks reproduce slow refusal,
missing errno/exception/full identity evidence and forwarded Git argv binding.
Dead-owner independent port probing already passed before the repair.
GREEN: Python contracts 21, Node contracts 7, Python/MJS self-checks 9 each:
46 PASS / 0 FAIL. No sockets, native children, builds or product operations.
Unknown/timeout observations still FAIL; cleanup still uses retained Job only.
Updated fixture SHA256 (native rebuild/reacceptance remains unverified):
  run_s06_desktop_direct_native.py
    eb4bef4452b0fcb33890d4987d98f9d3d185b21cb65c4d1c3fb2f8438820e05d
  s06_desktop_direct_native.mjs
    7546e99045da208ab02e54c44519d5b8730798819a55fcaaab362b48e646e438
  s06_git_proxy_windows.go
    58eb661a3e46aa8a61db2140694414c2417f744bc495dcf1bb5a1bd7db19d01b

Current oct4-final-git-1933 repair adds four pure Python checks, two owned
ephemeral-loopback controls, and two pure Node checks. Pending socket outcomes
remain UNKNOWN; completion uses select exceptional/writable readiness and
SO_ERROR with a four-second maximum. Windows spawn hiding and exact registered
Git basename/Python launcher identities retain full argv/cwd/executable hashes.
Current-source receipt: docs/windows/selective-security-20261003/S06/
fixture-listener-owner-oct4-green.json (52 pure checks plus 2 socket controls).

Native fixture requires pre-existing Windows x64 esbuild. No install, heavy
native, production runtime, Git commit/push, other-source edits or thread
messages performed. Final independent review belongs to the separate reviewer.
"""
import importlib.util
import io
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location(
    's06_fixture', Path(__file__).with_name('run_s06_desktop_direct_native.py'))
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)


def complete_debug_record(count=1):
    identities = [{'pid':pid,'birth':float(pid),'exe':'trusted.exe','cwd':'owned',
                   'cmd':['trusted.exe'],'exe_sha256':'bound','captured_before_continue':True,
                   'kernel_identity':{'pid':pid,'creation_filetime':pid*100,
                       'wait_result':258,'prior_live_identity':True,'job_scope':'held-job'}}
                  for pid in range(1,count+1)]
    part = {'coverage_complete':True,'create_count':count,'job_counts':[count,0],
            'exit_pids':list(range(1,count+1)),'capture_identities':identities}
    return dict(part,enabled=True,after_cleanup=dict(part))


class DebugAcceptanceContracts(unittest.TestCase):
    def test_legacy_or_missing_debug_record_cannot_pass_native_acceptance(self):
        self.assertNotEqual(fixture.acceptance_exit(0,False,[],[],[],True,[]),0)

    def test_native_audit_requires_both_complete_debug_epochs_before_listener_queries(self):
        import copy
        valid = complete_debug_record()
        variants = [None,{},dict(valid,enabled=False),dict(valid,coverage_complete=False),
                    dict(valid,after_cleanup={}),dict(valid,after_cleanup=None)]
        changed = copy.deepcopy(valid)
        changed['after_cleanup']['job_counts']=[2,0]
        variants.append(changed)
        for record in variants:
            with self.subTest(record=record):
                ledger={'identity_errors':[],'post_fixture_cleanup_listeners':[],
                        'debug_observation':record,'job_before_cleanup':[1,0],
                        'job_after_cleanup':[1,0]}
                receipt={'source_unchanged':True,'sha256':{},'go_fixture':{},
                         'results':[{'result':'PASS','before':[{'port':12345}]}]}
                with patch.object(fixture,'listener_probe',return_value={
                        'listener_open':False,'listener_status':'CLOSED'}) as probe:
                    fixture.audit_native_receipt(ledger,receipt,{}, {})
                self.assertFalse(ledger['receipt_valid'])
                self.assertTrue(ledger['identity_errors'])
                probe.assert_not_called()

    def test_claimed_complete_without_exact_birth_generation_and_exit_union_is_refused(self):
        import copy
        for field,value in [('capture_identities',[]),('exit_pids',[]),('create_count',True),
                            ('job_counts',[256,0]),('coverage_complete',1)]:
            record=copy.deepcopy(complete_debug_record())
            record[field]=value
            stages=GhStageContracts().stages()
            stages[0]['ledger']['debug_observation']=record
            self.assertFalse(fixture.gh_stages_passed(stages))
        for field,value in [('captured_before_continue',False),('kernel_identity',{}),('cmd',[])]:
            stages=GhStageContracts().stages()
            stages[0]['ledger']['debug_observation']['capture_identities'][0][field]=value
            self.assertFalse(fixture.gh_stages_passed(stages))

    def test_each_gh_stage_requires_debug_optin_and_before_after_coverage(self):
        for index in range(3):
            for field in ('enabled','coverage_complete','after_cleanup'):
                stages=GhStageContracts().stages()
                del stages[index]['ledger']['debug_observation'][field]
                self.assertFalse(fixture.gh_stages_passed(stages))

    def test_next_stage_requires_after_debug_coverage_even_with_exited_handles(self):
        for record in (None,{},dict(complete_debug_record(200),enabled=False),
                       dict(complete_debug_record(200),after_cleanup={})):
            stage=GhStageContracts().stages()[0]
            stage['ledger']['debug_observation']=record
            self.assertFalse(fixture.stage_quiescent(stage))

    def test_valid_current_debug_record_can_pass_native_acceptance(self):
        import inspect
        kwargs = {'debug_observation':complete_debug_record()} if (
            'debug_observation' in inspect.signature(fixture.acceptance_exit).parameters) else {}
        self.assertEqual(fixture.acceptance_exit(0,False,[],[],[],True,[],**kwargs),0)


class OwnershipContracts(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[3]
        self.operation = self.root / 'tmp' / 's06-direct-owned-pure'
        self.repo = self.operation / 'owned spaced repo'
        self.python = self.root / 'python.exe'
        self.git = self.operation / 'git.exe'

    def item(self, exe, args, cwd=None):
        return {'exe': str(exe), 'cwd': str(cwd or self.repo),
                'cmd': [str(exe), *args]}

    def test_operation_path_does_not_authorize_arbitrary_python_code(self):
        item = self.item(self.python, ['-I', '-B', '-c', 'foreign_code()',
                         str(self.operation)], self.root)
        self.assertFalse(fixture.owned_command(item, self.operation,
            {str(self.python.resolve()).casefold()}, self.root))

    def test_git_word_does_not_authorize_external_repository(self):
        item = self.item(self.git, ['-C', str(self.root), 'status'])
        self.assertFalse(fixture.owned_command(item, self.operation,
            {str(self.git.resolve()).casefold()}, self.root))

    def test_exact_setup_launch_is_registered_and_owned(self):
        item = self.item(self.git, ['-C', str(self.repo), 'init', '--initial-branch=fixture'])
        launch = dict(item, operation=str(self.operation), id='setup:init', sha256='bound')
        self.assertTrue(fixture.owned_command(item, self.operation,
            {str(self.git.resolve()).casefold(): 'bound'}, self.root, [launch]))

    def test_exact_binding_rejects_each_identity_change(self):
        item = self.item(self.python, ['-I', '-B', '-c', 'known_code', '{"cwd":"owned"}'], self.root)
        launch = dict(item, operation=str(self.operation), id='policy:diff', sha256='bound')
        allowed = {str(self.python.resolve()).casefold(): 'bound'}
        self.assertTrue(fixture.owned_command(item, self.operation, allowed, self.root, [launch]))
        for field, value in [('exe', str(self.git)), ('cwd', str(self.operation)),
                             ('cmd', item['cmd'] + ['extra'])]:
            with self.subTest(field=field):
                self.assertFalse(fixture.owned_command(dict(item, **{field:value}),
                    self.operation, allowed, self.root, [launch]))
        self.assertFalse(fixture.owned_command(item, self.operation, allowed,
            self.root, [dict(launch, sha256='changed')]))
        self.assertFalse(fixture.owned_command(item, self.operation, allowed,
            self.root, [dict(launch, operation=str(self.root))]))

    def test_initial_probe_failure_is_unknown_and_reaps_retained_job(self):
        events = []
        process = Mock(pid=17, returncode=None)
        process.poll.side_effect = lambda: process.returncode
        process.wait.side_effect = lambda timeout: setattr(process, 'returncode', 1)
        owner = SimpleNamespace(
            _create_windows_job=lambda: 'retained-job',
            _assign_windows_job=lambda job,p: events.append(('assign', job, p)),
            _resume_suspended_process=lambda pid: events.append(('resume', pid)),
            _terminate_process_tree=lambda p,job: events.append(('terminate', job, p)),
            _close_windows_job=lambda job: events.append(('close', job)),
            _windows_job_process_counts=Mock(side_effect=[(1,1),(1,0)]),
            MAX_BOUNDED_PROCESS_TREE_NODES=256)
        fake_psutil = SimpleNamespace(Process=Mock(side_effect=RuntimeError('probe unavailable')),
                                     NoSuchProcess=ProcessLookupError, wait_procs=Mock(return_value=([],[])))
        with patch.object(fixture, 'psutil', fake_psutil), \
             patch.object(fixture.subprocess, 'Popen', return_value=process):
            result = fixture.supervise([str(self.python), 'fixture'], self.root,
                self.operation, {}, {}, Mock(), owner=owner)
        self.assertEqual(result['descendant_state'], 'UNKNOWN')
        self.assertEqual(result['listener_state'], 'UNKNOWN')
        self.assertIn(('terminate', 'retained-job', process), events)
        self.assertIn(('close', 'retained-job'), events)
        self.assertTrue(result['identity_errors'])

    def test_missing_native_json_never_reports_empty_listener_audit(self):
        ledger = {'identity_errors': [], 'post_fixture_cleanup_listeners': [],
                  'debug_observation':complete_debug_record(),
                  'job_before_cleanup':[1,0],'job_after_cleanup':[1,0]}
        fixture.audit_native_receipt(ledger, None, {}, {})
        self.assertIs(ledger['receipt_valid'], False)
        self.assertEqual(ledger['listener_state'], 'UNKNOWN')
        self.assertEqual(ledger['descendant_state'], 'UNKNOWN')
        self.assertTrue(ledger['post_fixture_cleanup_listeners'])
        self.assertNotEqual(fixture.acceptance_exit(0,False,[],[],
            ledger['post_fixture_cleanup_listeners'],False,ledger['identity_errors'],
            complete_debug_record()),0)

    def test_unknown_listener_cannot_pass_even_with_other_valid_evidence(self):
        self.assertNotEqual(fixture.acceptance_exit(0,False,[],[],
            [{'open':None,'status':'UNKNOWN'}],True,[],complete_debug_record()),0)

    def supervised(self, *, launches, assign_error=None, count=(2,0)):
        """In-memory process/Job doubles: never query or signal a real PID."""
        parent = Mock(pid=17)
        child = Mock(pid=18)
        command = [str(self.python), 'fixture']
        identities = {
            17: dict(self.item(self.python, ['fixture'], self.operation), pid=17, birth=1),
            18: dict(self.item(self.git, ['status']), pid=18, birth=2),
        }
        parent.children.return_value = [child]
        parent.is_running.return_value = child.is_running.return_value = False
        process = Mock(pid=17, returncode=0)
        process.poll.side_effect = [None,0]
        owner = SimpleNamespace(_create_windows_job=Mock(return_value='job'),
            _assign_windows_job=Mock(side_effect=assign_error),
            _resume_suspended_process=Mock(), _terminate_process_tree=Mock(),
            _close_windows_job=Mock(), _windows_job_process_counts=Mock(return_value=count),
            MAX_BOUNDED_PROCESS_TREE_NODES=256)
        fake_psutil = SimpleNamespace(Process=Mock(return_value=parent), NoSuchProcess=ProcessLookupError)
        record = dict(identities[18], operation=str(self.operation), id='git:status', sha256='bound')
        with patch.object(fixture,'psutil',fake_psutil), \
             patch.object(fixture.subprocess,'Popen',return_value=process) as spawn, \
             patch.object(fixture,'process_identity',side_effect=lambda p: identities[p.pid]), \
             patch.object(fixture,'read_launches',side_effect=launches(record)), \
             patch.object(fixture.time,'sleep'):
            result = fixture.supervise(command,self.root,self.operation,
                {str(self.git.resolve()).casefold():'bound'}, {}, Mock(),owner=owner)
        return result, owner, process, spawn, fake_psutil

    def test_late_exact_go_registration_is_resolved_before_cleanup(self):
        result, owner, process, spawn, _ = self.supervised(launches=lambda record:[[],[record]])
        self.assertEqual(result['descendant_state'],'KNOWN')
        self.assertEqual([p['pid'] for p in result['identities']],[17,18])
        self.assertEqual(result['identity_errors'],[])
        self.assertEqual(result['remaining_after_fixture_cleanup'],[])
        owner._terminate_process_tree.assert_called_once_with(process,'job')
        owner._close_windows_job.assert_called_once_with('job')
        self.assertTrue(spawn.call_args.kwargs['creationflags'] & 4)

    def test_unregistered_child_stays_unknown_even_when_job_is_empty(self):
        result, owner, process, _, _ = self.supervised(launches=lambda record:[[],[]])
        self.assertEqual(result['descendant_state'],'UNKNOWN')
        self.assertTrue(result['remaining_after_fixture_cleanup'])
        self.assertTrue(any(e['phase']=='observe' and e.get('pid')==18 and e['status']=='UNOWNED'
                            for e in result['identity_errors']))
        owner._terminate_process_tree.assert_called_once_with(process,'job')

    def test_unowned_error_retains_full_observed_identity_and_frozen_exe_binding(self):
        result, _, _, _, _ = self.supervised(launches=lambda record:[[],[]])
        error = next(e for e in result['identity_errors'] if e.get('status') == 'UNOWNED')
        self.assertEqual(error.get('identity'), dict(self.item(self.git,['status']), pid=18, birth=2))
        self.assertEqual(error.get('executable_sha256'), 'bound')
        self.assertEqual(result['descendant_state'], 'UNKNOWN')
        self.assertTrue(result['remaining_after_fixture_cleanup'])

    def test_assignment_failure_does_not_resume_or_probe_bare_pid(self):
        result, owner, process, _, fake_psutil = self.supervised(
            launches=lambda record:[[]],assign_error=RuntimeError('job assignment refused'))
        owner._resume_suspended_process.assert_not_called()
        fake_psutil.Process.assert_not_called()
        owner._terminate_process_tree.assert_called_once_with(process,'job')
        owner._close_windows_job.assert_called_once_with('job')
        self.assertEqual(result['descendant_state'],'UNKNOWN')

    def test_job_accounting_failure_is_unknown_even_with_zero_active(self):
        result, _, _, _, _ = self.supervised(launches=lambda record:[[record],[record]],count=(256,0))
        self.assertEqual(result['descendant_state'],'UNKNOWN')
        self.assertTrue(result['identity_errors'])
        self.assertTrue(result['remaining_after_fixture_cleanup'])

    def test_malformed_registration_is_not_authority(self):
        item = self.item(self.git,['status'])
        self.assertFalse(fixture.owned_command(item,self.operation,
            {str(self.git.resolve()).casefold():'bound'},self.root,[None]))

    def test_socket_timeout_is_unknown_not_closed(self):
        ledger = {'identity_errors':[], 'post_fixture_cleanup_listeners':[],
                  'debug_observation':complete_debug_record(),
                  'job_before_cleanup':[1,0],'job_after_cleanup':[1,0]}
        receipt = {'source_unchanged':True,'sha256':{},'go_fixture':{},
                   'results':[{'result':'PASS','before':[{'port':12345}]}]}
        connection = Mock()
        connection.connect_ex.return_value = 10060
        socket_context = Mock()
        socket_context.__enter__ = Mock(return_value=connection)
        socket_context.__exit__ = Mock(return_value=False)
        with patch.object(fixture.socket,'socket',return_value=socket_context):
            fixture.audit_native_receipt(ledger,receipt,{}, {})
        self.assertEqual(ledger['listener_state'],'UNKNOWN')
        self.assertIsNone(ledger['post_fixture_cleanup_listeners'][0]['open'])

    def test_source_mismatch_keeps_listener_unknown_without_socket_probe(self):
        ledger = {'identity_errors':[], 'post_fixture_cleanup_listeners':[],
                  'debug_observation':complete_debug_record(),
                  'job_before_cleanup':[1,0],'job_after_cleanup':[1,0]}
        receipt = {'source_unchanged':True,'sha256':{'source':'changed'},'go_fixture':{},
                   'results':[{'result':'PASS'}]}
        with patch.object(fixture.socket,'socket') as socket_probe:
            fixture.audit_native_receipt(ledger,receipt,{'source':'bound'}, {})
        socket_probe.assert_not_called()
        self.assertEqual(ledger['listener_state'],'UNKNOWN')
        self.assertEqual(ledger['descendant_state'],'UNKNOWN')
        self.assertEqual(ledger['identity_errors'][0]['phase'],'native_receipt')

    def test_receipt_listener_audit_allows_bounded_slow_refusal(self):
        ledger = {'identity_errors':[], 'post_fixture_cleanup_listeners':[],
                  'debug_observation':complete_debug_record(),
                  'job_before_cleanup':[1,0],'job_after_cleanup':[1,0]}
        receipt = {'source_unchanged':True,'sha256':{},'go_fixture':{},
                   'results':[{'result':'PASS','before':[{'port':12345}]}]}
        connection = Mock()
        connection.connect_ex.return_value = 10035
        connection.getsockopt.return_value = 10061
        socket_context = Mock()
        socket_context.__enter__ = Mock(return_value=connection)
        socket_context.__exit__ = Mock(return_value=False)
        with patch.object(fixture.socket,'socket',return_value=socket_context), \
             patch.object(fixture.select,'select',return_value=([],[],[connection])) as wait:
            fixture.audit_native_receipt(ledger,receipt,{}, {})
        self.assertEqual(ledger['listener_state'],'KNOWN')
        self.assertIs(ledger['post_fixture_cleanup_listeners'][0]['open'],False)
        self.assertLessEqual(wait.call_args.args[3],4)


class ConsoleAuxiliaryContracts(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[3]
        self.operation = self.root/'tmp/owned-console-pure'
        self.trust = {'operation':str(self.operation), 'exe':str(self.root/'trusted-system32/conhost.exe'),
                      'cwd':str(self.root/'trusted-windows'), 'cmd':[str(self.root/'trusted-system32/conhost.exe'),'0x4'],
                      'sha256':'console-hash'}
        self.parent = {'pid':17,'birth':1.0,'exe':str(self.root/'node.exe'),
                       'cmd':[str(self.root/'node.exe'),'bound-code'], 'cwd':str(self.operation),
                       'kernel_identity':{'pid':17,'creation_filetime':100,'exit_filetime':0,
                                          'exe':str(self.root/'node.exe'),'job_scope':'retained-job',
                                          'console_host_pid':18,'wait_result':258}}
        self.child = {'pid':18,'birth':2.0,'exe':self.trust['exe'],'cwd':self.trust['cwd'],
                      'cmd':self.trust['cmd'],'exe_sha256':'console-hash',
                      'kernel_identity':{'pid':18,'creation_filetime':200,'exit_filetime':0,
                                         'exe':self.trust['exe'],'parent_pid':17,'job_scope':'retained-job'}}

    def owned(self, child=None, parent=None, registered=True, scope='retained-job', trust=None):
        return fixture.owned_console_aux(child or self.child, self.operation, trust or self.trust,
                                         parent or self.parent, registered, scope)

    def test_exact_console_child_of_registered_retained_parent_is_owned(self):
        self.assertTrue(self.owned())

    def test_console_parent_must_be_registered_and_same_retained_job(self):
        self.assertFalse(self.owned(registered=False))
        self.assertFalse(self.owned(scope='another-job'))
        parent = dict(self.parent, kernel_identity=dict(self.parent['kernel_identity'],job_scope='another-job'))
        self.assertFalse(self.owned(parent=parent))
        for value in (0,99,None):
            parent = dict(self.parent,kernel_identity=dict(self.parent['kernel_identity'],console_host_pid=value))
            self.assertFalse(self.owned(parent=parent))

    def test_console_exact_exe_argv_cwd_and_hash_are_all_required(self):
        for key, value in [('exe',str(self.root/'other/conhost.exe')),('cwd',str(self.operation)),
                           ('cmd',self.trust['cmd']+['extra']),('exe_sha256','different')]:
            with self.subTest(key=key):
                self.assertFalse(self.owned(child=dict(self.child, **{key:value})))

    def test_console_kernel_pid_parent_generation_and_creation_order_are_required(self):
        for key, value in [('pid',99),('parent_pid',99),('creation_filetime',50),('job_scope','foreign'),('exe','foreign')]:
            with self.subTest(key=key):
                child = dict(self.child,kernel_identity=dict(self.child['kernel_identity'],**{key:value}))
                self.assertFalse(self.owned(child=child))
        for changed in ({'exit_filetime':150},{'exit_filetime':250},{'wait_result':0},{'wait_result':0xffffffff}):
            parent = dict(self.parent,kernel_identity=dict(self.parent['kernel_identity'],**changed))
            self.assertFalse(self.owned(parent=parent))

    def test_console_missing_kernel_metadata_and_cross_operation_stay_unknown(self):
        for key in self.child['kernel_identity']:
            proof = dict(self.child['kernel_identity']); del proof[key]
            self.assertFalse(self.owned(child=dict(self.child,kernel_identity=proof)))
        self.assertFalse(self.owned(trust=dict(self.trust,operation=str(self.root))))
        self.assertFalse(self.owned(child=dict(self.child,kernel_identity=None)))

    def test_git_worker_registered_full_argv_allows_only_its_exact_C_cwd_transition(self):
        exe = self.root/'trusted-git/ucrt64/bin/git.exe'
        repo = self.operation/'owned spaced repo'
        argv = ['git.exe','-C',str(repo),'config','--includes','--show-origin','-z','--get-regexp','bound-pattern']
        launch = {'exe':str(exe),'cmd':argv,'cwd':str(self.root),'sha256':'git-hash',
                  'operation':str(self.operation),'id':'hermes:git:fileDiff'}
        item = dict(launch,cwd=str(repo))
        allowed = {str(exe.resolve()).casefold():'git-hash'}
        self.assertTrue(fixture.owned_command(item,self.operation,allowed,self.root,[launch]))
        for changed in [dict(item,cwd=str(self.operation/'other')),
                        dict(item,cmd=argv+['extra']),dict(item,exe=str(self.root/'other/git.exe'))]:
            self.assertFalse(fixture.owned_command(changed,self.operation,allowed,self.root,[launch]))
        self.assertFalse(fixture.owned_command(item,self.operation,allowed,self.root,[dict(launch,sha256='other')]))
        python = self.root/'python.exe'
        changed_launch = dict(launch,exe=str(python))
        self.assertFalse(fixture.owned_command(dict(item,exe=str(python)),self.operation,
            {str(python.resolve()).casefold():'git-hash'},self.root,[changed_launch]))

    def test_git_worker_C_transition_rejects_wrong_prefix_duplicate_and_unbound_origins(self):
        exe = self.root/'trusted-git/ucrt64/bin/git.exe'
        repo = self.operation/'owned spaced repo'
        allowed = {str(exe.resolve()).casefold():'git-hash'}
        tail = ['config','--includes','--show-origin','-z','--get-regexp','bound-pattern']
        commands = [
            ['git.exe','-c','bound=value','-C',str(repo),*tail],
            ['git.exe','-C',str(repo),'-C',str(repo),*tail],
            ['git.exe','-C',str(self.root),*tail],
            ['git.exe','-C',str(repo.relative_to(self.root)),*tail],
        ]
        for command in commands:
            with self.subTest(command=command):
                launch = {'exe':str(exe),'cwd':str(self.root),'cmd':command,'sha256':'git-hash',
                          'operation':str(self.operation),'id':'hermes:git:fileDiff'}
                item = dict(launch,cwd=str(repo))
                self.assertFalse(fixture.owned_command(item,self.operation,allowed,self.root,[launch]))
        command = ['git.exe','-C',str(repo),*tail]
        launch = {'exe':str(exe),'cwd':str(self.operation/'unregistered runtime'),'cmd':command,
                  'sha256':'git-hash','operation':str(self.operation),'id':'hermes:git:fileDiff'}
        self.assertFalse(fixture.owned_command(dict(launch,cwd=str(repo)),self.operation,allowed,self.root,[launch]))

    def console_supervised(self, *, query_error=None, alive=False, close_errors=(), metadata_error=None):
        parent = Mock(pid=17)
        child = Mock(pid=18)
        parent.children.return_value = [child]
        parent.is_running.return_value = False
        child.is_running.return_value = alive
        process = Mock(pid=17,returncode=0)
        process.poll.side_effect = [None,0]
        initial = dict(self.parent,exe_sha256='parent-hash')
        def observe(p):
            if p.pid == 17:
                return initial
            if metadata_error:
                raise metadata_error
            return self.child
        observer = SimpleNamespace(scope='retained-job',
            observe=Mock(side_effect=observe),
            associate=Mock(return_value=initial,side_effect=query_error),
            close=Mock(return_value=([],list(close_errors))))
        owner = SimpleNamespace(_create_windows_job=Mock(return_value='job'),
            _assign_windows_job=Mock(),_resume_suspended_process=Mock(),
            _terminate_process_tree=Mock(),_close_windows_job=Mock(),
            _windows_job_process_counts=Mock(return_value=(2,0)),MAX_BOUNDED_PROCESS_TREE_NODES=256)
        fake_psutil = SimpleNamespace(Process=Mock(return_value=parent),NoSuchProcess=ProcessLookupError)
        with patch.object(fixture,'psutil',fake_psutil), \
             patch.object(fixture.subprocess,'Popen',return_value=process), \
             patch.object(fixture,'read_launches',return_value=[]), \
             patch.object(fixture,'process_identity',side_effect=lambda p: {k:v for k,v in
                          (initial if p.pid == 17 else self.child).items()
                          if k in ('pid','birth','exe','cwd','cmd')}):
            result = fixture.supervise(initial['cmd'],self.root,self.operation,
                {str(Path(initial['exe']).resolve()).casefold():'parent-hash'}, {}, Mock(),owner=owner,
                observer=observer,auxiliary=self.trust)
        owner._terminate_process_tree.assert_called_once_with(process,'job')
        owner._close_windows_job.assert_called_once_with('job')
        observer.close.assert_called_once_with()
        if metadata_error:
            self.assertEqual(process.poll.call_count,2,
                'UNKNOWN observation must not prematurely stop the native result producer')
        return result

    def test_child_metadata_failure_keeps_unknown_but_waits_for_native_terminal_result(self):
        error = PermissionError(31,'QueryFullProcessImageNameW: process exited')
        result = self.console_supervised(metadata_error=error)
        self.assertEqual(result['descendant_state'],'UNKNOWN')
        row = next(row for row in result['identity_errors'] if row['phase']=='metadata_observation')
        self.assertEqual(row['pid'],18)
        self.assertEqual(row['error'],'PermissionError')
        self.assertIn('QueryFullProcessImageNameW',row['detail'])
        self.assertEqual(row['errno'],31)
        self.assertNotEqual(fixture.acceptance_exit(0,False,[],[],[],True,result['identity_errors'],
            complete_debug_record()),0)

    def test_console_query_error_cannot_classify_and_still_reaps_retained_job(self):
        result = self.console_supervised(query_error=RuntimeError('console query UNKNOWN'))
        self.assertEqual(result['descendant_state'],'UNKNOWN')
        self.assertTrue(result['identity_errors'])
        error = next(row for row in result['identity_errors'] if row['phase'] == 'console_association')
        self.assertEqual(error['identity'],self.child)
        self.assertEqual(error['registered_parent_generation']['pid'],17)
        self.assertEqual(error['detail'],'console query UNKNOWN')

    def test_supervisor_accepts_only_complete_console_association(self):
        result = self.console_supervised()
        self.assertEqual(result['descendant_state'],'KNOWN')
        self.assertEqual(result['identity_errors'],[])
        self.assertEqual(result['identities'][1]['classification'],'OS_CONSOLE_AUXILIARY')
        self.assertEqual(result['identities'][1]['parent_generation']['pid'],17)

    def test_classified_console_alive_before_cleanup_still_fails_acceptance(self):
        result = self.console_supervised(alive=True)
        self.assertTrue(result['before_fixture_cleanup'])
        self.assertNotEqual(fixture.acceptance_exit(0,False,result['before_fixture_cleanup'],
            result['remaining_after_fixture_cleanup'],[],True,result['identity_errors'],
            complete_debug_record()),0)

    def test_observation_handle_close_error_stays_unknown_even_with_empty_job(self):
        result = self.console_supervised(close_errors=[{'phase':'observation_close','status':'UNKNOWN'}])
        self.assertEqual(result['descendant_state'],'UNKNOWN')
        self.assertTrue(result['remaining_after_fixture_cleanup'])

    def fake_kernel_observer(self, *, self_pid=18, member=True, status=0):
        import ctypes
        from ctypes import wintypes
        observer = fixture.RetainedJobObservation.__new__(fixture.RetainedJobObservation)
        observer.ctypes,observer.types,observer.job = ctypes,wintypes,'job'
        observer.scope,observer.handles,observer.generations = 'retained-job',{},{}
        observer.identities,observer.identity_handles = {},{}
        def times(_handle,*values):
            values[0]._obj.dwLowDateTime = 200
            return 1
        def image(_handle,_flags,buffer,_size):
            buffer.value = self.trust['exe']; return 1
        def membership(_handle,job,value):
            self.assertEqual(job,'job'); value._obj.value = member; return 1
        def basic(_handle,info_class,info,_length,_size):
            self.assertEqual(info_class,0)
            info._obj.pid,info._obj.parent = self_pid,17
            return status
        observer.kernel = SimpleNamespace(OpenProcess=Mock(return_value='owned-handle'),
            GetProcessTimes=times,QueryFullProcessImageNameW=image,IsProcessInJob=membership,
            WaitForSingleObject=Mock(return_value=258))
        observer.native = SimpleNamespace(NtQueryInformationProcess=basic)
        observer.checked = lambda value,api=None: value if value else (_ for _ in ()).throw(RuntimeError('UNKNOWN'))
        return observer

    def test_actual_kernel_adapter_rejects_self_pid_job_and_query_errors(self):
        for changes in ({'self_pid':99},{'member':False},{'status':-1}):
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                self.fake_kernel_observer(**changes).proof(18)

    def test_actual_kernel_adapter_pins_handle_and_creation_generation(self):
        observer = self.fake_kernel_observer()
        first = observer.proof(18)
        self.assertEqual(first['parent_pid'],17)
        self.assertEqual(first['job_scope'],'retained-job')
        observer.proof(18)
        observer.kernel.OpenProcess.assert_called_once_with(0x00101000,False,18)
        observer.generations[18] = 99
        with self.assertRaises(RuntimeError):
            observer.proof(18)

    def test_actual_parent_adapter_rejects_changed_creation_generation(self):
        observer = self.fake_kernel_observer()
        observer.proof = Mock(return_value=dict(self.parent['kernel_identity'],creation_filetime=99))
        with self.assertRaises(RuntimeError):
            observer.associate(self.child,self.parent)

    def test_actual_parent_adapter_requires_live_parent_and_successful_console_query(self):
        for failure in ('closed','exited','query-error','exit-during-query'):
            with self.subTest(failure=failure):
                observer = self.fake_kernel_observer()
                observer.handles[17] = 100
                proof = dict(self.parent['kernel_identity'],exit_filetime=1 if failure == 'closed' else 0)
                observer.proof = Mock(return_value=proof)
                observer.kernel.WaitForSingleObject = Mock(side_effect=[
                    0 if failure == 'exited' else 258,
                    0 if failure == 'exit-during-query' else 258])
                def query(_handle,info_class,value,_length,_size):
                    self.assertEqual(info_class,49)
                    value._obj.value = 21
                    return -1 if failure == 'query-error' else 0
                observer.native.NtQueryInformationProcess = query
                with self.assertRaises(RuntimeError):
                    observer.associate(self.child,self.parent)


class RetiredConsoleParentContracts(unittest.TestCase):
    setUp = ConsoleAuxiliaryContracts.setUp

    def pair(self):
        parent = dict(self.parent,exe_sha256='parent-hash',kernel_identity=dict(
            self.parent['kernel_identity'],exit_filetime=250,wait_result=0,
            association='RETIRED_PARENT_INTERVAL',prior_live_identity=True))
        child = dict(self.child,kernel_identity=dict(self.child['kernel_identity'],prior_live_identity=True))
        del parent['kernel_identity']['console_host_pid']
        return child,parent

    def observer(self):
        import ctypes
        from ctypes import wintypes
        observer = fixture.RetainedJobObservation.__new__(fixture.RetainedJobObservation)
        observer.ctypes,observer.types,observer.job = ctypes,wintypes,'job'
        observer.scope = 'retained-job'
        observer.handles = {17:100,18:200}
        observer.generations = {17:100,18:200}
        parent = dict(self.parent,exe_sha256='parent-hash')
        observer.identities = {17:parent,18:self.child}
        observer.identity_handles = {17:100,18:200}
        # Prior live observations are in-memory, never registry-provided evidence.
        observer.identities = {pid:dict(item,kernel_identity=dict(item['kernel_identity'],
            prior_live_identity=True)) for pid,item in observer.identities.items()}
        observer.digests = {}
        state = {'born':{17:100,18:200},'exit':{17:250,18:260},'wait':{17:0,18:0},
                 'job':{17:True,18:True},'query_error':False,'pid_override':{},'parent_override':{}}
        by_handle = {100:17,200:18}
        def times(handle,*values):
            pid=by_handle[handle]
            values[0]._obj.dwLowDateTime=state['born'][pid]
            values[1]._obj.dwLowDateTime=state['exit'][pid]
            return 0 if state['query_error'] else 1
        def member(handle,job,value):
            self.assertEqual(job,'job');value._obj.value=state['job'][by_handle[handle]];return 1
        def image(handle,_flags,buffer,_size):
            pid=by_handle[handle]
            if state['wait'][pid]==0:
                raise RuntimeError('QueryImage must not run on previously known retired HANDLE')
            buffer.value=(self.parent if pid==17 else self.child)['exe'];return 1
        def native(handle,info_class,value,_length,_size):
            pid=by_handle[handle]
            if info_class==0:
                value._obj.pid=state['pid_override'].get(pid,pid)
                value._obj.parent=state['parent_override'].get(pid,17 if pid==18 else 9)
                return 0
            self.assertEqual(info_class,49)
            value._obj.value=18;return -1 if state['query_error'] else 0
        observer.kernel = SimpleNamespace(GetProcessTimes=times,IsProcessInJob=member,
            QueryFullProcessImageNameW=Mock(side_effect=image),
            WaitForSingleObject=Mock(side_effect=lambda handle,_timeout:state['wait'][by_handle[handle]]),
            OpenProcess=Mock(side_effect=AssertionError('Must not reopen continuously held generation')))
        observer.native = SimpleNamespace(NtQueryInformationProcess=Mock(side_effect=native))
        observer.checked = lambda value,api=None:value if value else (_ for _ in ()).throw(RuntimeError('UNKNOWN '+str(api)))
        return observer,state

    def test_retired_parent_exact_interval_is_accepted_without_live_console_query(self):
        child,parent=self.pair()
        self.assertTrue(fixture.owned_console_aux(child,self.operation,self.trust,parent,True,'retained-job'))

    def test_actual_retired_adapter_uses_both_continuous_handles_and_never_queries_dead_image(self):
        observer,_state=self.observer()
        try:
            parent=observer.associate(self.child,dict(self.parent,exe_sha256='parent-hash'))
        except Exception as error:
            self.fail('Known retired generation must use interval proof: '+str(error))
        child=dict(self.child,kernel_identity=dict(self.child['kernel_identity'],prior_live_identity=True))
        self.assertTrue(fixture.owned_console_aux(child,self.operation,self.trust,parent,True,'retained-job'))
        observer.kernel.OpenProcess.assert_not_called()
        observer.kernel.QueryFullProcessImageNameW.assert_not_called()
        self.assertTrue(all(call.args[1]==0 for call in observer.native.NtQueryInformationProcess.call_args_list))

    def test_retired_interval_missing_reversed_outside_or_unconfirmed_exit_is_refused(self):
        child,parent=self.pair()
        for changes in ({'exit_filetime':0},{'exit_filetime':199},{'exit_filetime':None},
                        {'creation_filetime':201},{'wait_result':258},{'wait_result':0xffffffff},
                        {'prior_live_identity':False},{'association':'unrecognized'}):
            changed=dict(parent,kernel_identity=dict(parent['kernel_identity'],**changes))
            self.assertFalse(fixture.owned_console_aux(child,self.operation,self.trust,changed,True,'retained-job'))
        for key in ('exit_filetime','creation_filetime','wait_result','prior_live_identity','association'):
            proof=dict(parent['kernel_identity']);del proof[key]
            self.assertFalse(fixture.owned_console_aux(child,self.operation,self.trust,dict(parent,kernel_identity=proof),True,'retained-job'))

    def test_retired_child_exact_metadata_hash_pid_parent_and_job_are_required(self):
        child,parent=self.pair()
        for field,value in [('exe','foreign'),('cwd','foreign'),('cmd',['foreign']),('exe_sha256','foreign')]:
            self.assertFalse(fixture.owned_console_aux(dict(child,**{field:value}),self.operation,self.trust,parent,True,'retained-job'))
        for field,value in [('pid',99),('parent_pid',99),('job_scope','foreign'),('prior_live_identity',False)]:
            changed=dict(child,kernel_identity=dict(child['kernel_identity'],**{field:value}))
            self.assertFalse(fixture.owned_console_aux(changed,self.operation,self.trust,parent,True,'retained-job'))
        self.assertFalse(fixture.owned_console_aux(child,self.operation,self.trust,parent,False,'retained-job'))

    def test_actual_retired_adapter_refuses_missing_live_identity_or_replaced_handle(self):
        for pid in (17,18):
            for failure in ('metadata','handle','prior-live'):
                with self.subTest(pid=pid,failure=failure),self.assertRaises((RuntimeError,KeyError)):
                    observer,_state=self.observer()
                    if failure=='metadata':del observer.identities[pid]
                    elif failure=='handle':observer.identity_handles[pid]=999
                    else:observer.identities[pid]['kernel_identity']['prior_live_identity']=False
                    observer.associate(self.child,dict(self.parent,exe_sha256='parent-hash'))

    def test_actual_retired_adapter_refuses_generation_pid_job_interval_and_query_errors(self):
        for failure in ('parent-gen','child-gen','parent-pid','child-pid','parent-job','child-job',
                        'kernel-parent','interval','missing-exit','query-error'):
            with self.subTest(failure=failure),self.assertRaises(RuntimeError):
                observer,state=self.observer()
                if failure=='parent-gen':state['born'][17]=99
                elif failure=='child-gen':state['born'][18]=201
                elif failure=='parent-pid':state['pid_override'][17]=99
                elif failure=='child-pid':state['pid_override'][18]=99
                elif failure=='parent-job':state['job'][17]=False
                elif failure=='child-job':state['job'][18]=False
                elif failure=='kernel-parent':state['parent_override'][18]=99
                elif failure=='interval':state['exit'][17]=199
                elif failure=='missing-exit':state['exit'][17]=0
                else:state['query_error']=True
                observer.associate(self.child,dict(self.parent,exe_sha256='parent-hash'))

    def test_actual_retired_adapter_refuses_changed_full_metadata_or_executable_hash(self):
        for pid in (17,18):
            for field in ('exe','cwd','cmd','birth','exe_sha256'):
                with self.subTest(pid=pid,field=field),self.assertRaises(RuntimeError):
                    observer,_state=self.observer()
                    child,parent=self.child,dict(self.parent,exe_sha256='parent-hash')
                    changed=dict(child if pid==18 else parent,**{field:[] if field=='cmd' else 'foreign'})
                    observer.associate(changed if pid==18 else child,changed if pid==17 else parent)

    def test_live_query_failure_never_falls_back_to_retired_protocol(self):
        observer,state=self.observer()
        state['wait'][17],state['exit'][17]=258,0
        # GetProcessTimes succeeds; Class49 independently fails.
        query=observer.native.NtQueryInformationProcess.side_effect
        def failed(handle,info_class,*args):
            return -1 if info_class==49 else query(handle,info_class,*args)
        observer.native.NtQueryInformationProcess.side_effect=failed
        with self.assertRaises(RuntimeError):
            observer.associate(self.child,dict(self.parent,exe_sha256='parent-hash'))
        self.assertTrue(any(call.args[1]==49 for call in observer.native.NtQueryInformationProcess.call_args_list))

    def test_known_retired_observation_reuses_held_identity_without_pid_metadata_lookup(self):
        observer,_state=self.observer()
        with patch.object(fixture,'process_identity',side_effect=AssertionError('No retired PID lookup')):
            result=observer.observe(Mock(pid=18))
        self.assertEqual(result['cmd'],self.child['cmd'])
        self.assertEqual(result['exe_sha256'],'console-hash')
        self.assertEqual(result['kernel_identity']['exit_filetime'],260)
        observer.kernel.QueryFullProcessImageNameW.assert_not_called()
        observer.kernel.OpenProcess.assert_not_called()

    def test_initial_metadata_exit_race_never_creates_prior_live_identity(self):
        observer,state=self.observer()
        state['wait'][18],state['exit'][18]=258,0
        del observer.identities[18]
        observer.identity_handles.pop(18)
        def metadata(_process):
            state['wait'][18]=0
            return dict(self.child,birth=200/10000000-11644473600)
        with patch.object(fixture,'process_identity',side_effect=metadata), \
             patch.object(fixture,'sha256',return_value='console-hash'):
            with self.assertRaises(RuntimeError):
                observer.observe(Mock(pid=18))
        self.assertNotIn(18,observer.identities)
        self.assertNotIn(18,observer.identity_handles)


class FrozenObservationDigestContracts(unittest.TestCase):
    setUp = ConsoleAuxiliaryContracts.setUp
    observer = RetiredConsoleParentContracts.observer

    def live_observer(self):
        observer,state=self.observer()
        state['wait'][18],state['exit'][18]=258,0
        del observer.identities[18]
        observer.identity_handles.pop(18)
        observer.digests=fixture.frozen_observation_digests({self.child['exe']:'a'*64})
        metadata={key:self.child[key] for key in ('pid','exe','cwd','cmd')}
        metadata['birth']=200/10000000-11644473600
        return observer,state,metadata

    def test_frozen_manifest_avoids_hash_stall_between_metadata_and_live_handle_check(self):
        observer,state,metadata=self.live_observer()
        def stalled_hash(_exe):
            state['wait'][18]=0
            return 'a'*64
        with patch.object(fixture,'process_identity',return_value=metadata), \
             patch.object(fixture,'sha256',side_effect=stalled_hash) as digest:
            result=observer.observe(Mock(pid=18))
        digest.assert_not_called()
        self.assertEqual(result['exe_sha256'],'a'*64)
        self.assertIs(result['kernel_identity']['prior_live_identity'],True)

    def test_manifest_canonicalizes_case_and_rejects_invalid_or_conflicting_bindings(self):
        exe=str(Path(self.child['exe']).resolve())
        self.assertEqual(fixture.frozen_observation_digests({exe.upper():'a'*64}),
                         {exe.casefold():'a'*64})
        for manifest in (None,[],{'relative.exe':'a'*64},{exe:'invalid'},
                         {exe:'a'*64,exe.upper():'b'*64}):
            with self.subTest(manifest=manifest),self.assertRaises((TypeError,ValueError)):
                fixture.frozen_observation_digests(manifest)

    def test_cached_hash_never_bypasses_metadata_exit_or_kernel_generation_checks(self):
        for failure in ('exit','generation','job','query'):
            observer,state,metadata=self.live_observer()
            def capture(_process):
                if failure=='exit':state['wait'][18]=0
                return metadata
            if failure=='generation':state['born'][18]=201
            if failure=='job':state['job'][18]=False
            if failure=='query':state['query_error']=True
            with self.subTest(failure=failure), \
                 patch.object(fixture,'process_identity',side_effect=capture), \
                 patch.object(fixture,'sha256',return_value='a'*64),self.assertRaises(RuntimeError):
                observer.observe(Mock(pid=18))
            self.assertNotIn(18,observer.identities)

    def test_unbound_missing_binary_still_fails_observation(self):
        observer,_state,metadata=self.live_observer()
        observer.digests={}
        with patch.object(fixture,'process_identity',return_value=metadata), \
             patch.object(fixture,'sha256',side_effect=FileNotFoundError('missing frozen executable')), \
             self.assertRaises(FileNotFoundError):
            observer.observe(Mock(pid=18))


class MarkerSampleContracts(unittest.TestCase):
    """Execute the actual embedded Python program with process/socket fakes."""
    def sample(self, *, process_error=None, socket_error=None, code=10061, delayed_refusal=False,
               completion=10061, readiness='exceptional'):
        source = Path(__file__).with_name('s06_desktop_direct_native.mjs').read_text(encoding='utf-8')
        program = re.search(r'const sampleProgram = `([\s\S]*?)`', source).group(1)
        class Gone(Exception): pass
        process = Mock()
        process.create_time.return_value = 1.25
        process.is_running.return_value = True
        process.exe.return_value = 'owned.exe'
        process.cwd.return_value = 'owned-repo'
        process.cmdline.return_value = ['owned.exe','fetch']
        process_probe = Mock(return_value=process)
        process_probe.side_effect = Gone() if process_error == 'gone' else process_error
        connection = Mock()
        budget = [None]
        connection.settimeout.side_effect = lambda seconds: budget.__setitem__(0, seconds)
        def connect(address):
            self.assertEqual(address, ('127.0.0.1', 12345))
            if socket_error: raise socket_error
            return 10035 if delayed_refusal else code
        connection.connect_ex.side_effect = connect
        connection.getsockopt.return_value = completion
        def wait(_read, _write, _exception, seconds):
            self.assertLessEqual(seconds,4)
            budget[0] = seconds
            return [], [connection] if readiness == 'writable' else [], [connection] if readiness == 'exceptional' else []
        socket_context = Mock()
        socket_context.__enter__ = Mock(return_value=connection)
        socket_context.__exit__ = Mock(return_value=False)
        socket_probe = Mock(return_value=socket_context)
        output = io.StringIO()
        records = [{'pid':18,'port':12345}]
        with patch.dict(sys.modules, {
                'psutil':SimpleNamespace(Process=process_probe,NoSuchProcess=Gone),
                'socket':SimpleNamespace(socket=socket_probe,SOL_SOCKET=65535,SO_ERROR=4103),
                'select':SimpleNamespace(select=wait)}), \
             patch.object(sys,'argv',['sample',json.dumps(records),'{}',str(Path(fixture.__file__))]), \
             patch.object(sys,'stdout',output):
            exec(compile(program,'<bound S06 sample>','exec'), {})
        return json.loads(output.getvalue())[0], connection

    def test_dead_owner_still_probes_known_port_independently(self):
        item, connection = self.sample(process_error='gone')
        self.assertIs(item['alive'], False)
        self.assertIs(item['listener_open'], False)
        connection.connect_ex.assert_called_once_with(('127.0.0.1',12345))

    def test_dead_owner_slow_connection_refusal_has_bounded_observation_budget(self):
        item, connection = self.sample(process_error='gone', delayed_refusal=True)
        self.assertIs(item['alive'], False)
        self.assertIs(item['listener_open'], False)
        connection.setblocking.assert_called_once_with(False)

    def test_pending_exceptional_refusal_is_observed_as_closed(self):
        item, _ = self.sample(process_error='gone', code=10035, completion=10061)
        self.assertIs(item['listener_open'],False)
        self.assertEqual(item['listener_errno'],10061)

    def test_pending_writable_success_is_observed_as_open(self):
        item, _ = self.sample(process_error='gone', code=10035, completion=0, readiness='writable')
        self.assertIs(item['listener_open'],True)

    def test_pending_without_readiness_stays_unknown(self):
        item, _ = self.sample(process_error='gone', code=10035, completion=0, readiness='none')
        self.assertIsNone(item['listener_open'])
        self.assertEqual(item['listener_errno'],10035)

    def test_exceptional_zero_error_cannot_be_misreported_as_closed_or_open(self):
        item, _ = self.sample(process_error='gone', code=10035, completion=0)
        self.assertIsNone(item['listener_open'])

    def test_listener_timeout_retains_errno_and_unknown_failure(self):
        item, _ = self.sample(process_error='gone', code=10060)
        self.assertIsNone(item['listener_open'])
        self.assertEqual(item.get('listener_errno'),10060)
        self.assertEqual(item.get('listener_status'),'UNKNOWN')

    def test_listener_exception_retains_error_and_unknown_failure(self):
        item, _ = self.sample(process_error='gone', socket_error=OSError(10013,'denied'))
        self.assertIsNone(item['listener_open'])
        self.assertEqual(item.get('listener_error'),'OSError')
        self.assertEqual(item.get('listener_errno'),10013)

    def test_metadata_error_does_not_hide_independent_listener_state(self):
        item, connection = self.sample(process_error=PermissionError('metadata denied'))
        self.assertIsNone(item['alive'])
        self.assertEqual(item['status'],'UNKNOWN')
        self.assertIs(item['listener_open'],False)
        connection.connect_ex.assert_called_once()


class OwnedLoopbackObservationContracts(unittest.TestCase):
    """Explicitly selected real loopback controls; never probe production ports."""
    def observe(self,port):
        source = Path(__file__).with_name('s06_desktop_direct_native.mjs').read_text(encoding='utf-8')
        program = re.search(r'const sampleProgram = `([\s\S]*?)`',source).group(1)
        class Gone(Exception): pass
        output = io.StringIO()
        with patch.dict(sys.modules, {'psutil':SimpleNamespace(Process=Mock(side_effect=Gone()),NoSuchProcess=Gone)}), \
             patch.object(sys,'argv',['sample',json.dumps([{'pid':18,'port':port}]),'{}',str(Path(fixture.__file__))]), \
             patch.object(sys,'stdout',output):
            exec(compile(program,'<owned loopback S06 sample>','exec'), {})
        return json.loads(output.getvalue())[0]

    def test_known_closed_owned_loopback_port_is_closed(self):
        with fixture.socket.socket() as reservation:
            reservation.bind(('127.0.0.1',0))
            port = reservation.getsockname()[1]
        item = self.observe(port)
        self.assertIs(item['alive'],False)
        self.assertIs(item['listener_open'],False)
        self.assertIn(item['listener_errno'],(10061,111))

    def test_known_open_owned_loopback_port_is_open_and_fails_deadline_acceptance(self):
        with fixture.socket.socket() as listener:
            listener.bind(('127.0.0.1',0)); listener.listen(1)
            item = self.observe(listener.getsockname()[1])
        self.assertIs(item['listener_open'],True)
        self.assertEqual(item['listener_errno'],0)


class GhStageContracts(unittest.TestCase):
    def stages(self):
        names = [
            ['hermes:git:review:diff-preserves-large-no-index-exit-one',
             'hermes:git:fileDiff-preserves-large-no-index-exit-one'],
            ['gh-preserves-operator-token-selected-git-and-noninteractive-policy',
             'gh-ordinary-authentication-failure-remains-unavailable'],
            ['direct-gh-owned-descendant-deadline'],
        ]
        stages = []
        for mode, results in zip(('gh-large', 'gh-positive', 'gh-deadline'), names):
            binding = {'source_sha256': 'go-source', 'exe_sha256': mode + '-exe'}
            receipt = {'mode': mode, 'native_os': 'win32', 'backend_started': False,
                       'source_unchanged': True, 'sha256': {'fixture': 'frozen'},
                       'go_fixture': binding, 'temp': mode + '-operation',
                       'results': [{'name': name, 'result': 'PASS'} for name in results]}
            ledger = {'sha256': receipt['sha256'], 'go_fixture': binding,
                      'classification': 'COMPLETED', 'exit_code': 0, 'child_exit_code': 0,
                      'timed_out': False, 'receipt_valid': True, 'identity_errors': [],
                      'before_fixture_cleanup': [], 'remaining_after_fixture_cleanup': [],
                      'job_before_cleanup': [200, 0], 'job_after_cleanup': [200, 0],
                      'debug_observation':complete_debug_record(200),
                      'retained_handle_final_states': [{'wait_result': 0, 'state': 'EXITED'}],
                      'post_fixture_cleanup_listeners': [{'open': False}]}
            stages.append({'receipt': receipt, 'ledger': ledger})
        return stages

    def test_accepts_all_frozen_independent_stages(self):
        self.assertTrue(fixture.gh_stages_passed(self.stages()))

    def test_missing_duplicate_and_partial_coverage_refused(self):
        stages = self.stages()
        self.assertFalse(fixture.gh_stages_passed(stages[:1]))
        self.assertFalse(fixture.gh_stages_passed([stages[0], stages[0]]))
        for stage_index, count in enumerate((2, 2, 1)):
            for index in range(count):
                stages = self.stages()
                del stages[stage_index]['receipt']['results'][index]
                self.assertFalse(fixture.gh_stages_passed(stages))

    def test_no_unknown_error_timeout_active_or_cumulative_overflow_acceptance(self):
        for key, value in [('identity_errors', [{'status': 'UNKNOWN'}]),
                           ('timed_out', True), ('receipt_valid', False), ('child_exit_code', 1),
                           ('job_after_cleanup', [256, 0]), ('job_before_cleanup', [200, 1]),
                           ('post_fixture_cleanup_listeners', [{'open': None}])]:
            with self.subTest(key=key):
                stages = self.stages()
                stages[1]['ledger'][key] = value
                self.assertFalse(fixture.gh_stages_passed(stages))

    def test_changed_source_or_reused_operation_refused(self):
        stages = self.stages()
        stages[1]['receipt']['sha256'] = stages[1]['ledger']['sha256'] = {'fixture': 'changed'}
        self.assertFalse(fixture.gh_stages_passed(stages))
        stages = self.stages()
        stages[1]['receipt']['temp'] = stages[0]['receipt']['temp']
        self.assertFalse(fixture.gh_stages_passed(stages))

    def test_only_retained_quiescence_permits_next_stage_without_accepting_identity_failure(self):
        stages = self.stages()
        stages[0]['ledger']['identity_errors'] = [{'phase': 'observe', 'status': 'UNKNOWN'}]
        self.assertTrue(fixture.stage_quiescent(stages[0]))
        self.assertFalse(fixture.gh_stages_passed(stages))
        for key, value in [('job_after_cleanup', [200, 1]),
                           ('retained_handle_final_states', [{'wait_result': 258, 'state': 'UNKNOWN'}]),
                           ('identity_errors', [{'phase': 'job_close'}])]:
            with self.subTest(key=key):
                stage = self.stages()[0]
                stage['ledger'][key] = value
                self.assertFalse(fixture.stage_quiescent(stage))


class FinalPathAuditContracts(unittest.TestCase):
    """Resolver doubles only; old live matching is the semantic RED control."""
    def audit(self, deadline=None):
        if hasattr(fixture,'FinalPathAudit'):
            return fixture.FinalPathAudit(deadline)
        return SimpleNamespace(resolve=lambda value:Path(value).resolve(),verify=lambda:None)

    def match(self, item, operation, allowed, root, records, audit, deadline=None):
        import inspect
        kwargs={'deadline':deadline}
        if 'resolver' in inspect.signature(fixture.owned_command).parameters:
            kwargs['resolver']=audit.resolve
        return fixture.owned_command(item,operation,allowed,root,records,**kwargs)

    def test_many_exact_records_resolve_each_unique_path_only_twice_within_original_budget(self):
        root=Path(__file__).resolve().parents[3]
        operation=root/'tmp/s06-direct-owned-cache-budget'
        exe=operation/'git.exe'
        allowed={str(exe.resolve()).casefold():'bound'}
        items=[{'exe':str(exe),'cwd':str(operation),'cmd':[str(exe),'worker',str(i)]} for i in range(80)]
        records=[dict(item,operation=str(operation),id=str(i),sha256='bound') for i,item in enumerate(items)]
        now=[0.0]
        calls=[]
        real_resolve=Path.resolve
        def expensive_resolve(path,*args,**kwargs):
            calls.append(str(path))
            now[0]+=0.001
            return real_resolve(path,*args,**kwargs)
        complete=True
        with patch.object(Path,'resolve',new=expensive_resolve), \
             patch.object(fixture.time,'monotonic',side_effect=lambda:now[0]):
            audit=self.audit(2.0)
            try:
                for item in items:
                    complete=complete and self.match(item,operation,allowed,root,records,audit,2.0)
                audit.verify()
            except TimeoutError:
                complete=False
        self.assertTrue(complete)
        self.assertLessEqual(len(calls),2*len(set(calls)))

    def test_junction_drift_after_matching_is_not_a_cached_ownership_grant(self):
        root=Path(__file__).resolve().parents[3]
        operation=root/'tmp/s06-direct-owned-cache-drift'
        exe=operation/'git.exe'
        item={'exe':str(exe),'cwd':str(operation),'cmd':[str(exe),'--version']}
        records=[dict(item,operation=str(operation),id='version',sha256='bound')]
        allowed={str(exe.resolve()).casefold():'bound'}
        changed=[False]
        actual_resolve=Path.resolve
        def resolves(path,*args,**kwargs):
            return root/'foreign' if changed[0] and str(path)==str(operation) else actual_resolve(path,*args,**kwargs)
        with patch.object(Path,'resolve',new=resolves):
            audit=self.audit()
            self.assertTrue(self.match(item,operation,allowed,root,records,audit))
            changed[0]=True
            with self.assertRaises(RuntimeError):
                audit.verify()

    def test_last_revalidation_resolve_crossing_deadline_is_refused(self):
        root=Path(__file__).resolve().parents[3]
        now=[0.0]
        actual_resolve=Path.resolve
        def resolves(path,*args,**kwargs):
            result=actual_resolve(path,*args,**kwargs)
            now[0]+=0.6
            return result
        with patch.object(Path,'resolve',new=resolves), \
             patch.object(fixture.time,'monotonic',side_effect=lambda:now[0]):
            audit=self.audit(1.0)
            audit.resolve(root)
            with self.assertRaises(TimeoutError):
                audit.verify()

    def test_cached_exact_binding_preserves_git_transition_and_all_foreign_negatives(self):
        root=Path(__file__).resolve().parents[3]
        operation=root/'tmp/s06-direct-owned-cache-controls'
        exe=operation/'git.exe'
        repo=operation/'owned spaced repo'
        item={'exe':str(exe),'cwd':str(repo),'cmd':[str(exe),'-C',str(repo),'status']}
        launch=dict(item,cwd=str(root),operation=str(operation),id='version',sha256='bound')
        allowed={str(exe.resolve()).casefold():'bound'}
        cases=[(item,launch,True)]
        for field,value in [('operation',str(root)),('id',''),('sha256','wrong'),
                            ('exe',str(operation/'foreign.exe')),('cwd',str(operation/'unregistered-origin')),
                            ('cmd',item['cmd']+['extra'])]:
            cases.append((item,dict(launch,**{field:value}),False))
        for argv in ([str(exe),'--no-pager','-C',str(repo),'status'],
                     [str(exe),'-C',str(repo),'-C',str(repo),'status'],
                     [str(exe),'-C',str(root),'status']):
            cases.append((dict(item,cmd=argv),dict(launch,cmd=argv),False))
        cases.extend([(dict(item,cwd=str(root/'foreign')),launch,False),
                      (dict(item,cwd=str(root/'foreign')),
                       dict(launch,cwd=str(root/'foreign')),False),
                      (dict(item,exe=str(operation/'alias.exe')),launch,False)])
        for observed,record,expected in cases:
            with self.subTest(observed=observed,record=record):
                audit=self.audit()
                actual=self.match(observed,operation,allowed,root,[record],audit)
                audit.verify()
                self.assertEqual(actual,expected)
                self.assertEqual(actual,fixture.owned_command(observed,operation,allowed,root,[record]))

    def test_cached_real_executable_alias_does_not_enable_wrong_basename_git_transition(self):
        root=Path(__file__).resolve().parents[3]
        operation=root/'tmp/s06-direct-owned-cache-alias'
        exe=operation/'git.exe'
        alias=operation/'not-git.exe'
        repo=operation/'owned spaced repo'
        item={'exe':str(exe),'cwd':str(repo),'cmd':['git','-C',str(repo),'status']}
        launch=dict(item,exe=str(alias),cwd=str(root),operation=str(operation),id='alias',sha256='bound')
        allowed={str(exe.resolve()).casefold():'bound'}
        actual_resolve=Path.resolve
        def resolves(path,*args,**kwargs):
            return exe if str(path)==str(alias) else actual_resolve(path,*args,**kwargs)
        with patch.object(Path,'resolve',new=resolves):
            audit=self.audit()
            self.assertFalse(self.match(item,operation,allowed,root,[launch],audit))
            audit.verify()

    def test_cached_scope_root_and_canonical_exe_drift_are_both_rejected_at_final_recheck(self):
        root=Path(__file__).resolve().parents[3]
        for suffix in ('scope','git.exe'):
            target=root/'tmp/s06-direct-owned-cache-drift-all'/suffix
            changed=[False]
            actual_resolve=Path.resolve
            def resolves(path,*args,**kwargs):
                return root/'foreign'/suffix if changed[0] and str(path)==str(target) else actual_resolve(path,*args,**kwargs)
            with self.subTest(suffix=suffix),patch.object(Path,'resolve',new=resolves):
                audit=self.audit()
                audit.resolve(target)
                changed[0]=True
                with self.assertRaises(RuntimeError):
                    audit.verify()


class DebugIntegrationContracts(unittest.TestCase):
    """Kernel/event doubles only; RED also exercises the prior polling supervisor."""
    def supervised(self, *, foreign=False, reused=False, rip=False, close_error=False,
                   assign_error=False, omit_child=False, continue_error=False, terminate_error=False,
                   root_exits_first=False, slow_registry=False, registry_variant=None,
                   expired_registry=False, expired_last_observe=False, mutate_after_snapshot=False):
        import inspect
        root = Path(__file__).resolve().parents[3]
        operation = root/'tmp/s06-direct-owned-debug-pure'
        exe = operation/'node.exe'
        command = [str(exe), 'fixture']
        trace = []
        protocol_time=[0.0]
        budget_expired=[False]
        real_clock=fixture.time.monotonic
        identities = {pid: {'pid':pid, 'birth':float(pid), 'exe':str(exe),
            'cwd':str(operation), 'cmd':command if pid == 17 else [str(exe),'worker'],
            'exe_sha256':'bound', 'kernel_identity':{'pid':pid,'creation_filetime':pid*100,
                'wait_result':258,'exit_filetime':0,'job_scope':'job','prior_live_identity':True}}
            for pid in (17,18)}
        parent = SimpleNamespace(pid=17, children=lambda recursive:[], is_running=lambda:False)
        observer = SimpleNamespace(scope='job', handles={17:117}, generations={17:1700},
            identities={17:identities[17]}, identity_handles={17:117},
            observe=Mock(side_effect=lambda p:(trace.append(('capture_stamp',p.pid,protocol_time[0])),
                                              identities[p.pid])[1]),
            proof=Mock(side_effect=lambda pid: identities[pid]['kernel_identity']),
            close=Mock(return_value=([{'pid':p,'state':'EXITED','wait_result':0} for p in (17,18)],[])))
        api = SimpleNamespace()
        queue = [dict(code=3,pid=17,tid=1,process=217,file=317)]
        if not omit_child:
            queue.append(dict(code=3,pid=18,tid=2,process=218,file=318))
        if rip:
            queue.append(dict(code=9,pid=17,tid=1))
        exits=[dict(code=5,pid=18,tid=2),dict(code=5,pid=17,tid=1)]
        queue.extend(list(reversed(exits)) if root_exits_first else exits)
        original_observe=observer.observe.side_effect
        def observe_with_final_cost(process):
            item=original_observe(process)
            if expired_last_observe and not queue:
                item=dict(item,kernel_identity=dict(item['kernel_identity'],wait_result=0))
                if process.pid == 18:
                    budget_expired[0]=True
            return item
        observer.observe.side_effect=observe_with_final_cost
        wait_yield=[False]
        def waited_event(timeout):
            if (root_exits_first or slow_registry) and wait_yield[0]:
                wait_yield[0]=False
                return None
            wait_yield[0]=True
            return SimpleNamespace(**queue.pop(0)) if queue else None
        api.wait = waited_event
        api.duplicate = lambda handle: handle+1000
        def generation(handle, job, pid):
            if foreign:
                raise RuntimeError('not in retained Job')
            return {'pid':pid,'creation_filetime':pid*100+(1 if reused else 0),'wait_result':258}
        api.generation = generation
        def close(handle):
            trace.append(('close',handle))
            if close_error:
                raise OSError('debug image close failed')
        api.close = close
        continuations = [0]
        root_exited = [False]
        def continued(event,status):
            trace.append(('continue',event.code,event.pid,status))
            continuations[0] += 1
            if continue_error and continuations[0] == 1:
                raise OSError('ContinueDebugEvent refused')
            if event.code == 5 and event.pid == 17:
                root_exited[0]=True
        api.continue_event = continued
        process = Mock(pid=17,returncode=0)
        # Polling never sees the short-lived child; debug events do.
        process.poll.side_effect = lambda: 0 if not queue or assign_error else None
        if root_exits_first:
            process.poll.side_effect = lambda: 0 if root_exited[0] else None
        legacy_polls = iter((None,0,0))
        supports_debug = 'debug_api' in inspect.signature(fixture.supervise).parameters
        if not supports_debug:
            process.poll.side_effect = lambda: next(legacy_polls,0)
        def waited(timeout):
            trace.append(('wait',len(queue)))
            return 0
        process.wait.side_effect = waited
        process._handle = SimpleNamespace(Close=lambda:trace.append(('popen_close',)))
        def terminated(p,j):
            trace.append(('terminate',j))
            if terminate_error:
                raise OSError('retained termination refused')
        owner = SimpleNamespace(_create_windows_job=lambda:'job',
            _assign_windows_job=Mock(side_effect=RuntimeError('assignment') if assign_error else None),
            _resume_suspended_process=Mock(), _terminate_process_tree=terminated,
            _close_windows_job=lambda j:trace.append(('job_close',j)),
            _windows_job_process_counts=lambda j:(2,1 if root_exits_first and queue else 0),
            MAX_BOUNDED_PROCESS_TREE_NODES=256)
        fake_psutil = SimpleNamespace(Process=lambda pid:parent if pid == 17 else SimpleNamespace(pid=pid),
                                      NoSuchProcess=ProcessLookupError)
        launch = dict(identities[18],operation=str(operation),id='worker',sha256='bound')
        audit_type=getattr(fixture,'FinalPathAudit',None)
        def audit_with_external_mutation(deadline):
            launch['cmd']=[str(exe),'foreign-after-read']
            return audit_type(deadline)
        def registry_read(operation):
            trace.append(('registry_stamp',protocol_time[0],len(queue)))
            if slow_registry:
                # Source-bound measured old cycle: 13.8ms read + 158.1ms classification.
                # This is a protocol double, not a native performance claim.
                protocol_time[0]+=0.1719
            if expired_registry:
                budget_expired[0]=True
            if registry_variant == 'corrupt':
                raise ValueError('corrupt registry JSON')
            if registry_variant == 'deleted':
                return []
            if registry_variant == 'mutated':
                return [dict(launch,cmd=[str(exe),'different-worker'])]
            return [launch]
        kwargs = {'owner':owner,'observer':observer}
        if supports_debug:
            kwargs.update(debug_births=True,debug_api=api)
        with patch.object(fixture,'psutil',fake_psutil), \
             patch.object(fixture.subprocess,'Popen',return_value=process), \
             patch.object(fixture,'process_identity',side_effect=lambda p:{k:identities[p.pid][k]
                for k in ('pid','birth','exe','cwd','cmd')}), \
             patch.object(fixture,'read_launches',side_effect=registry_read), \
             patch.object(fixture.time,'monotonic',side_effect=lambda:
                 real_clock()+100 if budget_expired[0] else real_clock()), \
             patch.dict(fixture.__dict__,{'FinalPathAudit':audit_with_external_mutation}
                        if mutate_after_snapshot else {}), \
             patch.object(fixture.time,'sleep'):
            result = fixture.supervise(command,root,operation,{str(exe.resolve()).casefold():'bound'},
                                       {},Mock(),**kwargs)
        return result,trace,owner

    def test_create_event_captures_short_lived_child_before_continue(self):
        result,trace,_ = self.supervised()
        self.assertEqual([p['pid'] for p in result['identities']],[17,18])
        self.assertTrue(result.get('debug_observation',{}).get('coverage_complete'))
        self.assertEqual(result['identity_errors'],[])

    def test_root_exit_does_not_skip_remaining_owned_exit_event(self):
        result,trace,_ = self.supervised(root_exits_first=True)
        self.assertEqual(result['identity_errors'],[])
        self.assertTrue(result['debug_observation']['coverage_complete'])
        self.assertLess(trace.index(('continue',5,17,0x00010002)),
                        trace.index(('continue',5,18,0x00010002)))
        self.assertLess(trace.index(('continue',5,18,0x00010002)),trace.index(('wait',0)))

    def test_slow_registry_does_not_delay_next_create_or_repeat_during_debug_pump(self):
        result,trace,_=self.supervised(slow_registry=True)
        self.assertEqual(result['identity_errors'],[])
        self.assertTrue(result['debug_observation']['coverage_complete'])
        child_stamp=next(row for row in trace if row[:2]==('capture_stamp',18))
        self.assertEqual(child_stamp[2],0.0)
        registry_rows=[row for row in trace if row[0]=='registry_stamp']
        self.assertEqual(len(registry_rows),1)
        self.assertEqual(registry_rows[0][2],0)
        self.assertLess(trace.index(('continue',5,17,0x00010002)),trace.index(registry_rows[0]))
        timings=result['debug_observation']['after_cleanup']['timings']
        self.assertEqual(timings['registry_reads'],1)
        self.assertEqual(timings['classification_passes'],1)

    def test_debug_supervisor_constructs_one_final_audit_and_revalidates_before_cleanup(self):
        audit_type=fixture.FinalPathAudit
        actual_verify=audit_type.verify
        with patch.object(audit_type,'verify',autospec=True,side_effect=actual_verify) as verify, \
             patch.object(fixture,'FinalPathAudit',wraps=audit_type) as constructor:
            result,trace,_=self.supervised()
        self.assertEqual(result['identity_errors'],[])
        self.assertEqual(constructor.call_count,1)
        self.assertEqual(verify.call_count,1)

    def test_final_supervisor_realpath_drift_is_unknown_and_independent_cleanup_continues(self):
        with patch.object(fixture.FinalPathAudit,'verify',side_effect=RuntimeError('junction drift')):
            result,trace,_=self.supervised()
        self.assertEqual(result['descendant_state'],'UNKNOWN')
        self.assertTrue(any(error['phase']=='job_audit' for error in result['identity_errors']))
        self.assertIn(('terminate','job'),trace)
        self.assertIn(('job_close','job'),trace)
        self.assertIn(('popen_close',),trace)
        self.assertNotEqual(fixture.acceptance_exit(0,False,[],[],[],True,
            result['identity_errors'],result['debug_observation']),0)

    def test_final_registry_is_an_immutable_fresh_value_snapshot(self):
        result,_,_=self.supervised(mutate_after_snapshot=True)
        self.assertEqual(result['identity_errors'],[])
        self.assertEqual([item['pid'] for item in result['identities']],[17,18])
        self.assertEqual(result['identities'][1]['registered_launch']['cmd'],
                         result['identities'][1]['cmd'])

    def test_each_registry_record_scan_respects_deadline_without_granting_late_match(self):
        root=Path(__file__).resolve().parents[3]
        operation=root/'tmp/s06-direct-owned-budget-pure'
        exe=operation/'git.exe'
        item={'exe':str(exe),'cwd':str(operation),'cmd':[str(exe),'--version']}
        launch=dict(item,operation=str(operation),id='version',sha256='bound')
        records=[dict(launch,cmd=[str(exe),'wrong']),launch]
        with patch.object(fixture.time,'monotonic',side_effect=[0.0,2.0]):
            with self.assertRaises(TimeoutError):
                fixture.owned_command(item,operation,{str(exe.resolve()).casefold():'bound'},
                                      root,records,deadline=1.0)

    def test_final_corrupt_or_mutated_registry_never_grants_ownership_after_full_capture(self):
        for variant in ('corrupt','mutated','deleted'):
            with self.subTest(variant=variant):
                result,trace,_=self.supervised(slow_registry=True,registry_variant=variant)
                self.assertEqual(result['descendant_state'],'UNKNOWN')
                self.assertTrue(result['identity_errors'])
                self.assertIn(('job_close','job'),trace)
                self.assertIn(('popen_close',),trace)
                self.assertNotEqual(fixture.acceptance_exit(0,False,[],[],[],True,
                    result['identity_errors'],result['debug_observation']),0)

    def test_final_registry_cost_is_charged_to_original_deadline_and_cleanup_still_runs(self):
        result,trace,_=self.supervised(expired_registry=True)
        self.assertEqual(result['descendant_state'],'UNKNOWN')
        self.assertTrue(result['timed_out'])
        self.assertEqual([item['pid'] for item in result['identities']],[17])
        self.assertIn(('terminate','job'),trace)
        self.assertIn(('job_close','job'),trace)
        self.assertIn(('popen_close',),trace)

    def test_last_matching_path_comparison_crossing_deadline_never_returns_true(self):
        root=Path(__file__).resolve().parents[3]
        operation=root/'tmp/s06-direct-owned-last-match'
        exe=operation/'git.exe'
        item={'exe':str(exe),'cwd':str(operation),'cmd':[str(exe),'--version']}
        launch=dict(item,operation=str(operation),id='version',sha256='bound')
        now=[89.0]
        actual_cwd=fixture.registered_cwd
        def expensive_cwd(*args):
            result=actual_cwd(*args)
            now[0]=91.0
            return result
        with patch.object(fixture.time,'monotonic',side_effect=lambda:now[0]), \
             patch.object(fixture,'registered_cwd',side_effect=expensive_cwd):
            with self.assertRaises(TimeoutError):
                fixture.owned_command(item,operation,{str(exe.resolve()).casefold():'bound'},
                                      root,[launch],deadline=90.0)

    def test_last_retained_observe_crossing_deadline_refuses_and_closes_independently(self):
        result,trace,_=self.supervised(expired_last_observe=True)
        self.assertEqual(result['descendant_state'],'UNKNOWN')
        self.assertTrue(result['timed_out'])
        self.assertTrue(any(error.get('phase')=='cleanup' and error.get('pid')==18
                            and error.get('error')=='TimeoutError' for error in result['identity_errors']))
        self.assertIn(('terminate','job'),trace)
        self.assertIn(('job_close','job'),trace)
        self.assertIn(('popen_close',),trace)
        self.assertTrue(all(row['state']=='EXITED' for row in result['retained_handle_final_states']))
        self.assertNotEqual(fixture.acceptance_exit(0,False,[],[],[],True,
            result['identity_errors'],result['debug_observation']),0)

    def test_foreign_job_does_not_become_identity_authority(self):
        result,_,_ = self.supervised(foreign=True)
        self.assertEqual(result['descendant_state'],'UNKNOWN')
        self.assertTrue(result['identity_errors'])

    def test_reused_root_generation_does_not_become_identity_authority(self):
        result,_,_ = self.supervised(reused=True)
        self.assertEqual(result['descendant_state'],'UNKNOWN')

    def test_rip_event_is_not_a_successful_observation(self):
        result,_,_ = self.supervised(rip=True)
        self.assertEqual(result['descendant_state'],'UNKNOWN')

    def test_image_close_failure_remains_unknown(self):
        result,trace,_ = self.supervised(close_error=True)
        self.assertEqual(result['descendant_state'],'UNKNOWN')
        self.assertIn(('job_close','job'),trace)
        self.assertIn(('popen_close',),trace)

    def test_missing_create_event_is_not_cured_by_job_active_zero(self):
        result,_,_ = self.supervised(omit_child=True)
        self.assertEqual(result['descendant_state'],'UNKNOWN')
        self.assertFalse(result.get('debug_observation',{}).get('coverage_complete',False))

    def test_unassigned_root_exit_event_is_drained_before_wait_and_handles_close(self):
        result,trace,owner = self.supervised(assign_error=True)
        self.assertEqual(result['descendant_state'],'UNKNOWN')
        owner._resume_suspended_process.assert_not_called()
        self.assertIn(('wait',0),trace)
        self.assertIn(('popen_close',),trace)
        exited = trace.index(('continue',5,17,0x00010002))
        self.assertLess(exited,trace.index(('wait',0)))

    def test_continue_failure_is_sticky_but_pending_event_and_cleanup_are_released(self):
        result,trace,_ = self.supervised(continue_error=True)
        self.assertEqual(result['descendant_state'],'UNKNOWN')
        self.assertTrue(any(e['phase']=='debug_continue' for e in result['identity_errors']))
        self.assertIn(('job_close','job'),trace)
        self.assertIn(('popen_close',),trace)
        self.assertEqual(trace.count(('continue',3,17,0x00010002)),2)
        self.assertLess(trace.index(('continue',5,17,0x00010002)),trace.index(('wait',0)))

    def test_termination_exception_does_not_skip_independent_handle_release(self):
        result,trace,_ = self.supervised(terminate_error=True)
        self.assertEqual(result['descendant_state'],'UNKNOWN')
        self.assertIn(('job_close','job'),trace)
        self.assertIn(('popen_close',),trace)


class DebugPumpContracts(unittest.TestCase):
    def pump(self):
        errors,trace = [],[]
        item = {'pid':18,'birth':2.0,'exe':'worker.exe','cwd':'owned','cmd':['worker.exe'],
                'exe_sha256':'bound','kernel_identity':{'pid':18,'creation_filetime':200,
                    'wait_result':258,'exit_filetime':0,'prior_live_identity':True,'job_scope':'job'}}
        def observe(process):
            trace.append(('full_identity',process.pid))
            return item
        observer = SimpleNamespace(handles={},identities={},scope='job',observe=Mock(side_effect=observe))
        api = SimpleNamespace(duplicate=lambda handle:handle+100,
            generation=lambda handle,job,pid:{'pid':pid,'creation_filetime':200,'wait_result':258},
            close=lambda handle:trace.append(('close',handle)),
            continue_event=lambda event,status:trace.append(('continue',event.code,event.pid,status)),
            wait=Mock(return_value=None))
        return fixture.DebugBirthPump(api,observer,'job',errors),errors,trace,api,observer

    def create(self):
        return SimpleNamespace(code=3,pid=18,tid=19,file=12,process=20)

    def test_full_identity_is_before_continue_and_event_alone_is_not_registry_authority(self):
        pump,errors,trace,_,_ = self.pump()
        with patch.object(fixture,'psutil',SimpleNamespace(Process=lambda pid:SimpleNamespace(pid=pid))):
            pump.handle(self.create())
        self.assertEqual(errors,[])
        self.assertLess(trace.index(('full_identity',18)),trace.index(('continue',3,18,0x00010002)))
        self.assertTrue(pump.births[18]['captured_before_continue'])
        root=Path(__file__).resolve().parents[3]
        self.assertFalse(fixture.owned_command(pump.births[18],root/'tmp/pure',{},root,[]))

    def test_duplicate_create_is_unknown_and_does_not_replace_retained_handle(self):
        pump,errors,_,_,observer = self.pump()
        with patch.object(fixture,'psutil',SimpleNamespace(Process=lambda pid:SimpleNamespace(pid=pid))):
            pump.handle(self.create())
            retained = observer.handles[18]
            pump.handle(self.create())
        self.assertEqual(len(pump.births),1)
        self.assertEqual(observer.handles[18],retained)
        self.assertTrue(errors)
        self.assertIn('Duplicate or reused',errors[0]['detail'])

    def test_only_first_captured_first_chance_breakpoint_is_handled(self):
        pump,errors,trace,_,_ = self.pump()
        pump.births[18]={'captured_before_continue':True}
        for chance,code in [(1,0x80000003),(1,0x80000003),(0,0x80000003),(1,0xC0000005)]:
            pump.handle(SimpleNamespace(code=1,pid=18,tid=19,first_chance=chance,exception_code=code))
        self.assertEqual([row[-1] for row in trace],
                         [0x00010002,0x80010001,0x80010001,0x80010001])
        self.assertEqual(errors,[])

    def test_uncaptured_breakpoint_is_unhandled(self):
        pump,_,trace,_,_ = self.pump()
        pump.handle(SimpleNamespace(code=1,pid=99,tid=19,first_chance=1,exception_code=0x80000003))
        self.assertEqual(trace[-1][-1],0x80010001)

    def test_bounded_diagnostics_record_capture_exception_and_actual_continue_cost(self):
        pump,errors,trace,api,observer=self.pump()
        now=[10.0]
        pump.clock=lambda:now[0]
        original_observe=observer.observe.side_effect
        def observed(process):
            now[0]+=0.003
            return original_observe(process)
        observer.observe.side_effect=observed
        def continued(event,status):
            now[0]+=0.002
            trace.append(('continue',event.code,event.pid,status))
        api.continue_event=continued
        with patch.object(fixture,'psutil',SimpleNamespace(Process=lambda pid:SimpleNamespace(pid=pid))):
            pump.handle(self.create())
        pump.handle(SimpleNamespace(code=1,pid=18,tid=19,first_chance=1,exception_code=0xC0000005))
        self.assertEqual(errors,[])
        self.assertEqual(pump.events[0]['mono'],10.0)
        self.assertAlmostEqual(pump.events[0]['capture_seconds'],0.003)
        self.assertEqual(pump.events[1]['exception_code'],0xC0000005)
        self.assertEqual(pump.events[1]['first_chance'],1)
        self.assertEqual(pump.events[1]['continued_status'],0x80010001)
        self.assertAlmostEqual(pump.coverage((1,0))['timings']['continue_seconds'],0.004)
        api.continue_event=Mock(side_effect=OSError('continue refused'))
        with self.assertRaises(OSError):
            pump.handle(SimpleNamespace(code=1,pid=18,tid=19,first_chance=0,exception_code=0x80000003))
        self.assertIsNone(pump.events[-1]['continued_status'])
        self.assertTrue(errors)

    def test_continuous_events_yield_in_bursts_and_charge_original_deadline(self):
        pump,_,trace,api,_ = self.pump()
        now=[0.0]
        pump.clock=lambda:now[0]
        def wait(timeout):
            now[0]+=0.00001
            return SimpleNamespace(code=7,pid=18,tid=19)
        api.wait=Mock(side_effect=wait)
        self.assertEqual(pump.pump(1.0),64)
        self.assertEqual(api.wait.call_count,64)
        pump.max_events=1000
        with self.assertRaises(TimeoutError):
            pump.pump(now[0]+0.00015)
        self.assertLess(api.wait.call_count,90)

    def test_expired_budget_never_waits_for_an_event(self):
        pump,_,_,api,_ = self.pump()
        pump.clock=lambda:5.0
        with self.assertRaises(TimeoutError):
            pump.pump(5.0)
        api.wait.assert_not_called()

    def test_event_budget_overflow_stays_unknown_and_releases_event(self):
        pump,errors,trace,_,_ = self.pump()
        pump.max_events=0
        with self.assertRaises(RuntimeError):
            pump.handle(SimpleNamespace(code=7,pid=18,tid=19))
        self.assertTrue(errors)
        self.assertEqual(trace[-1],('continue',7,18,0x00010002))
        self.assertEqual(pump.events,[])
        pump.handle(SimpleNamespace(code=5,pid=18,tid=19),capture=False)
        self.assertEqual(pump.events,[])
        self.assertIn(18,pump.exited)

    def test_overflow_exception_and_capture_error_do_not_handle_nonloader_exception(self):
        pump,errors,trace,_,_ = self.pump()
        pump.max_events=0
        with self.assertRaises(RuntimeError):
            pump.handle(SimpleNamespace(code=1,pid=18,tid=19,first_chance=1,
                                        exception_code=0xC0000005))
        self.assertTrue(errors)
        self.assertEqual(trace[-1],('continue',1,18,0x80010001))
        pump.handle(SimpleNamespace(code=1,pid=18,tid=19,first_chance=0,
                                    exception_code=0x80000003),capture=False)
        self.assertEqual(trace[-1],('continue',1,18,0x80010001))
        pump,errors,trace,_,_ = self.pump()
        pump.handle(SimpleNamespace(code=1,pid=18,tid=19))
        self.assertEqual(trace[-1],('continue',1,18,0x80010001))

    def test_wrong_thread_cannot_wait_or_continue(self):
        pump,_,_,api,_ = self.pump()
        with patch.object(fixture.threading,'get_ident',return_value=-1),self.assertRaises(RuntimeError):
            pump.pump(pump.clock()+1)
        api.wait.assert_not_called()

    def test_missing_exit_and_256_sentinel_cannot_complete_coverage(self):
        pump,_,_,_,_ = self.pump()
        pump.births={18:{'captured_before_continue':True}}
        self.assertFalse(pump.coverage((1,0))['coverage_complete'])
        pump.exited={18}
        self.assertTrue(pump.coverage((1,0))['coverage_complete'])
        for counts in [(256,0),(256,1),(1,1),(2,0),None]:
            self.assertFalse(pump.coverage(counts)['coverage_complete'])

    def test_new_cleanup_birth_is_not_a_late_ownership_grant(self):
        pump,errors,trace,_,observer = self.pump()
        pump.handle(self.create(),capture=False)
        self.assertTrue(errors)
        self.assertEqual(observer.handles,{})
        self.assertEqual(pump.births,{})
        self.assertEqual(trace[-1],('continue',3,18,0x00010002))


class NativeDebugAdapterContracts(unittest.TestCase):
    """The actual ctypes adapter with every Win32 function replaced by a double."""
    def adapter(self):
        import ctypes
        names = ('WaitForDebugEventEx','ContinueDebugEvent','GetCurrentProcess','GetProcessId',
                 'DuplicateHandle','CloseHandle','GetProcessTimes','IsProcessInJob','WaitForSingleObject')
        kernel = SimpleNamespace(**{name:Mock(return_value=1) for name in names})
        with patch.object(ctypes,'WinDLL',return_value=kernel,create=True):
            api = fixture.WindowsDebugEvents()
        def duplicate(src,handle,target,out,rights,inherit,options):
            out._obj.value=901
            return 1
        kernel.DuplicateHandle.side_effect=duplicate
        kernel.GetProcessId.return_value=17
        kernel.WaitForSingleObject.return_value=258
        def times(handle,born,exited,kernel_time,user_time):
            born._obj.dwLowDateTime=1700
            return 1
        kernel.GetProcessTimes.side_effect=times
        kernel.IsProcessInJob.side_effect=lambda handle,job,member:setattr(member._obj,'value',True) or 1
        return api,kernel

    def test_actual_adapter_uses_176_byte_abi_and_readonly_noninheritable_duplicate(self):
        api,kernel=self.adapter()
        self.assertEqual(api.c.sizeof(api.Event),176)
        self.assertEqual(api.Event.data.offset,16)
        self.assertEqual(api.duplicate(217),901)
        args=kernel.DuplicateHandle.call_args.args
        self.assertEqual(args[4:],(0x00101000,False,0))
        self.assertEqual(api.generation(901,501,17),
                         {'pid':17,'creation_filetime':1700,'wait_result':258})
        self.assertEqual(kernel.IsProcessInJob.call_args.args[1],501)

    def test_actual_adapter_refuses_foreign_job_wrong_pid_and_nonlive_handle(self):
        for defect in ('job','pid','wait','times'):
            api,kernel=self.adapter()
            if defect=='job':
                kernel.IsProcessInJob.side_effect=lambda handle,job,member:1
            elif defect=='pid':
                kernel.GetProcessId.return_value=99
            elif defect=='wait':
                kernel.WaitForSingleObject.return_value=0
            else:
                kernel.GetProcessTimes.side_effect=None
                kernel.GetProcessTimes.return_value=0
            with self.subTest(defect=defect),self.assertRaises((RuntimeError,OSError)):
                api.generation(901,501,17)

    def test_actual_adapter_decodes_create_and_exception_without_running_native(self):
        api,kernel=self.adapter()
        def create(ptr,timeout):
            event=ptr._obj
            event.code,event.pid,event.tid=3,17,19
            event.data.create.process,event.data.create.file=217,317
            return 1
        kernel.WaitForDebugEventEx.side_effect=create
        event=api.wait(0)
        self.assertEqual((event.code,event.pid,event.process,event.file),(3,17,217,317))
        def exception(ptr,timeout):
            event=ptr._obj
            event.code,event.pid,event.tid=1,17,19
            event.data.exception.record.code=0x80000003
            event.data.exception.first_chance=1
            return 1
        kernel.WaitForDebugEventEx.side_effect=exception
        event=api.wait(0)
        self.assertEqual((event.exception_code,event.first_chance),(0x80000003,1))
        api.continue_event(event,0x80010001)
        kernel.ContinueDebugEvent.assert_called_once_with(17,19,0x80010001)


if __name__ == '__main__':
    unittest.main(verbosity=2)
