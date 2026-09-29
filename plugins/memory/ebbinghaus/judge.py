"""Opt-in LLM-as-judge review of Ebbinghaus memories.

Each candidate memory is evaluated against the memories that recall surfaces
for it, using hakua-memory's structured evaluation primitive
(``SemanticGraphInference.evaluate_output``) on top of the host-owned plugin
LLM, so the user's configured provider and auth are used as-is.

The judge is read-only with respect to memories: it only lists, recalls with
``reinforce=False, track=False`` and reads. Findings (contradiction pairs and
goal achievement status) are written to a separate database so a human can
review them; nothing is edited, archived or deleted automatically.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

logger = logging.getLogger(__name__)

PLUGIN_ID = "ebbinghaus"
FINDINGS_DB = "judge_findings.db"

JUDGE_CRITERIA = [
    "contradiction: identify statements in the text that contradict a reference "
    "memory; cite the contradicting reference ids in evidence_ids",
    "goal status: if the text states a goal, task, plan or commitment, mark the "
    "claim supported when the reference memories show it was achieved, "
    "contradicted when they show it failed or was abandoned, and unsupported "
    "when there is no evidence of completion",
    "internal consistency",
]

GOAL_TAGS = frozenset({"goal", "goals", "todo", "task", "tasks", "plan", "action-item", "milestone"})
GOAL_HINT = re.compile(
    r"(?i)\b(goal|todo|to-do|task|plan(?:ned|ning)?|will|need to|must|deadline|milestone|commit(?:ted)? to)\b"
    r"|目標|予定|タスク|課題|締切|締め切り|達成|やる|したい|するつもり|宿題"
)
REFERENCE_ID = re.compile(r"^memory:(\d+)$")

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS judge_runs (
        run_id TEXT PRIMARY KEY,
        started_at REAL NOT NULL,
        finished_at REAL,
        store_backend TEXT NOT NULL,
        candidates INTEGER NOT NULL DEFAULT 0,
        calls INTEGER NOT NULL DEFAULT 0,
        errors INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS judge_reviews (
        memory_id INTEGER NOT NULL,
        memory_updated_at REAL NOT NULL,
        run_id TEXT NOT NULL,
        verdict TEXT NOT NULL,
        overall_score REAL,
        confidence REAL,
        reviewed_at REAL NOT NULL,
        PRIMARY KEY (memory_id, memory_updated_at)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS judge_findings (
        finding_id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('contradiction', 'goal_status')),
        memory_id INTEGER NOT NULL,
        related_memory_id INTEGER,
        status TEXT NOT NULL,
        claim_text TEXT NOT NULL DEFAULT '',
        notes TEXT NOT NULL DEFAULT '',
        confidence REAL,
        review_state TEXT NOT NULL DEFAULT 'open',
        created_at REAL NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_judge_findings_memory ON judge_findings(memory_id)",
)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: Any, default: int, *, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


@dataclass(frozen=True)
class JudgeSettings:
    enabled: bool = False
    max_calls: int = 20
    reference_limit: int = 5
    scan_limit: int = 200

    @classmethod
    def from_plugin_config(cls, config: dict[str, Any] | None) -> "JudgeSettings":
        config = config or {}
        return cls(
            enabled=_as_bool(config.get("judge_enabled", False)),
            max_calls=_as_int(config.get("judge_max_calls"), 20, low=1, high=500),
            reference_limit=_as_int(config.get("judge_reference_limit"), 5, low=1, high=20),
            scan_limit=_as_int(config.get("judge_scan_limit"), 200, low=1, high=5000),
        )


def is_goal_like(memory: dict[str, Any]) -> bool:
    tags = memory.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    if any(str(t).strip().lower() in GOAL_TAGS for t in tags):
        return True
    return bool(GOAL_HINT.search(str(memory.get("content") or "")))


def goal_status(claims: Iterable[dict[str, Any]]) -> str:
    supports = {str(c.get("support") or "") for c in claims}
    if "supported" in supports and not supports & {"contradicted", "unsupported"}:
        return "achieved"
    if supports & {"contradicted", "unsupported"}:
        return "unachieved"
    return "unknown"


class FindingsStore:
    """Review flags live in plugin-data, never inside the shared memory DB."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        for statement in _SCHEMA:
            self._conn.execute(statement)
        self._conn.commit()

    @classmethod
    def open_default(cls) -> "FindingsStore":
        from plugins.plugin_storage import plugin_db

        return cls(plugin_db(PLUGIN_ID, FINDINGS_DB))

    def already_reviewed(self, memory_id: int, updated_at: float) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM judge_reviews WHERE memory_id = ? AND memory_updated_at = ?",
            (memory_id, updated_at),
        ).fetchone()
        return row is not None

    def start_run(self, run_id: str, backend: str) -> None:
        self._conn.execute(
            "INSERT INTO judge_runs (run_id, started_at, store_backend) VALUES (?, ?, ?)",
            (run_id, time.time(), backend),
        )
        self._conn.commit()

    def finish_run(self, run_id: str, *, candidates: int, calls: int, errors: int) -> None:
        self._conn.execute(
            "UPDATE judge_runs SET finished_at = ?, candidates = ?, calls = ?, errors = ? WHERE run_id = ?",
            (time.time(), candidates, calls, errors, run_id),
        )
        self._conn.commit()

    def record_review(
        self,
        run_id: str,
        memory: dict[str, Any],
        evaluation: dict[str, Any],
        findings: list[dict[str, Any]],
    ) -> None:
        now = time.time()
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO judge_reviews (memory_id, memory_updated_at, run_id, verdict,"
                " overall_score, confidence, reviewed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    int(memory["memory_id"]),
                    float(memory.get("updated_at") or 0.0),
                    run_id,
                    str(evaluation.get("verdict") or ""),
                    evaluation.get("overall_score"),
                    evaluation.get("confidence"),
                    now,
                ),
            )
            self._conn.executemany(
                "INSERT INTO judge_findings (run_id, kind, memory_id, related_memory_id, status,"
                " claim_text, notes, confidence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        run_id,
                        f["kind"],
                        f["memory_id"],
                        f.get("related_memory_id"),
                        f["status"],
                        f.get("claim_text", ""),
                        f.get("notes", ""),
                        f.get("confidence"),
                        now,
                    )
                    for f in findings
                ],
            )

    def list_findings(self, *, limit: int = 50, review_state: str = "open") -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT finding_id, run_id, kind, memory_id, related_memory_id, status, confidence,"
            " review_state, created_at FROM judge_findings WHERE review_state = ?"
            " ORDER BY finding_id DESC LIMIT ?",
            (review_state, max(1, int(limit))),
        ).fetchall()
        keys = (
            "finding_id", "run_id", "kind", "memory_id", "related_memory_id",
            "status", "confidence", "review_state", "created_at",
        )
        return [dict(zip(keys, row)) for row in rows]

    def close(self) -> None:
        self._conn.close()


