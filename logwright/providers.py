from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


def default_openai_model() -> str:
    return os.environ.get("LOGWRIGHT_OPENAI_MODEL", "gpt-5.4-mini")


def default_anthropic_model() -> str:
    return os.environ.get("LOGWRIGHT_ANTHROPIC_MODEL", "claude-sonnet-4-6")


def default_gemini_model() -> str:
    return os.environ.get("LOGWRIGHT_GEMINI_MODEL", "gemini-2.5-flash")


class ProviderError(RuntimeError):
    pass


@dataclass
class ProviderResponse:
    data: dict[str, Any]
    input_tokens: int | None
    output_tokens: int | None


class BaseProvider:
    name: str

    def __init__(self, model: str) -> None:
        self.model = model

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_name: str,
        schema: dict[str, Any],
        max_output_tokens: int = 900,
        ) -> ProviderResponse:
        raise NotImplementedError


def _json_request(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    retryable_statuses = {408, 429, 500, 502, 503, 504}
    last_error: Exception | None = None
    for attempt in range(3):
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            message = exc.read().decode("utf-8", "ignore")
            compact = _compact_error_message(message)
            last_error = ProviderError(f"HTTP {exc.code}: {compact}")
            if exc.code not in retryable_statuses or attempt == 2:
                raise last_error from exc
        except urllib.error.URLError as exc:
            last_error = ProviderError(str(exc))
            if attempt == 2:
                raise last_error from exc
        time.sleep(0.6 * (attempt + 1))
    if last_error:
        raise last_error
    raise ProviderError("provider request failed")


def _compact_error_message(message: str) -> str:
    stripped = message.strip()
    if not stripped:
        return "empty error response"
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        single_line = " ".join(stripped.split())
        return single_line[:240]

    for path in (
        ("error", "message"),
        ("message",),
        ("error", "status"),
    ):
        current: Any = payload
        for key in path:
            if not isinstance(current, dict) or key not in current:
                current = None
                break
            current = current[key]
        if isinstance(current, str) and current.strip():
            return current.strip()
    compact = " ".join(stripped.split())
    return compact[:240]


def _extract_json_text(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise ProviderError("provider returned empty text")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ProviderError("provider did not return valid JSON")
        return json.loads(text[start : end + 1])


class OpenAIProvider(BaseProvider):
    name = "openai"

    def __init__(self, model: str | None = None) -> None:
        resolved_model = model or default_openai_model()
        super().__init__(model=resolved_model)
        self.api_key = os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ProviderError("OPENAI_API_KEY is not set")

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_name: str,
        schema: dict[str, Any],
        max_output_tokens: int = 900,
    ) -> ProviderResponse:
        payload = {
            "model": self.model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_output_tokens": max_output_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": schema,
                    "strict": True,
                }
            },
        }
        raw = _json_request(
            "https://api.openai.com/v1/responses",
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            payload,
        )
        for item in raw.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "refusal":
                    raise ProviderError(content.get("refusal", "model refused request"))
                if content.get("type") == "output_text":
                    data = _extract_json_text(content.get("text", ""))
                    usage = raw.get("usage", {})
                    return ProviderResponse(
                        data=data,
                        input_tokens=usage.get("input_tokens"),
                        output_tokens=usage.get("output_tokens"),
                    )
        raise ProviderError("OpenAI response did not contain output_text")


class AnthropicProvider(BaseProvider):
    name = "anthropic"

    def __init__(self, model: str | None = None) -> None:
        resolved_model = model or default_anthropic_model()
        super().__init__(model=resolved_model)
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ProviderError("ANTHROPIC_API_KEY is not set")

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_name: str,
        schema: dict[str, Any],
        max_output_tokens: int = 900,
    ) -> ProviderResponse:
        schema_text = json.dumps(schema, sort_keys=True)
        prompt = (
            f"{user_prompt}\n\n"
            "Return JSON only. Do not use markdown fences.\n"
            f"Schema name: {schema_name}\n"
            f"Schema: {schema_text}\n"
        )
        payload = {
            "model": self.model,
            "max_tokens": max_output_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": prompt}],
        }
        raw = _json_request(
            "https://api.anthropic.com/v1/messages",
            {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            payload,
        )
        for content in raw.get("content", []):
            if content.get("type") == "text":
                data = _extract_json_text(content.get("text", ""))
                usage = raw.get("usage", {})
                return ProviderResponse(
                    data=data,
                    input_tokens=usage.get("input_tokens"),
                    output_tokens=usage.get("output_tokens"),
        )
        raise ProviderError("Anthropic response did not contain text content")


class GeminiProvider(BaseProvider):
    name = "gemini"

    def __init__(self, model: str | None = None) -> None:
        resolved_model = model or default_gemini_model()
        super().__init__(model=resolved_model)
        self.api_key = os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ProviderError("GEMINI_API_KEY is not set")

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_name: str,
        schema: dict[str, Any],
        max_output_tokens: int = 900,
    ) -> ProviderResponse:
        del schema_name
        payload = {
            "system_instruction": {
                "parts": [
                    {
                        "text": (
                            f"{system_prompt}\n\n"
                            "Return JSON only. Do not use markdown fences."
                        )
                    }
                ]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_prompt}],
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": schema,
                "maxOutputTokens": max_output_tokens,
                "temperature": 0,
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        model_name = urllib.parse.quote(self.model, safe="")
        raw = _json_request(
            (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model_name}:generateContent"
            ),
            {
                "x-goog-api-key": self.api_key,
                "Content-Type": "application/json",
            },
            payload,
        )
        prompt_feedback = raw.get("promptFeedback", {})
        if prompt_feedback.get("blockReason"):
            raise ProviderError(
                f"Gemini blocked the request: {prompt_feedback['blockReason']}"
            )
        for candidate in raw.get("candidates", []):
            content = candidate.get("content", {})
            for part in content.get("parts", []):
                text = part.get("text")
                if text:
                    data = _extract_json_text(text)
                    usage = raw.get("usageMetadata", {})
                    return ProviderResponse(
                        data=data,
                        input_tokens=usage.get("promptTokenCount"),
                        output_tokens=usage.get("candidatesTokenCount"),
                    )
        raise ProviderError("Gemini response did not contain JSON text")


def resolve_provider(provider_name: str, model: str | None = None) -> BaseProvider | None:
    if provider_name == "heuristic":
        return None
    if provider_name == "auto":
        if os.environ.get("ANTHROPIC_API_KEY"):
            return AnthropicProvider(model or default_anthropic_model())
        if os.environ.get("OPENAI_API_KEY"):
            return OpenAIProvider(model or default_openai_model())
        if os.environ.get("GEMINI_API_KEY"):
            return GeminiProvider(model or default_gemini_model())
        return None
    if provider_name == "anthropic":
        return AnthropicProvider(model or default_anthropic_model())
    if provider_name == "openai":
        return OpenAIProvider(model or default_openai_model())
    if provider_name == "gemini":
        return GeminiProvider(model or default_gemini_model())
    raise ProviderError(f"unknown provider: {provider_name}")
