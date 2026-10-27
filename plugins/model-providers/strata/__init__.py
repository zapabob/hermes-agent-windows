"""Strata model provider profile for Hermes Agent.

Connects Hermes Agent directly to the local Strata inference engine running on
this PC (NVIDIA GeForce RTX 5060 Ti 16GB + 32GB RAM).
Native support for DeepSeek-V4.1-Flash MLA thinking mode, arbitrary GGUF ModelBundle,
and 32k-128k context windows without third-party workarounds.
"""

from __future__ import annotations

import logging
from typing import Any

from providers import register_provider
from providers.base import ProviderProfile

logger = logging.getLogger(__name__)


def _model_is_thinking(model: str | None) -> bool:
    """Check if the model family supports thinking/reasoning tags."""
    m = (model or "").strip().lower()
    return "deepseek" in m or "reasoner" in m or "qwq" in m or "r1" in m


class StrataProfile(ProviderProfile):
    """Strata native provider — local high-speed inference with MLA & Spin(8)."""

    def build_api_kwargs_extras(
        self,
        *,
        reasoning_config: dict | None = None,
        model: str | None = None,
        **context: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        extra_body: dict[str, Any] = {}
        top_level: dict[str, Any] = {}

        # Enable thinking mode for DeepSeek-V4.1-Flash or when requested
        if _model_is_thinking(model):
            enabled = True
            if isinstance(reasoning_config, dict) and reasoning_config.get("enabled") is False:
                enabled = False
            extra_body["thinking"] = {"type": "enabled" if enabled else "disabled"}
            if enabled and isinstance(reasoning_config, dict):
                effort = reasoning_config.get("effort") or "high"
                top_level["reasoning_effort"] = effort

        return extra_body, top_level


strata = StrataProfile(
    name="strata",
    aliases=("strata-local", "strata-engine", "deepseek-strata"),
    display_name="Strata Local (RTX 5060 Ti / 32GB)",
    description="Strata native inference engine on this PC — DeepSeek MLA, Spin(8) Triality, Arbitrary GGUF",
    signup_url="https://github.com/zapabob/Strata",
    env_vars=("STRATA_API_KEY", "STRATA_BASE_URL"),
    base_url="http://127.0.0.1:8080/v1",
    models_url="http://127.0.0.1:8080/v1/models",
    supports_vision=True,
    supports_vision_tool_messages=True,
    supports_prompt_cache_key=True,
    fallback_models=(
        "deepseek-v4.1-flash",
        "deepseek-v4.1-flash-uncensored",
        "qwen3.8-flash-next",
        "qwen3.6-35b-a3b",
        "strata-custom-gguf",
    ),
    default_aux_model="deepseek-v4.1-flash",
)

register_provider(strata)
