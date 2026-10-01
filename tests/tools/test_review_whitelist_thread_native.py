"""Native thread lifecycle contracts for the existing review restriction owner.

Only the network is disabled. Whitelist setters, directive lookup and the
production context wrapper are exercised directly, without owner doubles.
These tests inspect authorization decisions; they do not execute denied tools.
"""

from concurrent.futures import ThreadPoolExecutor
import contextvars
from pathlib import Path
import os
import socket
import threading

import pytest

from hermes_cli import plugins
from tools.thread_context import propagate_context_to_thread


TOOLS = ("memory", "read_file", "write_file", "terminal")
REVIEW_FMT = "Background review denied non-whitelisted tool: {tool_name}."
PRIOR_FMT = "Existing worker denied: {tool_name}."


def decisions():
    return {
        name: (directive.action, directive.message)
        for name in TOOLS
        for directive in [plugins._get_pre_tool_call_directive_details(name, {})]
    }


def expected(allowed, fmt=REVIEW_FMT):
    return {
        name: (None, None) if allowed is None or name in allowed
        else ("block", fmt.format(tool_name=name))
        for name in TOOLS
    }


@pytest.fixture(autouse=True)
def owned_environment(monkeypatch, tmp_path):
    assert Path(tmp_path).drive.upper() == "H:"
    assert Path(os.environ["HERMES_HOME"]).drive.upper() == "H:"
    attempted = []

    def deny_network(*args, **kwargs):
        attempted.append((args, kwargs))
        raise AssertionError("network is denied in the whitelist native tests")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(socket.socket, "connect_ex", deny_network)
    monkeypatch.setattr(socket, "create_connection", deny_network)
    plugins.clear_thread_tool_whitelist()
    try:
        yield
    finally:
        plugins.clear_thread_tool_whitelist()
        assert attempted == []


def real_thread(target):
    results = []
    failures = []

    def run():
        try:
            results.append(target())
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=run, name="owned-whitelist-native")
    thread.start()
    thread.join(timeout=10)
    assert not thread.is_alive(), "test-owned thread did not finish"
    if failures:
        raise failures[0]
    assert len(results) == 1
    return results[0]


def test_real_thread_inherits_allowlist_and_exact_denial_format():
    allowed = {"memory", "read_file"}
    plugins.set_thread_tool_whitelist(allowed, REVIEW_FMT)
    child = real_thread(propagate_context_to_thread(decisions))
    assert decisions() == expected(allowed)
    assert child == expected(allowed)


def test_empty_allowlist_denies_every_tool_in_real_thread():
    plugins.set_thread_tool_whitelist(set(), REVIEW_FMT)
    child = real_thread(propagate_context_to_thread(decisions))
    assert decisions() == expected(set())
    assert child == expected(set())


def test_allowlist_and_format_are_snapshotted_when_wrapper_is_created():
    allowed = {"memory"}
    plugins.set_thread_tool_whitelist(allowed, REVIEW_FMT)
    wrapped = propagate_context_to_thread(decisions)
    allowed.clear()
    allowed.add("write_file")
    plugins.set_thread_tool_whitelist(allowed, PRIOR_FMT)
    child = real_thread(wrapped)
    assert decisions() == expected({"write_file"}, PRIOR_FMT)
    assert child == expected({"memory"}, REVIEW_FMT)


@pytest.mark.parametrize("raises", [False, True], ids=["completion", "exception"])
def test_reused_executor_restores_unrestricted_state(raises):
    seen = {}
    plugins.set_thread_tool_whitelist({"memory"}, REVIEW_FMT)

    def task():
        seen["during"] = (threading.get_ident(), decisions())
        if raises:
            raise ValueError("owned target failure")
        return "completed"

    wrapped = propagate_context_to_thread(task)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="owned-reuse") as pool:
        before = pool.submit(lambda: (threading.get_ident(), decisions())).result(10)
        future = pool.submit(wrapped)
        if raises:
            with pytest.raises(ValueError, match="owned target failure"):
                future.result(10)
        else:
            assert future.result(10) == "completed"
        after = pool.submit(lambda: (threading.get_ident(), decisions())).result(10)
    assert before[0] == seen["during"][0] == after[0]
    assert before[1] == after[1] == expected(None)
    assert decisions() == expected({"memory"})
    assert seen["during"][1] == expected({"memory"})


