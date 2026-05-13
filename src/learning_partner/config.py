from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_ENV_LOADED = False


@dataclass
class LLMSettings:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: int

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.model)


def _normalize_base_url(value: str) -> str:
    base = value.strip() or "https://api.openai.com/v1"
    return base.rstrip("/")


def _load_env_file_if_exists(path: Path | None = None) -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    env_path = path or Path(".env")
    if not env_path.exists():
        _ENV_LOADED = True
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
    _ENV_LOADED = True


def load_llm_settings_from_env() -> LLMSettings:
    _load_env_file_if_exists()
    api_key = os.getenv("LLM_API_KEY", "").strip()
    base_url = _normalize_base_url(os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"))
    model = os.getenv("LLM_MODEL", "gpt-4o-mini").strip()
    timeout_raw = os.getenv("LLM_TIMEOUT_SECONDS", "90").strip()
    try:
        timeout = max(5, int(timeout_raw))
    except ValueError:
        timeout = 90
    return LLMSettings(api_key=api_key, base_url=base_url, model=model, timeout_seconds=timeout)
