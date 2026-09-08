from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import quote


_METADATA_PATH = Path(__file__).with_name("distribution.json")
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)


@dataclass(frozen=True)
class RepositoryMetadata:
    slug: str
    web: str
    https: str
    ssh: str
    raw_base: str
    archive_base: str


@dataclass(frozen=True)
class UpstreamMetadata:
    slug: str
    version: str
    release_commit_sha: str
    snapshot_sha: str


@dataclass(frozen=True)
class PlatformMetadata:
    os: str
    architectures: tuple[str, ...]
    tier: int


@dataclass(frozen=True)
class ChannelMetadata:
    default: str
    supported: tuple[str, ...]


@dataclass(frozen=True)
class UpdateMetadata:
    branch: str
    allow_upstream_sync: bool


@dataclass(frozen=True)
class DistributionMetadata:
    schema_version: int
    id: str
    display_name: str
    version: str
    version_source: str
    repository: RepositoryMetadata
    upstream: UpstreamMetadata
    platform: PlatformMetadata
    channels: ChannelMetadata
    update: UpdateMetadata


def _require_mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"distribution field {field!r} must be an object")
    return value


def _require_string(mapping: dict[str, object], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"distribution field {field!r} must be a non-empty string")
    return value.strip()


@lru_cache(maxsize=1)
def load_distribution(path: Path | None = None) -> DistributionMetadata:
    metadata_path = path or _METADATA_PATH
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    root = _require_mapping(payload, "root")
    repository = _require_mapping(root.get("repository"), "repository")
    upstream = _require_mapping(root.get("upstream"), "upstream")
    platform = _require_mapping(root.get("platform"), "platform")
    channels = _require_mapping(root.get("channels"), "channels")
    update = _require_mapping(root.get("update"), "update")

    version = _require_string(root, "version")
    version_source = _require_string(root, "version_source")
    upstream_version = _require_string(upstream, "version")
    release_commit_sha = _require_string(upstream, "release_commit_sha").lower()
    snapshot_sha = _require_string(upstream, "snapshot_sha").lower()
    if version_source not in {"upstream", "downstream"}:
        raise ValueError("distribution.version_source must be 'upstream' or 'downstream'")
    if not _SEMVER.fullmatch(version):
        raise ValueError("distribution.version must be a semantic version")
    if not _SEMVER.fullmatch(upstream_version):
        raise ValueError("upstream.version must be a semantic version")
    if version_source == "upstream" and version != upstream_version:
        raise ValueError("distribution.version must match upstream.version")
    if not _FULL_SHA.fullmatch(release_commit_sha):
        raise ValueError("upstream.release_commit_sha must be a 40-character lowercase SHA")
    if not _FULL_SHA.fullmatch(snapshot_sha):
        raise ValueError("upstream.snapshot_sha must be a 40-character lowercase SHA")

    architectures = platform.get("architectures")
    if (
        not isinstance(architectures, list)
        or not architectures
        or not all(isinstance(item, str) and item for item in architectures)
    ):
        raise ValueError("platform.architectures must be a non-empty string list")
    supported = channels.get("supported")
    if (
        not isinstance(supported, list)
        or not supported
        or not all(isinstance(item, str) and item for item in supported)
    ):
        raise ValueError("channels.supported must be a non-empty string list")
    default_channel = _require_string(channels, "default")
    if default_channel not in supported:
        raise ValueError("channels.default must be present in channels.supported")
    allow_upstream_sync = update.get("allow_upstream_sync")
    if not isinstance(allow_upstream_sync, bool):
        raise ValueError("update.allow_upstream_sync must be a boolean")

    return DistributionMetadata(
        schema_version=int(root.get("schema_version", 0)),
        id=_require_string(root, "id"),
        display_name=_require_string(root, "display_name"),
        version=version,
        version_source=version_source,
        repository=RepositoryMetadata(
            slug=_require_string(repository, "slug"),
            web=_require_string(repository, "web"),
            https=_require_string(repository, "https"),
            ssh=_require_string(repository, "ssh"),
            raw_base=_require_string(repository, "raw_base").rstrip("/"),
            archive_base=_require_string(repository, "archive_base").rstrip("/"),
        ),
        upstream=UpstreamMetadata(
            slug=_require_string(upstream, "slug"),
            version=upstream_version,
            release_commit_sha=release_commit_sha,
            snapshot_sha=snapshot_sha,
        ),
        platform=PlatformMetadata(
            os=_require_string(platform, "os"),
            architectures=tuple(architectures),
            tier=int(platform.get("tier", 0)),
        ),
        channels=ChannelMetadata(
            default=default_channel,
            supported=tuple(supported),
        ),
        update=UpdateMetadata(
            branch=_require_string(update, "branch"),
            allow_upstream_sync=allow_upstream_sync,
        ),
    )


def install_script_url(ref: str, script_name: str) -> str:
    distribution = load_distribution()
    return (
        f"{distribution.repository.raw_base}/{quote(ref, safe='/')}/scripts/"
        f"{quote(script_name, safe='')}"
    )


def update_archive_url(branch: str) -> str:
    distribution = load_distribution()
    return (
        f"{distribution.repository.archive_base}/refs/heads/"
        f"{quote(branch, safe='/')}.zip"
    )


def resolve_downstream_sha(project_root: Path | None = None) -> str | None:
    root = project_root or _METADATA_PATH.parents[1]
    build_sha = root / ".hermes_build_sha"
    try:
        stamped = build_sha.read_text(encoding="utf-8").strip().lower()
        if _FULL_SHA.fullmatch(stamped):
            return stamped
    except OSError:
        pass
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = result.stdout.strip().lower()
    return sha if result.returncode == 0 and _FULL_SHA.fullmatch(sha) else None


def distribution_version_lines(
    *, downstream_sha: str | None = None
) -> tuple[str, str, str, str]:
    distribution = load_distribution()
    resolved_sha = downstream_sha or resolve_downstream_sha()
    revision = resolved_sha[:12] if resolved_sha else "unknown"
    return (
        f"Distribution: {distribution.display_name} {distribution.version}",
        f"Frozen upstream: {distribution.upstream.snapshot_sha[:12]}",
        f"Downstream revision: {revision}",
        f"Update channel: {distribution.channels.default}",
    )
