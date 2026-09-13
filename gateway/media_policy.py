"""Shared config→env bridge for media-delivery policy.

``validate_media_delivery_path`` (gateway/platforms/base.py) reads its policy
from environment variables:

  - ``HERMES_MEDIA_DELIVERY_STRICT``    <- gateway.strict
  - ``HERMES_MEDIA_ALLOW_DIRS``         <- gateway.media_delivery_allow_dirs
  - ``HERMES_MEDIA_TRUST_RECENT_FILES`` <- gateway.trust_recent_files

Historically the config.yaml -> env translation ran ONLY in gateway startup
(gateway/run.py), so any process that delivers media without booting the
gateway — a manual ``hermes cron run`` in the CLI, ``hermes send``, a
standalone cron tick — filtered MEDIA paths under DIFFERENT policy than the
gateway's scheduled deliveries. In strict/allowlisted enterprise deployments
that divergence silently dropped attachments from manual cron runs while
scheduled runs delivered them (text is unaffected — only media goes through
path validation).

``apply_media_policy_env()`` is that same translation as a shared, idempotent
helper. Gateway startup calls it, and every standalone delivery entrypoint
calls it immediately before filtering media paths.

Precedence: an explicitly-set environment variable WINS over config.yaml.
This preserves both the operator contract (env overrides are how deployments
pin behavior) and gateway/run.py's historical shape (it only wrote the env
var when the config key was present; we additionally refuse to overwrite a
pre-existing env value so a shell-exported override survives).

Under a HERMES_HOME override (multiplexed turn) the validator helpers below
read the routed profile's config instead of the process-wide env bridge,
which still holds the launch profile's policy.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_FLAG_ENVS = (
    ("strict", "HERMES_MEDIA_DELIVERY_STRICT"),
    ("trust_recent_files", "HERMES_MEDIA_TRUST_RECENT_FILES"),
)
_ALLOW_DIRS_ENV = "HERMES_MEDIA_ALLOW_DIRS"
_TRUST_RECENT_SECONDS_ENV = "HERMES_MEDIA_TRUST_RECENT_SECONDS"
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _routed_gateway_cfg() -> Optional[Dict[str, Any]]:
    """``gateway`` section of the ROUTED profile when a HERMES_HOME override is active."""
    from hermes_constants import get_hermes_home_override

    if not get_hermes_home_override():
        return None
    try:
        from hermes_cli.config import load_config_readonly

        gateway_cfg = load_config_readonly().get("gateway")
    except Exception:
        return {}
    return gateway_cfg if isinstance(gateway_cfg, dict) else {}


def media_delivery_strict() -> bool:
    cfg = _routed_gateway_cfg()
    if cfg is not None:
        return bool(cfg.get("strict", False))
    return os.environ.get(_FLAG_ENVS[0][1], "0").strip().lower() in _TRUTHY


def media_delivery_allow_dirs() -> str:
    """Operator allowlist as the ``os.pathsep``-joined string the validator splits."""
    cfg = _routed_gateway_cfg()
    if cfg is not None:
        return _allow_dirs_str(cfg.get("media_delivery_allow_dirs"))
    return os.environ.get(_ALLOW_DIRS_ENV, "")


def media_delivery_trust_recent() -> bool:
    cfg = _routed_gateway_cfg()
    if cfg is not None:
        return bool(cfg.get("trust_recent_files", True))
    return os.environ.get(_FLAG_ENVS[1][1], "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
        "",
    )


def media_delivery_trust_recent_seconds() -> str:
    """Raw recency window (``""`` = validator default); the caller parses/floors it."""
    cfg = _routed_gateway_cfg()
    if cfg is not None:
        raw = cfg.get("trust_recent_files_seconds")
        return "" if raw is None else str(raw)
    return os.environ.get(_TRUST_RECENT_SECONDS_ENV, "")


def _load_gateway_cfg(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if config is None:
        try:
            from hermes_cli.config import load_config

            config = load_config() or {}
        except Exception:
            return {}
    gateway_cfg = config.get("gateway", {})
    return gateway_cfg if isinstance(gateway_cfg, dict) else {}


def _set_env_default(env: str, value: str) -> None:
    """Set ``env`` only when unset/empty and ``value`` is non-empty (env wins)."""
    if value and not os.environ.get(env):
        os.environ[env] = value


def _allow_dirs_str(allow_dirs: Any) -> str:
    if isinstance(allow_dirs, (list, tuple)):
        return os.pathsep.join(str(p) for p in allow_dirs if p)
    return allow_dirs if isinstance(allow_dirs, str) else ""


def apply_media_policy_env(config: Optional[Dict[str, Any]] = None) -> None:
    """Bridge gateway media-policy settings from config.yaml into the env.

    Idempotent and env-wins: a variable already present in the environment is
    never overwritten, so gateway startup (which runs this same helper) and
    operator shell exports keep precedence. Never raises — a policy-bridge
    failure must not break delivery; the validator falls back to its
    defaults exactly as before.
    """
    try:
        gateway_cfg = _load_gateway_cfg(config)
        if not gateway_cfg:
            return

        for key, env in _FLAG_ENVS:
            flag = gateway_cfg.get(key)
            if flag is not None:
                _set_env_default(env, "1" if flag else "0")

        allow_dirs = gateway_cfg.get("media_delivery_allow_dirs")
        if allow_dirs:
            _set_env_default(_ALLOW_DIRS_ENV, _allow_dirs_str(allow_dirs))
    except Exception:  # noqa: BLE001 - policy bridge must never break delivery
        logger.debug("apply_media_policy_env failed", exc_info=True)