@pytest.mark.parametrize("raises", [False, True], ids=["completion", "exception"])
def test_reused_executor_restores_workers_existing_restriction(raises):
    seen = {}
    plugins.set_thread_tool_whitelist({"memory"}, REVIEW_FMT)

    def target():
        seen["during"] = (threading.get_ident(), decisions())
        if raises:
            raise LookupError("owned nested failure")
        return "completed"

    wrapped = propagate_context_to_thread(target)

    def install_prior():
        plugins.set_thread_tool_whitelist({"read_file"}, PRIOR_FMT)
        return threading.get_ident(), decisions()

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="owned-prior") as pool:
        before = pool.submit(install_prior).result(10)
        try:
            future = pool.submit(wrapped)
            if raises:
                with pytest.raises(LookupError, match="owned nested failure"):
                    future.result(10)
            else:
                assert future.result(10) == "completed"
            after = pool.submit(lambda: (threading.get_ident(), decisions())).result(10)
        finally:
            pool.submit(plugins.clear_thread_tool_whitelist).result(10)
    assert before[0] == seen["during"][0] == after[0]
    assert before[1] == after[1] == expected({"read_file"}, PRIOR_FMT)
    assert decisions() == expected({"memory"})
    assert seen["during"][1] == expected({"memory"})


@pytest.mark.parametrize("raises", [False, True], ids=["completion", "exception"])
def test_synchronous_nested_wrapper_restores_current_owner(raises):
    seen = {}
    plugins.set_thread_tool_whitelist({"memory"}, REVIEW_FMT)

    def target(value, *, suffix):
        seen["during"] = decisions()
        if raises:
            raise RuntimeError("owned synchronous failure")
        return value + suffix

    wrapped = propagate_context_to_thread(target)
    plugins.set_thread_tool_whitelist({"read_file"}, PRIOR_FMT)
    if raises:
        with pytest.raises(RuntimeError, match="owned synchronous failure"):
            wrapped("argument", suffix="-forwarded")
    else:
        assert wrapped("argument", suffix="-forwarded") == "argument-forwarded"
    assert decisions() == expected({"read_file"}, PRIOR_FMT)
    assert seen["during"] == expected({"memory"})


def test_two_wrapped_levels_restore_the_outer_restriction():
    seen = {}
    plugins.set_thread_tool_whitelist({"read_file"}, PRIOR_FMT)
    inner = propagate_context_to_thread(decisions)
    plugins.set_thread_tool_whitelist({"memory"}, REVIEW_FMT)

    def outer_target():
        seen["outer_before"] = decisions()
        seen["inner"] = inner()
        seen["outer_after"] = decisions()

    real_thread(propagate_context_to_thread(outer_target))
    assert decisions() == expected({"memory"})
    assert seen == {
        "outer_before": expected({"memory"}),
        "inner": expected({"read_file"}, PRIOR_FMT),
        "outer_after": expected({"memory"}),
    }


def test_concurrent_different_restrictions_are_isolated():
    barrier = threading.Barrier(2)

    def target():
        barrier.wait(timeout=10)
        return threading.get_ident(), decisions()

    plugins.set_thread_tool_whitelist({"memory"}, REVIEW_FMT)
    first = propagate_context_to_thread(target)
    plugins.set_thread_tool_whitelist({"read_file"}, PRIOR_FMT)
    second = propagate_context_to_thread(target)
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="owned-concurrent") as pool:
        a, b = pool.submit(first), pool.submit(second)
        first_seen, second_seen = a.result(15), b.result(15)
    assert first_seen[0] != second_seen[0]
    assert decisions() == expected({"read_file"}, PRIOR_FMT)
    assert first_seen[1] == expected({"memory"})
    assert second_seen[1] == expected({"read_file"}, PRIOR_FMT)


def test_unrestricted_wrapped_sibling_is_not_given_another_tasks_restriction():
    barrier = threading.Barrier(2)

    def target():
        barrier.wait(timeout=10)
        return threading.get_ident(), decisions()

    plugins.set_thread_tool_whitelist({"memory"}, REVIEW_FMT)
    restricted = propagate_context_to_thread(target)
    plugins.clear_thread_tool_whitelist()
    unrestricted = propagate_context_to_thread(target)
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="owned-sibling") as pool:
        a, b = pool.submit(restricted), pool.submit(unrestricted)
        restricted_seen, unrestricted_seen = a.result(15), b.result(15)
    assert restricted_seen[0] != unrestricted_seen[0]
    assert decisions() == unrestricted_seen[1] == expected(None)
    assert restricted_seen[1] == expected({"memory"})


def test_unrestricted_parent_temporarily_overrides_workers_prior_restriction():
    wrapped = propagate_context_to_thread(decisions)

    def worker():
        plugins.set_thread_tool_whitelist({"read_file"}, PRIOR_FMT)
        try:
            before = decisions()
            during = wrapped()
            after = decisions()
            return before, during, after
        finally:
            plugins.clear_thread_tool_whitelist()

    before, during, after = real_thread(worker)
    assert before == after == expected({"read_file"}, PRIOR_FMT)
    assert decisions() == expected(None)
    assert during == expected(None)


def test_unwrapped_thread_remains_unrestricted_control():
    plugins.set_thread_tool_whitelist({"memory"}, REVIEW_FMT)
    child = real_thread(decisions)
    assert decisions() == expected({"memory"})
    assert child == expected(None)


def test_unrestricted_wrapped_thread_preserves_unrestricted_control():
    assert decisions() == expected(None)
    assert real_thread(propagate_context_to_thread(decisions)) == expected(None)


