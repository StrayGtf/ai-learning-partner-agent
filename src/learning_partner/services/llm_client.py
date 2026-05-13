from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from learning_partner.config import LLMSettings, load_llm_settings_from_env


class LLMError(RuntimeError):
    pass


@dataclass
class LLMClient:
    settings: LLMSettings

    @property
    def enabled(self) -> bool:
        return self.settings.enabled

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1800,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        if not self.enabled:
            raise LLMError("LLM is not configured. Set LLM_API_KEY to enable model calls.")

        payload: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format

        body = json.dumps(payload).encode("utf-8")
        endpoint = f"{self.settings.base_url}/chat/completions"
        request = urllib.request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.settings.api_key}",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=self.settings.timeout_seconds) as response:
                content = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LLMError(f"HTTP {exc.code} from model API: {detail}") from exc
        except urllib.error.URLError as exc:
            raise LLMError(f"Network error while calling model API: {exc}") from exc

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Invalid JSON response from model API: {content[:200]}") from exc

        return _extract_message_text(parsed)

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> dict[str, Any]:
        text = self.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        parsed = _parse_json_loose(text)
        if parsed is not None:
            return parsed

        text = self.chat(messages, temperature=temperature, max_tokens=max_tokens, response_format=None)
        parsed = _parse_json_loose(text)
        if parsed is None:
            raise LLMError("Model returned content that is not valid JSON.")
        return parsed


def _extract_message_text(response_payload: dict[str, Any]) -> str:
    choices = response_payload.get("choices")
    if not choices or not isinstance(choices, list):
        raise LLMError("Model response does not contain choices.")
    message = choices[0].get("message", {})
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(parts).strip()
    return str(content)


def _parse_json_loose(raw_text: str) -> dict[str, Any] | None:
    text = raw_text.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
        return None
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    snippet = text[start : end + 1]
    try:
        parsed = json.loads(snippet)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        return None
    return None


def get_llm_client_from_env() -> LLMClient:
    return LLMClient(settings=load_llm_settings_from_env())
