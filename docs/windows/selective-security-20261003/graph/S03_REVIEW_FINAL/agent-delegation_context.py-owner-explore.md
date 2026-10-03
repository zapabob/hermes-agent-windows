**Exploration: agent/delegation_context.py**

Found 13 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`agent/delegation_context.py`** — _DELEGATED_CHILD_CONTEXT(variable), _NON_DISPATCHER_OWNED_CONTEXT(variable), DELEGATED_CHILD_ENV_MARKER(variable), KANBAN_ENV_KEYS(variable), delegated_child_context(function), is_delegated_child_context(function), non_dispatcher_owned_context(function), is_dispatcher_owned_worker_context(function), enter_non_dispatcher_owned_context(function), exit_non_dispatcher_owned_context(function), is_delegated_child_process_context(function), scrub_kanban_env(function), delegated_child_subprocess_env(function)

```python
1	"""Context-local state for delegate_task child execution.
2
3	The parent Hermes process may itself be a Kanban dispatcher worker with
4	HERMES_KANBAN_* variables in process env. delegate_task children run inside the
5	same Python process, but they are not dispatcher-owned Kanban workers. This
6	module lets code paths that resolve tool schemas or spawn subprocesses fail
7	closed for delegated children without mutating global os.environ for the parent.
8
9	Cron jobs need the same treatment for the same reason: ``cronjob(action="run")``
10	executes ``run_job()`` in-process, so a cron agent fired from inside a Kanban
11	worker would otherwise inherit that worker's dispatcher identity.
12	``non_dispatcher_owned_context()`` covers both cases.
13	"""
14	from __future__ import annotations
15
16	from contextlib import contextmanager
17	from contextvars import ContextVar, Token
18	from typing import Iterable, Iterator, Mapping, MutableMapping
19
20	_DELEGATED_CHILD_CONTEXT: ContextVar[bool] = ContextVar(
21	    "hermes_delegated_child_context",
22	    default=False,
23	)
24
25	# Set for any in-process execution that is NOT the dispatcher-owned worker even
26	# though the worker's HERMES_KANBAN_* vars are legitimately in os.environ (cron
27	# jobs fired via the `cronjob` tool).  Kept separate from
28	# _DELEGATED_CHILD_CONTEXT so the delegate_task-specific behaviour attached to
29	# that flag (subprocess env scrubbing, its own error strings) is unchanged.
30	_NON_DISPATCHER_OWNED_CONTEXT: ContextVar[bool] = ContextVar(
31	    "hermes_non_dispatcher_owned_context",
32	    default=False,
33	)
34
35	DELEGATED_CHILD_ENV_MARKER = "HERMES_DELEGATED_CHILD_CONTEXT"
36
37	KANBAN_ENV_KEYS: tuple[str, ...] = (
38	    "HERMES_KANBAN_TASK",
39	    "HERMES_KANBAN_RUN_ID",
40	    "HERMES_KANBAN_WORKSPACE",
41	    "HERMES_KANBAN_WORKSPACES_ROOT",
42	    "HERMES_KANBAN_CLAIM_LOCK",
43	    "HERMES_KANBAN_BOARD",
44	    "HERMES_KANBAN_DB",
45	)
46
47
48	@contextmanager
49	def delegated_child_context(session_id: str | None = None) -> Iterator[None]:
50	    """Mark child execution and isolate its task-local session identity.
51
52	    Child construction calls ``set_current_session_id`` internally, so even a
53	    context entered without an id must restore the parent's ContextVar.  Child
54	    execution passes its explicit id and receives it only for this scope.
55	    """
56	    token = _DELEGATED_CHILD_CONTEXT.set(True)
57	    try:
58	        # Import lazily: session_context calls is_delegated_child_context() when
59	        # deciding whether the compatibility os.environ mirror is safe.
60	        from gateway.session_context import scoped_current_session_id
61
62	        with scoped_current_session_id(session_id):
63	            yield
64	    finally:
65	        _DELEGATED_CHILD_CONTEXT.reset(token)
66
67
68	def is_delegated_child_context() -> bool:
69	    """Return True while code is running for a delegate_task child."""
70	    return bool(_DELEGATED_CHILD_CONTEXT.get())
71
72
73	@contextmanager
74	def non_dispatcher_owned_context() -> Iterator[None]:
75	    """Mark in-process execution that does NOT own the dispatcher's Kanban task.
76
77	    A Kanban worker is a normal CLI agent whose default toolset includes
78	    ``cronjob``; ``cronjob(action="run")`` runs ``run_job()`` inside the worker's
79	    own process, where ``HERMES_KANBAN_TASK`` is legitimately set.  Without this
80	    marker the cron agent is misread as that worker: the kanban toolset is
81	    force-added, the worker protocol is injected into its system prompt, and
82	    ``kanban_complete`` defaults ``task_id`` to ``$HERMES_KANBAN_TASK`` — letting
83	    an unrelated cron job close the worker's task and overwrite real results.
84
85	    Scoped via ContextVar rather than by clearing ``os.environ``: the env is
86	    process-global and shared with the worker's own claim heartbeat, the
87	    gateway's Kanban watchers, and concurrent cron jobs on the parallel pool, so
88	    mutating it would starve the worker's claim and race those readers.
89	    """
90	    token = _NON_DISPATCHER_OWNED_CONTEXT.set(True)
91	    try:
92	        yield
93	    finally:
94	        _NON_DISPATCHER_OWNED_CONTEXT.reset(token)
95
96
97	def is_dispatcher_owned_worker_context() -> bool:
98	    """Return True only when this execution owns the dispatcher's Kanban task.
99
100	    The single predicate every ``HERMES_KANBAN_*`` identity gate should use
101	    before trusting those vars.  False for delegate_task children and for cron
102	    jobs fired in-process from a worker.
103	    """
104	    if _DELEGATED_CHILD_CONTEXT.get():
105	        return False
106	    return not _NON_DISPATCHER_OWNED_CONTEXT.get()
107
108
109	def enter_non_dispatcher_owned_context() -> Token[bool]:
110	    """Token-based form of :func:`non_dispatcher_owned_context`.
111
112	    For callers whose scope is a long ``try`` with a matching ``finally`` rather
113	    than a ``with`` block (``cron.scheduler.run_job``).  Pair with
114	    :func:`exit_non_dispatcher_owned_context`.
115	    """
116	    return _NON_DISPATCHER_OWNED_CONTEXT.set(True)
117
118
119	def exit_non_dispatcher_owned_context(token: Token[bool]) -> None:
120	    """Restore the flag saved by :func:`enter_non_dispatcher_owned_context`."""
121	    _NON_DISPATCHER_OWNED_CONTEXT.reset(token)
122
123
124	def is_delegated_child_process_context() -> bool:
125	    """Return True in this process or a subprocess spawned by a child."""
126	    import os
127
128	    return bool(_DELEGATED_CHILD_CONTEXT.get()) or bool(
129	        os.environ.get(DELEGATED_CHILD_ENV_MARKER)
130	    )
131
132
133	def scrub_kanban_env(env: Mapping[str, str] | MutableMapping[str, str]) -> dict[str, str]:
134	    """Return *env* with dispatcher-only Kanban variables removed."""
135	    cleaned = dict(env)
136	    for key in KANBAN_ENV_KEYS:
137	        cleaned.pop(key, None)
138	    cleaned[DELEGATED_CHILD_ENV_MARKER] = "1"
139	    return cleaned
140
141
142	def delegated_child_subprocess_env(
143	    env: Mapping[str, str] | MutableMapping[str, str] | None = None,
144	    *, allowed_provider_credentials: Iterable[str] = (),
145	) -> dict[str, str] | None:
146	    """Return an env override only when delegated-child lineage must cross fork.
147
148	    Most subprocess call sites historically used ``env=None`` to inherit the
149	    process environment.  In a ``delegate_task`` child, inheriting as-is leaks
150	    parent dispatcher ``HERMES_KANBAN_*`` vars while losing the ContextVar in
151	    the new process.  This helper preserves normal ``env=None`` semantics for
152	    non-delegated calls, and only materializes a scrubbed env when the lineage
153	    marker must be propagated across a child-process boundary.
154	    """
155	    if not is_delegated_child_process_context():
156	        return None if env is None else dict(env)
157
158	    if env is None:
159	        import os
160
161	        env = os.environ
162	    from tools.environments.local import build_subprocess_env, hermes_subprocess_env
163	    cleaned = build_subprocess_env(env)
164	    approved = {key.upper() for key in allowed_provider_credentials}
165	    if approved:
166	        eligible = hermes_subprocess_env(credential_keys=approved)
167	        # Preserve only caller-requested values validated by the same profile
168	        # and Tier-1 owner. A prepared foreign value cannot be reintroduced.
169	        for key, value in env.items():
170	            if key.upper() in approved and eligible.get(key) == value:
171	                cleaned[key] = value
172	    return scrub_kanban_env(cleaned)
```


---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (9,019 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.
