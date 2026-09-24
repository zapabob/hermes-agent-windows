from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable

from hermes_constants import get_hermes_home

from .models import EngineState, Finding
from .store import SecurityStore


class HashReputationEngine:
    name = "hash_reputation"

    def __init__(self, store: SecurityStore) -> None:
        self.store = store

    def version(self) -> str:
        return self.store.feed_versions().get("hash_reputation", "empty")

    def scan(self, _path: Path, sha256: str) -> list[Finding]:
        row = self.store.lookup_hash(sha256)
        if row is None:
            return []
        family = row["malware_family"] or row["label"]
        return [
            Finding(
                self.name,
                family,
                100,
                details={"source": row["source"], "confidence": int(row["confidence"])},
            )
        ]


class ClamAVEngine:
    name = "clamav"

    def __init__(self, timeout: int = 30, database_dir: Path | None = None) -> None:
        self.timeout = max(1, timeout)
        self.clamd_command = shutil.which("clamdscan")
        self.clamscan_command = shutil.which("clamscan")
        self.command = self.clamd_command or self.clamscan_command
        configured = os.environ.get("CLAMAV_DATABASE_DIR")
        configured_dir = Path(configured) if configured else None
        if database_dir is not None:
            self.database_dir = database_dir
        elif configured_dir and configured_dir.exists():
            self.database_dir = configured_dir
        else:
            self.database_dir = database_dir or configured_dir

    def version(self) -> str:
        if not self.command:
            return EngineState.SCANNER_UNAVAILABLE.value
        try:
            result = subprocess.run(
                [self.command, "--version"], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=5, check=False,
                stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError):
            return EngineState.ENGINE_ERROR.value
        return (result.stdout or result.stderr).strip()[:160] or "unknown"

    def scan(self, path: Path, _sha256: str) -> list[Finding]:
        if not self.command:
            return [Finding(self.name, "ClamAV unavailable", 0, EngineState.SCANNER_UNAVAILABLE)]
        commands = [self.command]
        if self.command == self.clamd_command and self.clamscan_command:
            commands.append(self.clamscan_command)
        for index, command in enumerate(commands):
            try:
                arguments = [command]
                if command == self.clamscan_command and self.database_dir and self.database_dir.exists():
                    arguments.append(f"--database={self.database_dir}")
                arguments.extend(["--no-summary", str(path)])
                result = subprocess.run(
                    arguments, capture_output=True,
                    text=True, encoding="utf-8", errors="replace", timeout=self.timeout,
                    check=False, stdin=subprocess.DEVNULL,
                )
            except subprocess.TimeoutExpired:
                if index + 1 < len(commands):
                    continue
                return [Finding(self.name, "ClamAV timeout", 0, EngineState.SCAN_TIMEOUT)]
            except OSError as exc:
                if index + 1 < len(commands):
                    continue
                return [Finding(self.name, "ClamAV error", 0, EngineState.ENGINE_ERROR, {"error": str(exc)})]
            output = "\n".join(part for part in (result.stdout, result.stderr) if part)
            if result.returncode == 0:
                return [Finding(self.name, "no_detection", 0)]
            if result.returncode == 1:
                match = re.search(r":\s*(.+?)\s+FOUND\s*$", output, re.MULTILINE)
                return [Finding(self.name, match.group(1) if match else "ClamAV detection", 90)]
            if index + 1 == len(commands):
                return [Finding(self.name, "ClamAV scan error", 0, EngineState.ENGINE_ERROR, {"exit_code": result.returncode})]
        return [Finding(self.name, "ClamAV scan error", 0, EngineState.ENGINE_ERROR)]