@dataclass
class JudgeReport:
    run_id: str
    dry_run: bool
    budget: int = 0
    scanned: int = 0
    candidates: int = 0
    goal_like_candidates: int = 0
    calls: int = 0
    errors: int = 0
    skipped_no_references: int = 0
    skipped_already_reviewed: int = 0
    contradictions: int = 0
    goals: dict[str, int] = field(default_factory=lambda: {"achieved": 0, "unachieved": 0, "unknown": 0})

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "dry_run": self.dry_run,
            "scanned": self.scanned,
            "candidates": self.candidates,
            "goal_like_candidates": self.goal_like_candidates,
            "call_budget": self.budget,
            "planned_calls": min(self.candidates, self.budget) if self.dry_run else self.calls,
            "llm_calls": self.calls,
            "errors": self.errors,
            "skipped_no_references": self.skipped_no_references,
            "skipped_already_reviewed": self.skipped_already_reviewed,
            "contradiction_flags": self.contradictions,
            "goal_status": dict(self.goals),
        }


def _default_evaluator(llm: Any) -> Callable[..., dict[str, Any]]:
    from hakua_memory.semantic_graph.inference import SemanticGraphInference

    return SemanticGraphInference(llm).evaluate_output


class MemoryJudge:
    def __init__(
        self,
        store: Any,
        findings: FindingsStore,
        settings: JudgeSettings,
        *,
        llm: Any = None,
        evaluator: Optional[Callable[..., dict[str, Any]]] = None,
        store_backend: str = "builtin",
    ) -> None:
        self._store = store
        self._findings = findings
        self._settings = settings
        self._llm = llm
        self._evaluator = evaluator
        self._backend = store_backend

    def _references(self, memory: dict[str, Any]) -> list[dict[str, Any]]:
        attempt = self._store.recall_with_experience(
            str(memory.get("content") or ""),
            limit=self._settings.reference_limit + 1,
            min_score=0.05,
            reinforce=False,
            include_archived=False,
            allow_rescue=False,
            track=False,
        )
        refs = []
        for item in attempt.results:
            if int(item["memory_id"]) == int(memory["memory_id"]):
                continue
            refs.append(
                {
                    "id": f"memory:{int(item['memory_id'])}",
                    "content": str(item.get("content") or ""),
                    "created_at": item.get("created_at"),
                }
            )
        return refs[: self._settings.reference_limit]

    def _candidates(self, memory_ids: Optional[list[int]]) -> list[dict[str, Any]]:
        if memory_ids:
            out = []
            for memory_id in memory_ids:
                try:
                    out.append(self._store.get(int(memory_id)))
                except KeyError:
                    logger.warning("Ebbinghaus judge: memory %s not found", memory_id)
            return out
        rows = self._store.list_memories(limit=self._settings.scan_limit)
        # Goal-like traces first: achievement status is the scarcer signal.
        return sorted(rows, key=lambda m: not is_goal_like(m))

    def run(
        self,
        *,
        dry_run: bool = True,
        max_calls: Optional[int] = None,
        memory_ids: Optional[list[int]] = None,
    ) -> JudgeReport:
        budget = min(max_calls or self._settings.max_calls, self._settings.max_calls)
        report = JudgeReport(run_id=uuid.uuid4().hex, dry_run=dry_run, budget=budget)
        if not dry_run and not self._settings.enabled:
            raise PermissionError(
                "Ebbinghaus judge is disabled; set plugins.ebbinghaus.judge_enabled: true in config.yaml"
            )
        evaluator = self._evaluator
        if not dry_run and evaluator is None:
            evaluator = _default_evaluator(self._llm)
        if not dry_run:
            self._findings.start_run(report.run_id, self._backend)

        try:
            for memory in self._candidates(memory_ids):
                report.scanned += 1
                memory_id = int(memory["memory_id"])
                if self._findings.already_reviewed(memory_id, float(memory.get("updated_at") or 0.0)):
                    report.skipped_already_reviewed += 1
                    continue
                refs = self._references(memory)
                if not refs:
                    report.skipped_no_references += 1
                    continue
                report.candidates += 1
                if is_goal_like(memory):
                    report.goal_like_candidates += 1
                if dry_run or report.calls >= budget:
                    continue
                report.calls += 1
                try:
                    evaluation = evaluator(
                        str(memory.get("content") or ""),
                        criteria=JUDGE_CRITERIA,
                        reference_nodes=refs,
                    )
                except Exception as exc:
                    report.errors += 1
                    logger.warning("Ebbinghaus judge evaluation failed for %s: %s", memory_id, type(exc).__name__)
                    continue
                findings = self._findings_from(memory, refs, evaluation)
                self._findings.record_review(report.run_id, memory, evaluation, findings)
                for f in findings:
                    if f["kind"] == "contradiction":
                        report.contradictions += 1
                    else:
                        report.goals[f["status"]] += 1
        finally:
            if not dry_run:
                self._findings.finish_run(
                    report.run_id,
                    candidates=report.candidates,
                    calls=report.calls,
                    errors=report.errors,
                )
        return report

    @staticmethod
    def _findings_from(
        memory: dict[str, Any],
        refs: list[dict[str, Any]],
        evaluation: dict[str, Any],
    ) -> list[dict[str, Any]]:
        memory_id = int(memory["memory_id"])
        allowed = {r["id"] for r in refs}
        confidence = evaluation.get("confidence")
        claims = [c for c in evaluation.get("claims") or [] if isinstance(c, dict)]
        findings: list[dict[str, Any]] = []
        seen: set[int] = set()
        for claim in claims:
            if claim.get("support") != "contradicted":
                continue
            for evidence in claim.get("evidence_ids") or []:
                # Only ids we actually supplied count; anything else is a hallucinated reference.
                match = REFERENCE_ID.match(str(evidence))
                if str(evidence) not in allowed or not match:
                    continue
                related = int(match.group(1))
                if related in seen:
                    continue
                seen.add(related)
                findings.append(
                    {
                        "kind": "contradiction",
                        "memory_id": memory_id,
                        "related_memory_id": related,
                        "status": "contradicted",
                        "claim_text": str(claim.get("claim_text") or ""),
                        "notes": str(claim.get("notes") or ""),
                        "confidence": confidence,
                    }
                )
        if is_goal_like(memory):
            findings.append(
                {
                    "kind": "goal_status",
                    "memory_id": memory_id,
                    "related_memory_id": None,
                    "status": goal_status(claims),
                    "claim_text": "",
                    "notes": "; ".join(str(c.get("notes") or "") for c in claims if c.get("notes"))[:1000],
                    "confidence": confidence,
                }
            )
        return findings
