from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/fork-cicd.yml"
SCHEDULED = ROOT / ".github/workflows/windows-full-qualification.yml"
RELEASE = ROOT / ".github/workflows/windows-release.yml"
SANDBOX_STAGE2 = ROOT / "scripts/sandbox/stage2-run.sh"
DEV_SANDBOX = ROOT / "scripts/dev-sandbox.sh"
CI = ROOT / ".github/workflows/ci.yaml"
DETECT_ACTION = ROOT / ".github/actions/detect-changes/action.yml"


def _workflow(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _step_commands(job: dict) -> str:
    return "\n".join(str(step.get("run", "")) for step in job.get("steps", []))


def test_required_tier_one_jobs_exist() -> None:
    jobs = _workflow(WORKFLOW)["jobs"]
    assert set(jobs) == {
        "downstream-policy",
        "windows-native-python",
        "windows-native-desktop",
        "windows-watchdog-go",
        "upstream-api-compat",
        "windows-regression",
        "security-locks",
        "pilot-checkpoint-api",
    }


def test_policy_lane_fetches_frozen_upstream_history() -> None:
    job = _workflow(WORKFLOW)["jobs"]["downstream-policy"]
    checkout = job["steps"][0]
    commands = _step_commands(job)
    assert checkout["with"]["fetch-depth"] == 0
    assert ".codex/UPSTREAM_SNAPSHOT.json" in commands
    assert "https://github.com/NousResearch/hermes-agent.git" in commands
    assert "git fetch --no-tags" in commands


def test_all_tier_one_jobs_run_natively_on_windows() -> None:
    workflow = _workflow(WORKFLOW)
    jobs = workflow["jobs"]
    assert workflow["defaults"]["run"]["shell"] == "pwsh"
    assert all(job["runs-on"] == "windows-latest" for job in jobs.values())
    commands = "\n".join(_step_commands(job) for job in jobs.values())
    assert "/dev/null" not in commands
    assert "$RUNNER_TEMP/" not in commands
    assert "test ! -d" not in commands
    assert "test -d" not in commands


def test_native_jobs_cover_windows_contracts() -> None:
    jobs = _workflow(WORKFLOW)["jobs"]
    assert jobs["windows-native-python"]["runs-on"] == "windows-latest"
    assert jobs["windows-native-desktop"]["runs-on"] == "windows-latest"
    assert jobs["windows-watchdog-go"]["runs-on"] == "windows-latest"
    assert "tests/downstream/test_windows_contracts.py" in _step_commands(
        jobs["windows-native-python"]
    )
    assert "tests/gateway/test_async_session_db.py" in _step_commands(
        jobs["windows-native-python"]
    )
    assert "go test ./..." in _step_commands(jobs["windows-watchdog-go"])
    assert "GOOS=windows" not in _step_commands(jobs["windows-watchdog-go"])


def test_desktop_lane_derives_metadata_and_builds() -> None:
    job = _workflow(WORKFLOW)["jobs"]["windows-native-desktop"]
    commands = _step_commands(job)
    assert "package.engines.node" in commands
    assert "package-lock.json" in commands
    assert "npm ci" in commands
    assert "run typecheck" in commands
    assert "run lint" in commands
    assert "run test:desktop:platforms" in commands
    assert "run build" in commands


def test_security_lane_checks_all_lock_ecosystems() -> None:
    commands = _step_commands(_workflow(WORKFLOW)["jobs"]["security-locks"])
    assert "uv lock --check" in commands
    assert "uv export --frozen --all-extras --no-dev --no-emit-project" in commands
    assert "Join-Path $env:RUNNER_TEMP 'hermes-audit-requirements.txt'" in commands
    assert "pip-audit==2.10.1 pip-audit --require-hashes --disable-pip --requirement" in commands
    assert "npm audit" in commands
    assert "go mod verify" in commands


def test_scheduled_full_windows_qualification_exists() -> None:
    workflow = _workflow(SCHEDULED)
    jobs = workflow["jobs"]
    assert set(jobs) == {"python-full", "desktop-full", "watchdog-live"}
    assert all(job["runs-on"] == "windows-latest" for job in jobs.values())
    assert "scripts/run_tests_parallel.py" in _step_commands(jobs["python-full"])


def test_external_actions_are_commit_pinned() -> None:
    action = re.compile(r"^([^./][^@]*)@([0-9a-f]{40})$")
    for path in (WORKFLOW, SCHEDULED, RELEASE):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped.startswith("uses:"):
                continue
            reference = stripped.removeprefix("uses:").split("#", 1)[0].strip()
            assert action.match(reference), (
                f"unpinned action in {path.name}: {reference}"
            )


def test_release_builds_never_implicitly_publish_from_electron_builder() -> None:
    commands = _step_commands(
        _workflow(RELEASE)["jobs"]["build-qualify-release"]
    )

    builder_commands = [
        line.strip()
        for line in commands.splitlines()
        if "run builder --" in line or "run-electron-builder.mjs" in line
    ]
    assert len(builder_commands) == 2
    assert all("--publish never" in command for command in builder_commands)
    assert "$env:GITHUB_WORKSPACE" in builder_commands[1]


def test_sandbox_node_trusts_the_local_mitm_ca() -> None:
    stage2 = SANDBOX_STAGE2.read_text(encoding="utf-8")

    assert "--setenv NODE_EXTRA_CA_CERTS /work/certs/ca.pem" in stage2
    assert "--setenv NODE_EXTRA_CA_CERTS /work/certs/real-ca.pem" not in stage2
    assert "--setenv CURL_CA_BUNDLE /work/certs/ca-bundle.pem" in stage2
    assert "--setenv SSL_CERT_FILE /work/certs/ca-bundle.pem" in stage2
    assert "--setenv GIT_SSL_CAINFO /work/certs/ca-bundle.pem" in stage2
    assert "python3 /work/proxy.py /work/http /work/certs /work/certs/real-ca.pem" in stage2


def test_sandbox_does_not_export_hidden_fhs_node_headers() -> None:
    sandbox = DEV_SANDBOX.read_text(encoding="utf-8")

    assert '/nix/store/*) NODE_DIR="$node_dir_candidate"' in sandbox
    assert 'NODE_DIR="$(dirname "$(dirname "$(command -v node)")")"' not in sandbox


def test_ci_detect_step_passes_only_declared_action_inputs() -> None:
    workflow = _workflow(CI)
    action = _workflow(DETECT_ACTION)
    detect_step = next(
        step
        for step in workflow["jobs"]["detect"]["steps"]
        if step.get("uses") == "./.github/actions/detect-changes"
    )
    passed_inputs = set(detect_step.get("with", {}))
    assert passed_inputs == {"github-token"}
    assert passed_inputs <= set(action.get("inputs", {}))