class YaraEngine:
    name = "yara"

    def __init__(self, rules_dir: Path | None = None, timeout: int = 30) -> None:
        self.rules_dir = rules_dir or (get_hermes_home() / "security" / "feeds" / "yara")
        self.timeout = max(1, timeout)
        self._compiled = None
        self._compile_errors: list[str] = []
        self._files = sorted(self.rules_dir.glob("*.yar")) + sorted(self.rules_dir.glob("*.yara")) if self.rules_dir.exists() else []
        if importlib.util.find_spec("yara") is not None and self._files:
            self._compile()

    def _compile(self) -> None:
        yara = importlib.import_module("yara")

        sources: dict[str, str] = {}
        for path in self._files:
            try:
                source = path.read_text(encoding="utf-8")
                yara.compile(source=source)
                sources[path.stem] = source
            except (OSError, UnicodeError, Exception) as exc:
                self._compile_errors.append(f"{path.name}: {exc}")
        if not sources:
            return
        try:
            self._compiled = yara.compile(sources=sources)
        except Exception as exc:
            self._compile_errors.append(str(exc))

    def version(self) -> str:
        if self._compiled is None:
            return EngineState.SCANNER_UNAVAILABLE.value
        newest = max((path.stat().st_mtime_ns for path in self._files), default=0)
        return f"rules-{len(self._files)}-{newest}"

    def scan(self, path: Path, _sha256: str) -> list[Finding]:
        if self._compiled is None:
            details = {"compile_errors": self._compile_errors[:5]} if self._compile_errors else {}
            return [Finding(self.name, "YARA unavailable", 0, EngineState.SCANNER_UNAVAILABLE, details)]
        try:
            matches = self._compiled.match(str(path), timeout=self.timeout)
        except Exception as exc:
            return [Finding(self.name, "YARA scan error", 0, EngineState.ENGINE_ERROR, {"error": str(exc)})]
        findings: list[Finding] = []
        for match in matches:
            meta = dict(match.meta or {})
            tier = str(meta.get("hermes_tier", "core")).lower()
            score = 60 if tier == "extended" else 80
            findings.append(Finding(self.name, str(match.rule), score, details={"tier": tier, "tags": list(match.tags)}))
        return findings or [Finding(self.name, "no_detection", 0)]


class StaticHeuristicsEngine:
    name = "static_heuristics"
    executable_suffixes = {".bat", ".cmd", ".com", ".cpl", ".dll", ".exe", ".hta", ".js", ".jse", ".lnk", ".msi", ".ps1", ".scr", ".vbe", ".vbs", ".wsf"}
    document_suffixes = {".doc", ".docm", ".docx", ".pdf", ".ppt", ".pptm", ".pptx", ".rtf", ".txt", ".xls", ".xlsm", ".xlsx"}
    macro_suffixes = {".docm", ".dotm", ".pptm", ".ppam", ".xlsm", ".xlam"}

    def version(self) -> str:
        return "heuristics-1"

    def scan(
        self,
        path: Path,
        _sha256: str,
        *,
        original_path: Path | None = None,
    ) -> list[Finding]:
        heuristic_path = original_path or path
        suffixes = [item.lower() for item in heuristic_path.suffixes]
        findings: list[Finding] = []
        if len(suffixes) >= 2 and suffixes[-2] in self.document_suffixes and suffixes[-1] in self.executable_suffixes:
            findings.append(Finding(self.name, "executable_double_extension", 20))
        if suffixes and suffixes[-1] in self.macro_suffixes:
            findings.append(Finding(self.name, "macro_enabled_document", 20))
        path_parts = {part.lower() for part in heuristic_path.parts}
        if suffixes and suffixes[-1] in self.executable_suffixes and ({"temp", "tmp", "downloads"} & path_parts):
            findings.append(Finding(self.name, "executable_in_transient_location", 20))
        try:
            with path.open("rb") as handle:
                header = handle.read(4)
        except OSError as exc:
            return [Finding(self.name, "static_read_error", 0, EngineState.ENGINE_ERROR, {"error": str(exc)})]
        if header.startswith(b"MZ") and (not suffixes or suffixes[-1] not in self.executable_suffixes):
            findings.append(Finding(self.name, "pe_disguised_as_non_executable", 20))
        return findings


def engine_versions(engines: Iterable[Any]) -> dict[str, str]:
    return {str(engine.name): str(engine.version()) for engine in engines}


def versions_cache_key(versions: dict[str, str]) -> str:
    return json.dumps(versions, sort_keys=True, separators=(",", ":"))