@pytest.mark.parametrize("raises", [False, True], ids=["completion", "exception"])
def test_copy_context_executor_inherits_and_restores_existing_worker(raises):
    seen = {}
    plugins.set_thread_tool_whitelist({"memory"}, REVIEW_FMT)
    copied = contextvars.copy_context()

    def target():
        seen["during"] = (threading.get_ident(), decisions())
        if raises:
            raise ValueError("owned copied-context failure")
        return "completed"

    def prior():
        plugins.set_thread_tool_whitelist({"read_file"}, PRIOR_FMT)
        return threading.get_ident(), decisions()

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="owned-copy") as pool:
        before = pool.submit(prior).result(10)
        try:
            future = pool.submit(copied.run, target)
            if raises:
                with pytest.raises(ValueError, match="owned copied-context failure"):
                    future.result(10)
            else:
                assert future.result(10) == "completed"
            after = pool.submit(lambda: (threading.get_ident(), decisions())).result(10)
        finally:
            pool.submit(plugins.clear_thread_tool_whitelist).result(10)
    assert before[0] == seen["during"][0] == after[0]
    assert before[1] == after[1] == expected({"read_file"}, PRIOR_FMT)
    assert decisions() == expected({"memory"})
    assert seen["during"][1] == expected({"memory"})


def test_copy_context_captures_allowlist_before_caller_mutates_its_set():
    allowed = {"memory"}
    plugins.set_thread_tool_whitelist(allowed, REVIEW_FMT)
    copied = contextvars.copy_context()
    allowed.clear()
    allowed.add("write_file")
    plugins.set_thread_tool_whitelist({"read_file"}, PRIOR_FMT)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="owned-copy-snapshot") as pool:
        child = pool.submit(copied.run, decisions).result(10)
        after = pool.submit(decisions).result(10)
    assert decisions() == expected({"read_file"}, PRIOR_FMT)
    assert after == expected(None)
    assert child == expected({"memory"})


@pytest.mark.parametrize("raises", [False, True], ids=["completion", "exception"])
def test_copy_context_synchronous_run_restores_enclosing_restriction(raises):
    seen = {}
    plugins.set_thread_tool_whitelist({"memory"}, REVIEW_FMT)
    copied = contextvars.copy_context()
    plugins.set_thread_tool_whitelist({"read_file"}, PRIOR_FMT)

    def target():
        seen["during"] = decisions()
        if raises:
            raise RuntimeError("owned copied sync failure")
        return "completed"

    if raises:
        with pytest.raises(RuntimeError, match="owned copied sync failure"):
            copied.run(target)
    else:
        assert copied.run(target) == "completed"
    assert decisions() == expected({"read_file"}, PRIOR_FMT)
    assert seen["during"] == expected({"memory"})


class AsyncCheckpoint:
    """One bounded coroutine suspension, with no event loop or network."""

    def __await__(self):
        yield None


def resume(copied, coroutine):
    try:
        return False, copied.run(coroutine.send, None)
    except StopIteration as finished:
        return True, finished.value


def test_async_coroutine_resume_keeps_independent_captured_restrictions():
    async def target():
        before = decisions()
        await AsyncCheckpoint()
        return before, decisions()

    plugins.set_thread_tool_whitelist({"memory"}, REVIEW_FMT)
    first_context = contextvars.copy_context()
    plugins.set_thread_tool_whitelist({"read_file"}, PRIOR_FMT)
    second_context = contextvars.copy_context()
    plugins.clear_thread_tool_whitelist()
    first, second = target(), target()
    try:
        assert resume(first_context, first) == (False, None)
        assert resume(second_context, second) == (False, None)
        first_done, first_result = resume(first_context, first)
        second_done, second_result = resume(second_context, second)
    finally:
        first.close()
        second.close()
    assert first_done and second_done
    assert decisions() == expected(None)
    assert first_result == (expected({"memory"}), expected({"memory"}))
    assert second_result == (expected({"read_file"}, PRIOR_FMT), expected({"read_file"}, PRIOR_FMT))


def test_async_coroutine_local_change_does_not_leak_to_parent_or_sibling():
    plugins.set_thread_tool_whitelist({"memory"}, REVIEW_FMT)
    first_context = contextvars.copy_context()
    sibling_context = contextvars.copy_context()

    async def target():
        plugins.set_thread_tool_whitelist({"read_file"}, PRIOR_FMT)
        await AsyncCheckpoint()
        return decisions()

    coroutine = target()
    try:
        assert resume(first_context, coroutine) == (False, None)
        parent_during = decisions()
        sibling_during = sibling_context.run(decisions)
        finished, child = resume(first_context, coroutine)
    finally:
        coroutine.close()
    assert finished
    assert child == expected({"read_file"}, PRIOR_FMT)
    assert parent_during == sibling_during == decisions() == expected({"memory"})
