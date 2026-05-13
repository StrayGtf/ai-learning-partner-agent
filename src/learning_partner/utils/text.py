from __future__ import annotations

import re


def slugify(text: str, fallback: str) -> str:
    normalized = text.strip().lower()
    normalized = re.sub(r"[^\w\s-]", "", normalized, flags=re.ASCII)
    normalized = re.sub(r"[\s_]+", "-", normalized, flags=re.ASCII).strip("-")
    if not normalized:
        return fallback
    return normalized


def truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "是", "需要"}


def code_flag_text(flag: bool) -> str:
    return "yes" if flag else "no"
