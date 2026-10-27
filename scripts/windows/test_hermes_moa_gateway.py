from __future__ import annotations

import json
import logging
import sys
import urllib.error
import urllib.request
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
LOG = logging.getLogger("moa-gateway-probe")


def load_api_key(path: Path) -> str:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "API_SERVER_KEY":
            return value.strip().strip('"').strip("'")
    raise RuntimeError("API_SERVER_KEY is not configured")


def main() -> int:
    api_key = load_api_key(Path.home() / ".hermes" / ".env")
    payload = {
        "model": "hermes-agent",
        "messages": [
            {
                "role": "user",
                "content": (
                    "Local integration probe only. Reply with exactly "
                    "HERMES_MOA_OK and no other text. Do not call tools."
                ),
            }
        ],
        "stream": False,
    }
    request = urllib.request.Request(
        "http://127.0.0.1:8642/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        LOG.error("MoA gateway probe failed: %s", exc)
        return 1

    content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
    if "HERMES_MOA_OK" not in content:
        LOG.error("MoA gateway returned an unexpected response")
        return 1
    LOG.info("HERMES_MOA_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
