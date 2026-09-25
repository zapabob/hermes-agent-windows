"""Local Ebbinghaus-inspired memory provider.

This plugin models durable memory as encoded cue sets with a simple
Ebbinghaus forgetting curve:

    retention = exp(-elapsed_days / stability_days)

Memories are stored locally in SQLite, searched with lexical/cue overlap,
and strengthened by explicit recall or rehearsal. Sleep maintenance is
finite: active capacity caps, archive-first forgetting, sleep rehearsal
limits, and optional provenance-backed dream consolidation.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.memory_provider import MemoryProvider
from tools.registry import tool_error

from .policies import EbbinghausPolicies, PolicyConfigError
from .schema_identity import open_shared_store
from .store import CapacityError, EbbinghausMemoryStore, forgetting_retention

logger = logging.getLogger(__name__)

__all__ = [
    "CapacityError",
    "EbbinghausMemoryProvider",
    "EbbinghausMemoryStore",
    "EbbinghausPolicies",
    "PolicyConfigError",
    "forgetting_retention",
    "register",
]


EBBINGHAUS_MEMORY_SCHEMA = {
    "name": "ebbinghaus_memory",
    "description": (
        "Local human-like memory with finite active capacity. Encodes memories "
        "into retrieval cues, stores them in SQLite, recalls by cue overlap, and "
        "models decay with an Ebbinghaus forgetting curve. Prefer prune_mode="
        "archive for sleep maintenance; use delete only when explicitly required. "
        "Dream uses preview then apply — the plugin does not call an external LLM."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "remember",
                    "recall",
                    "rehearse",
                    "forget",
                    "decay",
                    "sleep",
                    "list",
                    "stats",
                    "dream",
                    "revise",
                    "prediction_error",
                    "stabilize",
                    "retract",
                    "history",
                    "events",
                    "correction_check",
                    "insight_propose",
                    "insight_validate",
                    "insight_reject",
                ],
            },
            "content": {"type": "string", "description": "Memory content for remember."},
            "new_content": {
                "type": "string",
                "description": "Replacement belief content for revise.",
            },
            "query": {"type": "string", "description": "Cue/query for recall or rehearse."},
            "memory_id": {
                "type": "integer",
                "description": "Memory id for rehearse/forget/revise/retract/history.",
            },
            "belief_id": {
                "type": "string",
                "description": "Belief id for history when memory_id is omitted.",
            },
            "reason": {
                "type": "string",
                "description": "Non-empty reason for revise, retract, or insight_reject.",
            },
            "evidence": {
                "type": "array",
                "description": "Evidence objects for revise or insight_validate.",
            },
            "confidence": {
                "type": "number",
                "description": "Belief or insight confidence from 0.0 to 1.0.",
            },
            "test_query": {
                "type": "string",
                "description": "Correction rehearsal probe query for revise.",
            },
            "source": {
                "type": "string",
                "description": "Provenance source for remember, revise, or prediction_error.",
            },
            "expected_hash": {
                "type": "string",
                "description": "SHA-256 of the expected observation for prediction_error.",
            },
            "observed_hash": {
                "type": "string",
                "description": "SHA-256 of the observed outcome for prediction_error.",
            },
            "severity": {
                "type": "number",
                "description": "Prediction error severity from 0.0 to 1.0.",
            },
            "requires_revision": {
                "type": "boolean",
                "description": "Whether prediction_error should create a new belief version.",
            },
            "evidence_type": {
                "type": "string",
                "description": "Validated evidence class for stabilize.",
            },
            "evidence_hash": {
                "type": "string",
                "description": "SHA-256 of the evidence used for stabilize.",
            },
            "allow_rescue": {
                "type": "boolean",
                "description": "Allow latent/archive rescue on recall when experience is enabled.",
            },
            "include_history": {
                "type": "boolean",
                "description": "Include superseded/retracted/contested beliefs in recall.",
            },
            "include_experience": {
                "type": "boolean",
                "description": "Return full RecallAttemptResult fields for recall.",
            },
            "event_type": {
                "type": "string",
                "description": "Optional event_type filter for events action.",
            },
            "association_id": {
                "type": "string",
                "description": "Association preview id for insight_propose.",
            },
            "candidate_id": {
                "type": "string",
                "description": "Insight candidate id for validate/reject.",
            },
            "hypothesis": {
                "type": "string",
                "description": "Falsifiable hypothesis for insight_propose.",
            },
            "source_memory_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Source memory ids for insight_propose.",
            },
            "validation_method": {
                "type": "string",
                "description": "ValidationMethod wire value for insight_validate.",
            },
            "summary": {
                "type": "string",
                "description": "Optional validated insight summary.",
            },
            "tags": {"type": "string", "description": "Comma-separated tags or cue labels."},
            "salience": {"type": "number", "description": "Importance from 0.05 to 1.0."},
            "valence": {"type": "number", "description": "Emotional valence from -1.0 to 1.0."},
            "limit": {"type": "integer", "description": "Maximum result or sleep review count."},
            "min_score": {"type": "number", "description": "Minimum recall score."},
            "threshold": {"type": "number", "description": "Retention threshold for decay."},
            "rehearse_threshold": {
                "type": "number",
                "description": "Sleep retention threshold below which important memories may be rehearsed.",
            },
            "forget_threshold": {
                "type": "number",
                "description": "Sleep retention threshold below which low-value memories are forgotten/archived.",
            },
            "salience_keep_threshold": {
                "type": "number",
                "description": "Sleep salience cutoff for consolidation instead of forgetting.",
            },
            "prune": {
                "type": "boolean",
                "description": "Legacy flag: true forces physical delete. Prefer prune_mode.",
            },
            "prune_mode": {
                "type": "string",
                "enum": ["none", "archive", "delete"],
                "description": "Sleep disposition for forgotten traces. archive is the safe default.",
            },
            "include_archived": {
                "type": "boolean",
                "description": "Allow recall/list to include archived memories (operator use).",
            },
            "max_sleep_rehearsals": {
                "type": "integer",
                "description": "Max automatic sleep rehearsals per memory.",
            },
            "max_negative_sleep_rehearsals": {
                "type": "integer",
                "description": "Max automatic sleep rehearsals for strongly negative memories.",
            },
            "mode": {
                "type": "string",
                "enum": ["preview", "apply", "association_preview"],
                "description": "Dream mode: preview clusters, apply summaries, or association_preview.",
            },
            "dreams": {
                "type": "array",
                "description": "Dream apply payloads with cluster_id, source_memory_ids, summary, tags, salience, valence.",
            },
        },
        "required": ["action"],
    },
}


def _cfg_get(config: dict, *keys: str, default: Any = None) -> Any:
    """Nested dict get without importing hermes_cli.config (can hang under load)."""
    current: Any = config
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return default if current is None else current


def _load_plugin_config() -> dict:
    try:
        # Canonical loader: managed-scope overlay + ${VAR} expansion.
        from hermes_cli.config import load_config_readonly

        all_config = load_config_readonly()
        return (
            _cfg_get(all_config, "plugins", "ebbinghaus", default={})
            or _cfg_get(all_config, "plugins", "ebbinghaus-memory", default={})
            or {}
        )
    except Exception:
        return {}


STORE_BACKENDS = ("builtin", "hakua")


def _load_hakua_store_backend() -> tuple[Any, Any, type[Exception]]:
    """Return hakua-memory's store class, policies class and capacity error.

    hakua-memory is an optional extra; ``tools.lazy_deps`` installs it on
    first use (or raises ``FeatureUnavailable`` when installs are disabled).
    """
    try:
        from tools.lazy_deps import ensure as _lazy_ensure

        _lazy_ensure("memory.hakua", prompt=False)
    except ImportError:
        pass
    from hakua_memory.ebbinghaus.policies import EbbinghausPolicies as HakuaPolicies
    from hakua_memory.ebbinghaus.store import CapacityError as HakuaCapacityError
    from hakua_memory.ebbinghaus.store import EbbinghausMemoryStore as HakuaMemoryStore

    return HakuaMemoryStore, HakuaPolicies, HakuaCapacityError


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_text(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def _extract_candidate_memories(text: str) -> list[tuple[str, float]]:
    normalized = _normalize_text(text)
    if len(normalized) < 12:
        return []
    lowered = normalized.lower()
    patterns = [
        ("remember", 0.9),
        ("don't forget", 0.9),
        ("do not forget", 0.9),
        ("i prefer", 0.8),
        ("i always", 0.75),
        ("i never", 0.75),
        ("my default", 0.75),
        ("覚えて", 0.9),
        ("忘れない", 0.9),
        ("好み", 0.75),
        ("いつも", 0.75),
        ("使う", 0.65),
    ]
    for marker, salience in patterns:
        if marker in lowered:
            return [(normalized[:700], salience)]
    return []


class EbbinghausMemoryProvider(MemoryProvider):
    """Local memory provider with cue encoding and forgetting-curve decay."""

    def __init__(self, config: dict | None = None):
        self._config = config or _load_plugin_config()
        try:
            self._policies = EbbinghausPolicies.from_plugin_config(self._config)
        except PolicyConfigError as exc:
            logger.error("Invalid Ebbinghaus plugin config: %s", exc)
            raise
        self._store: EbbinghausMemoryStore | None = None
        self._store_backend = "builtin"
        self._capacity_errors: tuple[type[Exception], ...] = (CapacityError,)
        self._bridge: Any = None
        self._session_id = ""
        self._max_prefetch = int(self._policies.max_prefetch)
        self._min_prefetch_score = float(self._policies.min_prefetch_score)
        self._auto_encode_turns = bool(self._policies.auto_encode_turns)

    @property
    def name(self) -> str:
        return "ebbinghaus"

    @property
    def store_backend(self) -> str:
        """Store implementation in use: ``builtin`` or ``hakua``."""
        return self._store_backend

    def is_available(self) -> bool:
        return True

    def get_config_schema(self) -> List[Dict[str, Any]]:
        from hermes_constants import display_hermes_home
        return [
            {"key": "db_path", "description": "SQLite database path", "default": f"{display_hermes_home()}/ebbinghaus_memory.db"},
            {"key": "base_stability_days", "description": "Initial forgetting-curve stability in days", "default": "3.0"},
            {"key": "decay_threshold", "description": "Retention threshold considered forgotten", "default": "0.10"},
            {"key": "max_prefetch", "description": "Maximum memories injected before a turn", "default": "5"},
            {"key": "min_prefetch_score", "description": "Minimum score for automatic prefetch", "default": "0.18"},
            {"key": "auto_encode_turns", "description": "Auto-store preference-like user turns", "default": "false", "choices": ["true", "false"]},
            {"key": "store_backend", "description": "Store implementation (hakua uses the optional hakua-memory package and falls back to builtin)", "default": "builtin", "choices": list(STORE_BACKENDS)},
            {"key": "judge_enabled", "description": "Allow `hermes ebbinghaus judge --run` to send memories to the configured model for contradiction/goal review", "default": "false", "choices": ["true", "false"]},
            {"key": "judge_max_calls", "description": "Maximum model calls per judge run", "default": "20"},
        ]

    def save_config(self, values: Dict[str, Any], hermes_home: str) -> None:
        try:
            import yaml
            # Write-back round-trip: raw read only (do not persist merged defaults).
            from hermes_cli.config import read_user_config_raw

            config_path = Path(hermes_home) / "config.yaml"
            existing = read_user_config_raw(config_path)
            existing.setdefault("plugins", {})
            existing["plugins"]["ebbinghaus"] = values
            with open(config_path, "w", encoding="utf-8") as handle:
                yaml.safe_dump(existing, handle, allow_unicode=True, sort_keys=False)
        except Exception as exc:
            logger.debug("Ebbinghaus save_config failed: %s", exc)

    def initialize(self, session_id: str, **kwargs) -> None:
        raw_home = kwargs.get("hermes_home")
        if raw_home:
            hermes_home = Path(str(raw_home)).expanduser()
        else:
            from hermes_constants import get_hermes_home
            hermes_home = get_hermes_home()
        default_db = hermes_home / "ebbinghaus_memory.db"
        db_path = str(self._config.get("db_path") or default_db)
        db_path = db_path.replace("$HERMES_HOME", str(hermes_home))
        db_path = db_path.replace("${HERMES_HOME}", str(hermes_home))
        self._store = self._open_store(db_path)
        try:
            from plugins.semantic_graph.config import load_config
            from plugins.semantic_graph.store import SemanticGraphStore

            from .semantic_graph_bridge import (
                EbbinghausSemanticGraphBridge,
                bridge_is_enabled,
            )

            if bridge_is_enabled():
                graph_config = load_config()
                self._bridge = EbbinghausSemanticGraphBridge(
                    SemanticGraphStore(graph_config.db_path()),
                    memory_store=self._store,
                )
        except Exception as exc:
            logger.warning(
                "Ebbinghaus semantic graph bridge initialization skipped: %s",
                type(exc).__name__,
            )
        self._session_id = session_id

    def _open_store(self, db_path: str) -> Any:
        backend = str(self._config.get("store_backend") or "builtin").strip().lower()
        if backend == "hakua":
            try:
                store_cls, policies_cls, capacity_error = _load_hakua_store_backend()
                store = open_shared_store(
                    db_path,
                    store_cls=store_cls,
                    store_kwargs={"policies": policies_cls.from_plugin_config(self._config)},
                    canonical_kwargs={"policies": self._policies},
                )
            except Exception as exc:
                logger.warning(
                    "Ebbinghaus hakua-memory backend unavailable (%s: %s); "
                    "using builtin store",
                    type(exc).__name__,
                    exc,
                )
            else:
                logger.info("Ebbinghaus memory store backend: hakua-memory")
                self._store_backend = "hakua"
                self._capacity_errors = (CapacityError, capacity_error)
                return store
        elif backend != "builtin":
            logger.warning(
                "Unknown plugins.ebbinghaus.store_backend %r; using builtin store",
                backend,
            )
        self._store_backend = "builtin"
        self._capacity_errors = (CapacityError,)
        return EbbinghausMemoryStore(db_path, policies=self._policies)

    def _bridge_remember(self, result: dict[str, Any]) -> None:
        if self._bridge is None:
            return
        try:
            self._bridge.after_remember(result)
        except Exception as exc:
            logger.warning(
                "Ebbinghaus remember bridge invocation failed: %s",
                type(exc).__name__,
            )

    def _bridge_revision(self, result: dict[str, Any]) -> None:
        if self._bridge is None:
            return
        try:
            self._bridge.after_revision(result)
        except Exception as exc:
            logger.warning(
                "Ebbinghaus revision bridge invocation failed: %s",
                type(exc).__name__,
            )

    def _bridge_retraction(self, result: dict[str, Any]) -> None:
        if self._bridge is None:
            return
        try:
            self._bridge.after_retraction(result)
        except Exception as exc:
            logger.warning(
                "Ebbinghaus retraction bridge invocation failed: %s",
                type(exc).__name__,
            )

    def _bridge_dream(self, result: dict[str, Any]) -> None:
        if self._bridge is None:
            return
        try:
            self._bridge.after_dream_apply(result)
        except Exception as exc:
            logger.warning(
                "Ebbinghaus dream bridge invocation failed: %s",
                type(exc).__name__,
            )

    def system_prompt_block(self) -> str:
        if not self._store:
            return ""
        stats = self._store.stats()
        return (
            "# Ebbinghaus Memory\n"
            f"Active. {stats.get('active_count', stats.get('count', 0))} active / "
            f"{stats.get('count', 0)} total encoded memories stored locally. "
            "Use ebbinghaus_memory to remember durable facts, recall relevant "
            "context, rehearse important traces, sleep with prune_mode=archive, "
            "and dream preview/apply for semantic lessons."
        )

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        if not self._store or not query:
            return ""
        # Fetch a slightly larger pool, then apply valence-aware score floors.
        pool_limit = max(self._max_prefetch * 3, self._max_prefetch)
        attempt = self._store.recall_with_experience(
            query,
            limit=pool_limit,
            min_score=self._min_prefetch_score,
            reinforce=False,
            include_archived=False,
            allow_rescue=None,
            track=True,
        )
        results = list(attempt.results)
        if not results:
            return ""
        neg_floor = float(self._policies.sleep.negative_prefetch_min_score)
        neg_threshold = float(self._policies.sleep.negative_valence_threshold)
        filtered: list[dict] = []
        suppressed = 0
        for item in results:
            valence = float(item.get("valence") or 0.0)
            score = float(item.get("score") or 0.0)
            if valence <= neg_threshold and score < neg_floor:
                suppressed += 1
                continue
            filtered.append(item)
            if len(filtered) >= self._max_prefetch:
                break
        if suppressed:
            # Best-effort observability for rumination-bias metrics.
            try:
                self._store._negative_prefetch_suppressed_count += suppressed  # noqa: SLF001
            except Exception:
                pass
        if not filtered:
            return ""
        lines = []
        for item in filtered:
            lines.append(
                "- "
                f"[retention={item['retention']:.2f}, salience={item['salience']:.2f}] "
                f"{item['content']}"
            )
        body = "## Ebbinghaus Memory\n" + "\n".join(lines)
        if attempt.state_note:
            body = f"{body}\n\n{attempt.state_note}"
        return body

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        if not self._auto_encode_turns or not self._store:
            return
        for content, salience in _extract_candidate_memories(user_content):
            try:
                result = self._store.remember(
                    content,
                    tags=["auto", "user"],
                    salience=salience,
                    source="sync_turn",
                    session_id=session_id or self._session_id,
                )
                self._bridge_remember(result)
            except Exception as exc:
                logger.debug("Ebbinghaus sync_turn encode failed: %s", exc)

    def on_session_end(self, messages: List[Dict[str, Any]]) -> None:
        if not self._auto_encode_turns or not self._store:
            return
        for msg in messages:
            if msg.get("role") != "user":
                continue
            content = msg.get("content", "")
            if not isinstance(content, str):
                continue
            for memory, salience in _extract_candidate_memories(content):
                try:
                    result = self._store.remember(
                        memory,
                        tags=["auto", "session"],
                        salience=salience,
                        source="session_end",
                        session_id=self._session_id,
                    )
                    self._bridge_remember(result)
                except Exception as exc:
                    logger.debug("Ebbinghaus session encode failed: %s", exc)

    def on_memory_write(
        self,
        action: str,
        target: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if action not in {"add", "replace"} or not self._store or not content:
            return
        metadata = metadata or {}
        try:
            tags = ["built-in-memory", target]
            if metadata.get("platform"):
                tags.append(str(metadata["platform"]))
            result = self._store.remember(
                content,
                tags=tags,
                salience=0.8 if target == "user" else 0.7,
                source="memory_tool",
                session_id=str(metadata.get("session_id") or self._session_id),
            )
            self._bridge_remember(result)
        except Exception as exc:
            logger.debug("Ebbinghaus memory_write mirror failed: %s", exc)

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return [EBBINGHAUS_MEMORY_SCHEMA]

    def _sleep_defaults(self) -> dict[str, Any]:
        sleep = self._policies.sleep
        return {
            "rehearse_threshold": sleep.rehearse_threshold,
            "forget_threshold": sleep.forget_threshold,
            "salience_keep_threshold": sleep.salience_keep_threshold,
            "limit": sleep.limit,
            "prune_mode": sleep.prune_mode,
            "max_sleep_rehearsals": sleep.max_sleep_rehearsals,
            "max_negative_sleep_rehearsals": sleep.max_negative_sleep_rehearsals,
            "recent_replay_limit": sleep.recent_replay_limit,
            "remote_integration_limit": sleep.remote_integration_limit,
            "max_negative_replay_per_budget": (
                sleep.max_negative_replay_per_budget
            ),
        }

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
        if tool_name != "ebbinghaus_memory":
            return tool_error(f"Unknown tool: {tool_name}")
        if not self._store:
            return tool_error("Ebbinghaus memory is not initialized")
        try:
            action = str(args.get("action", "")).lower()
            if action == "remember":
                result = self._store.remember(
                    args.get("content", ""),
                    tags=args.get("tags"),
                    salience=float(args.get("salience", 0.65)),
                    valence=float(args.get("valence", 0.0)),
                    source=str(args.get("source", "tool")),
                    session_id=self._session_id,
                )
                self._bridge_remember(result)
                return json.dumps(
                    result,
                    ensure_ascii=False,
                )
            if action == "recall":
                include_experience = bool(args.get("include_experience", True))
                attempt = self._store.recall_with_experience(
                    args.get("query", ""),
                    limit=int(args.get("limit", 5)),
                    min_score=float(args.get("min_score", 0.12)),
                    reinforce=True,
                    include_archived=bool(args.get("include_archived", False)),
                    include_history=bool(args.get("include_history", False)),
                    allow_rescue=args.get("allow_rescue"),
                    track=True,
                )
                if include_experience:
                    return json.dumps(
                        {
                            "outcome": attempt.outcome.value,
                            "results": attempt.results,
                            "attempt_id": attempt.attempt_id,
                            "matched_miss_id": attempt.matched_miss_id,
                            "rescued_memory_id": attempt.rescued_memory_id,
                            "direct_best_score": attempt.direct_best_score,
                            "rescue_score": attempt.rescue_score,
                            "surprise": attempt.surprise,
                            "state_note": attempt.state_note,
                        },
                        ensure_ascii=False,
                    )
                return json.dumps({"results": attempt.results}, ensure_ascii=False)
            if action == "revise":
                result = self._store.revise_memory(
                    int(args["memory_id"]),
                    str(args.get("new_content") or args.get("content") or ""),
                    reason=str(args.get("reason") or ""),
                    evidence=args.get("evidence") or [],
                    confidence=float(args.get("confidence", 0.95)),
                    test_query=str(args.get("test_query") or ""),
                    source=str(args.get("source") or "explicit_correction"),
                    session_id=self._session_id,
                )
                self._bridge_revision(result)
                return json.dumps(
                    result,
                    ensure_ascii=False,
                )
            if action == "prediction_error":
                confidence = args.get("confidence")
                result = self._store.record_prediction_error(
                    int(args["memory_id"]),
                    source=str(args.get("source") or ""),
                    expected_hash=str(args.get("expected_hash") or ""),
                    observed_hash=str(args.get("observed_hash") or ""),
                    severity=float(args.get("severity", 0.0)),
                    requires_revision=bool(args.get("requires_revision", False)),
                    new_content=str(args.get("new_content") or ""),
                    reason=str(args.get("reason") or ""),
                    confidence=(None if confidence is None else float(confidence)),
                    test_query=str(args.get("test_query") or ""),
                    session_id=self._session_id,
                )
                revision = result.get("revision")
                if isinstance(revision, dict):
                    self._bridge_revision(revision)
                return json.dumps(result, ensure_ascii=False)
            if action == "stabilize":
                result = self._store.stabilize_memory(
                    int(args["memory_id"]),
                    evidence_type=str(args.get("evidence_type") or ""),
                    evidence_hash=str(args.get("evidence_hash") or ""),
                    session_id=self._session_id,
                )
                return json.dumps(result, ensure_ascii=False)
            if action == "retract":
                result = self._store.retract_memory(
                    int(args["memory_id"]),
                    reason=str(args.get("reason") or ""),
                    session_id=self._session_id,
                )
                self._bridge_retraction(result)
                return json.dumps(
                    result,
                    ensure_ascii=False,
                )
            if action == "history":
                return json.dumps(
                    {
                        "history": self._store.belief_history(
                            memory_id=args.get("memory_id"),
                            belief_id=str(args.get("belief_id") or ""),
                        )
                    },
                    ensure_ascii=False,
                )
            if action == "events":
                return json.dumps(
                    {
                        "events": self._store.list_events(
                            event_type=str(args.get("event_type") or ""),
                            memory_id=args.get("memory_id"),
                            limit=int(args.get("limit", 20)),
                        )
                    },
                    ensure_ascii=False,
                )
            if action == "correction_check":
                return json.dumps(
                    self._store.run_correction_check(
                        rehearsal_id=args.get("rehearsal_id"),
                        limit=int(args.get("limit", 10)),
                    ),
                    ensure_ascii=False,
                )
            if action == "insight_propose":
                return json.dumps(
                    self._store.propose_insight(
                        association_id=str(args.get("association_id") or ""),
                        hypothesis=str(args.get("hypothesis") or ""),
                        source_memory_ids=args.get("source_memory_ids") or [],
                        initial_confidence=float(args.get("confidence", 0.55)),
                    ),
                    ensure_ascii=False,
                )
            if action == "insight_validate":
                result = self._store.validate_insight(
                    candidate_id=str(args.get("candidate_id") or ""),
                    validation_method=str(args.get("validation_method") or "manual"),
                    evidence=args.get("evidence") or [],
                    validated_confidence=float(args.get("confidence", 0.8)),
                    summary=str(args.get("summary") or ""),
                )
                if result.get("promoted_memory_id") is not None:
                    self._bridge_remember(
                        {"memory_id": int(result["promoted_memory_id"])}
                    )
                return json.dumps(
                    result,
                    ensure_ascii=False,
                )
            if action == "insight_reject":
                return json.dumps(
                    self._store.reject_insight(
                        candidate_id=str(args.get("candidate_id") or ""),
                        reason=str(args.get("reason") or ""),
                    ),
                    ensure_ascii=False,
                )
            if action == "rehearse":
                return json.dumps(
                    {
                        "results": self._store.rehearse(
                            memory_id=args.get("memory_id"),
                            query=args.get("query", ""),
                            limit=int(args.get("limit", 1)),
                        )
                    },
                    ensure_ascii=False,
                )
            if action == "forget":
                return json.dumps(
                    {"forgotten": self._store.forget(int(args["memory_id"]))},
                    ensure_ascii=False,
                )
            if action == "decay":
                return json.dumps(
                    self._store.decay(
                        threshold=args.get("threshold"),
                        prune=bool(args.get("prune", False)),
                        limit=int(args.get("limit", 50)),
                    ),
                    ensure_ascii=False,
                )
            if action == "sleep":
                defaults = self._sleep_defaults()
                prune = args.get("prune")
                prune_mode = args.get("prune_mode")
                if prune is None and prune_mode is None:
                    prune_mode = defaults["prune_mode"]
                return json.dumps(
                    self._store.sleep_cycle(
                        rehearse_threshold=float(
                            args.get("rehearse_threshold", defaults["rehearse_threshold"])
                        ),
                        forget_threshold=args.get(
                            "forget_threshold", defaults["forget_threshold"]
                        ),
                        salience_keep_threshold=float(
                            args.get(
                                "salience_keep_threshold",
                                defaults["salience_keep_threshold"],
                            )
                        ),
                        prune=None if prune is None else bool(prune),
                        prune_mode=None if prune_mode is None else str(prune_mode),
                        limit=int(args.get("limit", defaults["limit"])),
                        max_sleep_rehearsals=args.get(
                            "max_sleep_rehearsals", defaults["max_sleep_rehearsals"]
                        ),
                        max_negative_sleep_rehearsals=args.get(
                            "max_negative_sleep_rehearsals",
                            defaults["max_negative_sleep_rehearsals"],
                        ),
                    ),
                    ensure_ascii=False,
                )
            if action == "list":
                return json.dumps(
                    {
                        "memories": self._store.list_memories(
                            limit=int(args.get("limit", 20)),
                            include_archived=bool(args.get("include_archived", False)),
                        )
                    },
                    ensure_ascii=False,
                )
            if action == "stats":
                return json.dumps(self._store.stats(), ensure_ascii=False)
            if action == "dream":
                mode = str(args.get("mode") or "preview").lower()
                if mode == "preview":
                    return json.dumps(self._store.dream_preview(), ensure_ascii=False)
                if mode == "association_preview":
                    return json.dumps(
                        self._store.association_preview(
                            limit=args.get("limit"),
                        ),
                        ensure_ascii=False,
                    )
                if mode == "apply":
                    result = self._store.dream_apply(args.get("dreams"))
                    self._bridge_dream(result)
                    return json.dumps(result, ensure_ascii=False)
                return tool_error(
                    "dream mode must be preview, apply, or association_preview"
                )
            return tool_error(f"Unknown action: {action}")
        except self._capacity_errors as exc:
            payload = {"error": str(exc), **(getattr(exc, "details", None) or {})}
            return json.dumps(payload, ensure_ascii=False)
        except KeyError as exc:
            return tool_error(f"Missing required argument: {exc}")
        except Exception as exc:
            return tool_error(str(exc))

    def shutdown(self) -> None:
        self._bridge = None
        if self._store:
            self._store.close()
            self._store = None


def register(ctx) -> None:
    """Register Ebbinghaus memory provider with the plugin system."""
    ctx.register_memory_provider(EbbinghausMemoryProvider())
    if hasattr(ctx, "register_skill"):
        try:
            from hermes_constants import get_bundled_skills_dir

            default_skills = Path(__file__).resolve().parents[3] / "skills"
            skill_path = (
                get_bundled_skills_dir(default_skills)
                / "autonomous-ai-agents"
                / "ebbinghaus-memory"
                / "SKILL.md"
            )
            if skill_path.exists():
                ctx.register_skill(
                    "ebbinghaus-memory",
                    skill_path,
                    "Use Ebbinghaus memory sleep, recall, dream, and decay.",
                )
        except Exception as exc:
            logger.debug("Ebbinghaus skill registration skipped: %s", exc)
