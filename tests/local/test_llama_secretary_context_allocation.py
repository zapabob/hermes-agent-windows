"""Run the launcher's actual allocation function without launching a server."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "scripts/windows/start-llama-secretary.ps1"


@pytest.mark.parametrize("parallel,per_slot,expected", [
    (1, 131072, 131072), (2, 131072, 262144), (2, 0, 131072),
    (0, 131072, None), (2, 32000, None), (64, 2147483647, None),
])
def test_preserve_context_per_slot_and_legacy_total(parallel: int, per_slot: int, expected: int | None):
    shell = shutil.which("powershell.exe") or shutil.which("pwsh")
    if not shell:
        pytest.skip("PowerShell is required for the native launcher contract")
    command = r"""
$ErrorActionPreference='Stop'
$ast=[System.Management.Automation.Language.Parser]::ParseFile($env:TEST_LAUNCHER,[ref]$null,[ref]$null)
$fn=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Resolve-LlamaContextAllocation'},$true)
if(-not $fn){throw 'Missing allocation function'}
Invoke-Expression $fn.Extent.Text
Resolve-LlamaContextAllocation -Context 131072 -Parallel PARALLEL -ContextPerSlot PER_SLOT | ConvertTo-Json -Compress
""".replace("PARALLEL", str(parallel)).replace("PER_SLOT", str(per_slot))
    result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", command],
                            env={**os.environ, "TEST_LAUNCHER": str(LAUNCHER)},
                            capture_output=True, encoding="utf-8", errors="replace", timeout=20,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if expected is None:
        assert result.returncode != 0
        assert not result.stdout.strip()
    else:
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == expected
