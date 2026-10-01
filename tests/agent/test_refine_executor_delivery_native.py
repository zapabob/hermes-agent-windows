"""Public refine acceptance using actual timeout/segmented executors and existing owners."""
import threading
import json
import yaml
import pytest
from tests.agent.test_refine_delivery_native import delivery, patch_args


@pytest.mark.parametrize('delivery', [65536], indirect=True)
def test_segmented_read_results_are_confirmed_only_after_whole_turn(delivery, monkeypatch):
    from agent import tool_executor
    real = tool_executor.execute_tool_calls_segmented
    segments = []
    def observe(*args, **kwargs):
        segments.append([kind for kind, _calls in kwargs['segments']])
        return real(*args, **kwargs)
    monkeypatch.setattr(tool_executor, 'execute_tool_calls_segmented', observe)
    first = delivery.skills / 'review-owned/SKILL.md'
    other = delivery.skills / 'user-owned/SKILL.md'
    results = delivery.run([[('read_file', {'path': str(first)}), ('read_file', {'path': str(other)}), ('skill_manage', patch_args())], ('skill_manage', patch_args())])
    assert segments == [['parallel', 'sequential']]
    assert results[2].get('_read_before_write_required') is True, results[2]
    assert results[3].get('success') is True, results[3]
    assert '新しい安全な手順' in first.read_text(encoding='utf-8')


@pytest.mark.parametrize('delivery', [65536], indirect=True)
def test_segmented_preview_never_confirms_omitted_target(delivery, monkeypatch):
    from agent import tool_executor
    real = tool_executor.execute_tool_calls_segmented
    segments = []
    def observe(*args, **kwargs):
        segments.append([kind for kind, _calls in kwargs['segments']])
        return real(*args, **kwargs)
    monkeypatch.setattr(tool_executor, 'execute_tool_calls_segmented', observe)
    target = delivery.skills / 'review-owned/SKILL.md'
    content = delivery.old.replace('旧手順', ('手順確認 ' + 'a' * 84 + '\n') * 1000 + '旧手順')
    target.write_text(content, encoding='utf-8')
    before = target.read_bytes()
    results = delivery.run([[('read_file', {'path': str(target), 'limit': 2000}), ('read_file', {'path': str(delivery.skills / 'user-owned/SKILL.md')}), ('skill_manage', patch_args())], ('skill_manage', patch_args())])
    assert segments == [['parallel', 'sequential']]
    assert 'delivered_preview' in results[0], results[0]
    assert '旧手順' not in results[0]['delivered_preview']
    denial = results[-1]
    if 'delivered_preview' in denial:
        denial = json.JSONDecoder().raw_decode(denial['delivered_preview'])[0]
    assert denial.get('_read_before_write_required') is True, results[-1]
    assert target.read_bytes() == before


@pytest.mark.parametrize('delivery', [65536], indirect=True)
def test_actual_executor_timeout_does_not_confirm_late_read(delivery, monkeypatch):
    from tools import file_tools, skill_manager_tool
    from agent import tool_executor
    config = delivery.home / 'config.yaml'
    data = yaml.safe_load(config.read_text(encoding='utf-8'))
    data['timeouts'] = {'tools': {'sequential_call': 10.0}}
    config.write_text(yaml.safe_dump(data), encoding='utf-8')
    assert tool_executor._resolve_sequential_tool_timeout() == 10.0
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()
    real_read, real_manage = file_tools.read_file_tool, skill_manager_tool.skill_manage
    real_mark = skill_manager_tool.mark_background_review_skill_read
    prepared, captured = [], []
    def observe_mark(path, *, result=None):
        captured.append(skill_manager_tool._background_review_read_capture.get() is not None)
        return real_mark(path, result=result)
    def delayed_read(*args, **kwargs):
        # Complete the real host read while its execution scope is active.
        # Hold that successful payload until the real executor times out.
        payload = real_read(*args, **kwargs)
        parsed = json.loads(payload)
        assert not parsed.get('error') and '旧手順' in parsed.get('content', ''), parsed
        prepared.append(parsed)
        entered.set()
        assert release.wait(20), 'owned read I/O was not released'
        returned.set()
        return payload
    def patch_after_late_read(*args, **kwargs):
        if kwargs.get('action', args[0] if args else None) == 'patch':
            release.set()
            assert returned.wait(10), 'late actual read did not finish before guarded patch'
        return real_manage(*args, **kwargs)
    monkeypatch.setattr(file_tools, 'read_file_tool', delayed_read)
    monkeypatch.setattr(skill_manager_tool, 'skill_manage', patch_after_late_read)
    monkeypatch.setattr(skill_manager_tool, 'mark_background_review_skill_read', observe_mark)
    target = delivery.skills / 'review-owned/SKILL.md'
    before = target.read_bytes()
    try:
        results = delivery.run([('read_file', {'path': str(target)}), ('skill_manage', patch_args())])
        assert entered.is_set() and returned.is_set()
        assert len(prepared) == 1 and captured == [True], (prepared, captured)
        assert 'timed out after 10.0s' in str(results[0]), results[0]
        assert results[1].get('_read_before_write_required') is True, results[1]
        assert target.read_bytes() == before
    finally:
        release.set()
