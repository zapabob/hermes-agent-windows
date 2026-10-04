"""Validated experimental items, holdout identity, and dimension-wise scoring."""

from __future__ import annotations
import hashlib
import json
import math
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Item(BaseModel):
    """A synthetic choice task; root metadata is audit data, not a command."""

    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1)
    family: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    options: list[str] = Field(min_length=4, max_length=4)
    gold: Literal["A", "B", "C", "D"]
    source_type: Literal["synthetic_derived", "synthetic_authored_eval"]
    root_id: str | None

    @model_validator(mode="after")
    def check_root(self) -> Item:
        if self.source_type == "synthetic_derived" and not self.root_id:
            raise ValueError("Derived examples require a real root locator")
        if self.source_type == "synthetic_authored_eval" and self.root_id is not None:
            raise ValueError("Frozen eval is authored independently of training roots")
        return self


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def prompt_hash(item: dict[str, Any]) -> str:
    value = item["prompt"] + "\n" + "\n".join(item["options"])
    normalized = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def verify_disjoint(train: list[dict[str, Any]], evaluation: list[dict[str, Any]]) -> dict[str, Any]:
    for x in train + evaluation:
        Item.model_validate(x)
    if not train or not evaluation:
        raise ValueError("Train and frozen evaluation must both be nonempty")
    ids = [x["id"] for x in train + evaluation]
    if len(ids) != len(set(ids)):
        raise ValueError("ID overlap")
    intersection = {prompt_hash(x) for x in train} & {prompt_hash(x) for x in evaluation}
    if intersection:
        raise ValueError("Normalized content/hash overlap")
    return {
        "train_count": len(train),
        "eval_count": len(evaluation),
        "id_overlap": 0,
        "normalized_prompt_hash_overlap": len(intersection),
        "scope": (
            "Exact and NFKC/whitespace-normalized prompts+options; "
            "not proof of all semantic near-duplicate exclusion"
        ),
    }


def summarize(gold: list[dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    index = {x["id"]: x for x in rows}
    if len(index) != len(rows) or set(index) != {x["id"] for x in gold}:
        raise ValueError("Duplicate or missing evaluation decisions; no zero-filled score")
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for x in gold:
        choice = index[x["id"]].get("choice")
        if not isinstance(choice, str) or len(choice) != 1 or choice not in "ABCD":
            raise ValueError("Invalid decision is missing, not a score of zero")
        totals[x["family"]][0] += int(choice == x["gold"])
        totals[x["family"]][1] += 1
    return {k: {"correct": a, "total": n, "rate": a / n} for k, (a, n) in sorted(totals.items())}


def compare(gold: list[dict[str, Any]], parent: list[dict[str, Any]], child: list[dict[str, Any]]) -> dict[str, Any]:
    p, c = summarize(gold, parent), summarize(gold, child)
    pi, ci = {x["id"]: x for x in parent}, {x["id"]: x for x in child}
    out: dict[str, Any] = {}
    for family in p:
        subset = [x for x in gold if x["family"] == family]
        gain = sum(pi[x["id"]]["choice"] != x["gold"] and ci[x["id"]]["choice"] == x["gold"] for x in subset)
        loss = sum(pi[x["id"]]["choice"] == x["gold"] and ci[x["id"]]["choice"] != x["gold"] for x in subset)
        n = gain + loss
        probability = min(1.0, 2 * sum(math.comb(n, i) for i in range(min(gain, loss) + 1)) / (2**n)) if n else 1.0
        out[family] = {
            "parent": p[family],
            "child": c[family],
            "delta": c[family]["rate"] - p[family]["rate"],
            "parent_wrong_child_right": gain,
            "parent_right_child_wrong": loss,
            "exact_paired_two_sided_p": probability,
            "p_scope": "Exploratory, not multiplicity-corrected; synthetic cases share templates",
        }
    return out


def read_items(path: Path) -> list[dict[str, Any]]:
    return [
        Item.model_validate(json.loads(line)).model_dump()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def check_frozen(identity: dict[str, str]) -> None:
    """Fail closed if any pre-registered file bytes changed."""
    for name, expected in identity.items():
        path = Path(name)
        if not path.is_file() or sha_file(path) != expected:
            raise ValueError("Frozen file changed or missing: " + name)
