"""Strata native local inference and memory bridge for Hermes Agent.

Provides direct offloading of high-throughput and large-scale model inference
(DeepSeek-V4.1-Flash MLA, Qwen3.8-Flash-Next, arbitrary GGUF) to the local Strata engine,
with bidirectional synchronization of Hakua SOUL.md and MEMORY.md persistent memory.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import shutil
import struct
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_STRATA_URL = "http://127.0.0.1:8080/v1"
SOUL_PATHS = [
    Path("C:/Users/downl/.hermes/SOUL.md"),
    Path(os.path.expanduser("~/.hermes/SOUL.md")),
    Path("C:/Users/downl/SOUL.md"),
    Path(os.path.expanduser("~/SOUL.md")),
]
MEMORY_PATHS = [
    Path("C:/Users/downl/.hermes/memories/MEMORY.md"),
    Path(os.path.expanduser("~/.hermes/memories/MEMORY.md")),
    Path("C:/Users/downl/Documents/hermes-memory-vault/brain/MEMORY.md"),
]
HAKUA_DIR = Path("C:/Users/downl/.hakua-memory")


def get_base_url() -> str:
    """Resolve active Strata endpoint URL."""
    return os.environ.get("STRATA_BASE_URL") or os.environ.get("STRATA_ENDPOINT") or DEFAULT_STRATA_URL


def find_strata_bin() -> str | None:
    """Find installed or built Strata binary."""
    candidates = [
        os.environ.get("STRATA_BIN"),
        r"C:\Users\downl\AppData\Local\Programs\Strata\engine-bundle\0.1.47-windows-x86_64-cuda-cuda13\strata.exe",
        r"H:\Strata\build\native-spin8\Release\strata.exe",
        shutil.which("strata"),
        shutil.which("strata.exe"),
        r"C:\Users\downl\Documents\ChatGPT\Strata\strata.py",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def probe_strata_server() -> dict[str, Any]:
    """Check if the local Strata server is alive and return catalog/status."""
    base_url = get_base_url()
    models_url = f"{base_url.rstrip('/')}/models"
    models: list[str] = []
    alive = False
    error: str | None = None

    try:
        req = urllib.request.Request(models_url, headers={"User-Agent": "hermes-strata/1.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                alive = True
                data = json.loads(resp.read().decode("utf-8"))
                for item in data.get("data", []):
                    if isinstance(item, dict) and "id" in item:
                        models.append(item["id"])
    except urllib.error.URLError as e:
        error = f"Server not responding at {base_url} ({e.reason})"
    except Exception as e:
        error = f"Probe error: {str(e)}"

    bin_path = find_strata_bin()
    return {
        "alive": alive,
        "base_url": base_url,
        "models": models,
        "active_model": models[0] if models else None,
        "strata_bin": bin_path,
        "hardware": {
            "gpu": "NVIDIA GeForce RTX 5060 Ti 16GB (sm_120 Blackwell)",
            "system_ram": "32GB (Zero-VRAM CPU Drafter pool)",
            "supported_architectures": ["deepseek2", "deepseek_v3", "qwen2", "qwen2_moe", "spin8"],
        },
        "error": error,
    }


def resolve_soul_path() -> Path | None:
    """Find active SOUL.md path."""
    for p in SOUL_PATHS:
        if p.exists() and p.is_file():
            return p
    return None


def resolve_memory_path() -> Path:
    """Find active MEMORY.md path, defaulting to canonical location."""
    for p in MEMORY_PATHS:
        if p.exists() and p.is_file():
            return p
    # Fallback to standard path
    primary = MEMORY_PATHS[0]
    primary.parent.mkdir(parents=True, exist_ok=True)
    return primary


def read_soul_directives() -> str:
    """Read Hakua SOUL.md directives."""
    p = resolve_soul_path()
    if not p:
        return ""
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception as exc:
        logger.warning("Failed to read SOUL.md from %s: %s", p, exc)
        return ""


def read_memory_entries(max_entries: int = 20) -> list[str]:
    """Read recent memory entries from MEMORY.md."""
    p = resolve_memory_path()
    if not p.exists():
        return []
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        raw_entries = content.split("§")
        cleaned = [e.strip() for e in raw_entries if e.strip()]
        return cleaned[-max_entries:]
    except Exception as exc:
        logger.warning("Failed to read MEMORY.md from %s: %s", p, exc)
        return []


def append_memory_entry(entry: str) -> bool:
    """Safely append an entry to MEMORY.md with timestamp and delimiter."""
    if not entry or not entry.strip():
        return False
    p = resolve_memory_path()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    formatted = f"{now_str}: {entry.strip()}\n"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        append_prefix = "\n§\n" if p.exists() and p.stat().st_size > 0 else ""
        with open(p, "a", encoding="utf-8") as f:
            f.write(append_prefix + formatted)
        logger.info("Appended memory entry to %s", p)
        return True
    except Exception as exc:
        logger.error("Failed to append memory to %s: %s", p, exc)
        return False


def build_system_context(include_soul: bool = True, include_memory: bool = True, max_memories: int = 5) -> str:
    """Build persistent system prompt context containing Hakua alignment and memories."""
    blocks: list[str] = []
    if include_soul:
        soul = read_soul_directives()
        if soul:
            # Extract first 60 lines or core directives
            soul_lines = soul.splitlines()[:60]
            blocks.append("### CORE IDENTITY & DIRECTIVES (SOUL.md)\n" + "\n".join(soul_lines))

    if include_memory:
        memories = read_memory_entries(max_entries=max_memories)
        if memories:
            blocks.append("### RECENT MEMORY RECALL (MEMORY.md)\n" + "\n---\n".join(memories))

    return "\n\n".join(blocks)


def run_strata_inference(
    prompt: str,
    *,
    model: str | None = None,
    system_prompt: str | None = None,
    messages: list[dict[str, Any]] | None = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    thinking: bool = True,
    inject_memory: bool = False,
    timeout: int = 300,
) -> dict[str, Any]:
    """Execute chat completion request against local Strata engine."""
    base_url = get_base_url()
    endpoint = f"{base_url.rstrip('/')}/chat/completions"

    built_messages: list[dict[str, Any]] = []

    # Optional memory injection
    memory_context = build_system_context(include_soul=True, include_memory=True, max_memories=5) if inject_memory else ""
    full_system = f"{memory_context}\n\n{system_prompt}".strip() if system_prompt and memory_context else (system_prompt or memory_context)

    if full_system:
        built_messages.append({"role": "system", "content": full_system})

    if messages:
        built_messages.extend(messages)
    elif prompt:
        built_messages.append({"role": "user", "content": prompt})
    else:
        return {"success": False, "error": "No prompt or messages provided"}

    chosen_model = model or "deepseek-v4.1-flash"

    payload: dict[str, Any] = {
        "model": chosen_model,
        "messages": built_messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    # DeepSeek MLA thinking mode toggle
    if thinking and any(kw in chosen_model.lower() for kw in ("deepseek", "r1", "reasoner", "qwq")):
        payload["extra_body"] = {"thinking": {"type": "enabled"}}
        payload["reasoning_effort"] = "high"

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=req_data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "hermes-strata-inference/1.0",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_body = resp.read().decode("utf-8")
            data = json.loads(raw_body)
            choices = data.get("choices", [])
            first_choice = choices[0] if choices else {}
            msg = first_choice.get("message", {})
            content = msg.get("content", "")
            reasoning = msg.get("reasoning_content") or ""

            # Check if thinking tags are inside content
            if not reasoning and "<think>" in content and "</think>" in content:
                parts = content.split("</think>", 1)
                reasoning = parts[0].replace("<think>", "").strip()
                content = parts[1].strip()

            return {
                "success": True,
                "model": data.get("model", chosen_model),
                "content": content,
                "reasoning_content": reasoning,
                "usage": data.get("usage", {}),
                "finish_reason": first_choice.get("finish_reason", "stop"),
            }
    except urllib.error.URLError as e:
        logger.warning("Strata connection failed: %s", e)
        return {
            "success": False,
            "error": f"Strata inference server offline at {base_url}. Start with 'strata launch' or check port 8080. ({e.reason})",
            "model": chosen_model,
        }
    except Exception as exc:
        logger.error("Strata inference error: %s", exc)
        return {
            "success": False,
            "error": str(exc),
            "model": chosen_model,
        }


def inspect_gguf_file(path_str: str) -> dict[str, Any]:
    """Inspect arbitrary GGUF ModelBundle header and validate compatibility."""
    p = Path(path_str)
    if not p.exists() or not p.is_file():
        return {"valid": False, "error": f"File not found: {path_str}"}

    file_size = p.stat().st_size
    try:
        with open(p, "rb") as f:
            header = f.read(24)
            if len(header) < 24:
                return {"valid": False, "error": "File too small for GGUF header"}
            magic, version, tensor_count, metadata_kv_count = struct.unpack("<4sIQQ", header)
            if magic != b"GGUF":
                return {"valid": False, "error": f"Invalid magic bytes: {magic!r} (expected b'GGUF')"}

        # Heuristic compatibility assessment for RTX 5060 Ti 16GB + 32GB RAM
        size_gb = file_size / (1024**3)
        fits_vram = size_gb <= 14.5
        fits_total_ram = size_gb <= 30.0

        return {
            "valid": True,
            "path": str(p),
            "file_size_bytes": file_size,
            "file_size_gb": round(size_gb, 2),
            "gguf_version": version,
            "tensor_count": tensor_count,
            "metadata_kv_count": metadata_kv_count,
            "compatibility": {
                "fits_vram_directly": fits_vram,
                "fits_32gb_cpu_offload": fits_total_ram,
                "recommended_profile": "GPU-Resident (Full)" if fits_vram else ("Zero-VRAM Hybrid CPU Drafter" if fits_total_ram else "RAM Exceeded"),
            },
        }
    except Exception as exc:
        return {"valid": False, "error": f"Error parsing GGUF: {str(exc)}"}
