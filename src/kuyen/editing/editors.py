"""Editor ports: who interprets an Antü when the knowledge is not in a document (§6).

The port is tiny on purpose. `GraphEditorPort.interpret(request) -> str` returns the raw
proposal text; KÜYEN parses, validates, applies and versions it. Nothing in this module
can write to the canonical store, and no implementation is required to build a memory.

Two implementations ship:

* `OpenAICompatibleGraphEditor` — an OpenAI-compatible chat-completions endpoint, using
  only the standard library (`urllib`), configured explicitly through a dataclass whose
  credential is read from an environment variable at call time and never logged.
* `RecordedGraphEditor` — replay of an already recorded proposal, keyed by the hash of the
  request. It is what makes an edit reproducible without a model.

There is no fallback between editors: if the configured editor fails, the edit fails.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable

from ..canonical import canonical_json, sha256_text
from ..errors import KuyenError
from .prompt import GraphEditRequest


class EditorError(KuyenError):
    """The configured graph editor could not produce a proposal."""


class EditorConfigurationError(EditorError):
    """The editor configuration is incomplete or invalid (never a silent fallback)."""


@runtime_checkable
class GraphEditorPort(Protocol):
    """A semantic graph editor: instruction + context in, raw proposal out."""

    name: str

    def interpret(self, request: GraphEditRequest) -> str:  # pragma: no cover - protocol
        ...

    def metadata(self) -> dict[str, Any]:  # pragma: no cover - protocol
        ...


@dataclass(frozen=True)
class EditorConfig:
    """Explicit editor configuration. No credential is ever stored in it."""

    provider: str = "openai-compatible"
    model: str = ""
    endpoint: str = "https://api.openai.com/v1"
    api_key_env: str = "KUYEN_EDITOR_API_KEY"
    api_key_header: str = "Authorization"
    api_key_prefix: str = "Bearer "
    temperature: float = 0.0
    max_tokens: int = 2048
    timeout_s: float = 60.0
    json_mode: bool = True

    def __post_init__(self) -> None:
        if self.provider not in ("openai-compatible",):
            raise EditorConfigurationError(
                f"unsupported editor provider {self.provider!r}; no fallback is attempted",
                details={"code": "EDITOR_PROVIDER_UNSUPPORTED", "provider": self.provider})
        if not str(self.model).strip():
            raise EditorConfigurationError(
                "the editor requires an explicit model (no default, no fallback)",
                details={"code": "EDITOR_MODEL_REQUIRED"})

    @classmethod
    def from_env(cls, prefix: str = "KUYEN_EDITOR") -> "EditorConfig":
        """Read the configuration from explicit environment variables."""
        def value(key: str, default: str = "") -> str:
            return os.environ.get(f"{prefix}_{key}", default) or default

        return cls(
            provider=value("PROVIDER", "openai-compatible"),
            model=value("MODEL"),
            endpoint=value("ENDPOINT", "https://api.openai.com/v1"),
            api_key_env=value("API_KEY_ENV", "KUYEN_EDITOR_API_KEY"),
            temperature=float(value("TEMPERATURE", "0") or 0),
            max_tokens=int(value("MAX_TOKENS", "2048") or 2048),
            timeout_s=float(value("TIMEOUT_S", "60") or 60),
            json_mode=(value("JSON_MODE", "true").lower() not in ("0", "false", "no")),
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EditorConfig":
        known = {field.name for field in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        unknown = sorted(set(value) - known)
        if unknown:
            raise EditorConfigurationError(
                f"unknown editor configuration keys: {unknown}",
                details={"code": "EDITOR_CONFIG_UNKNOWN_FIELD", "fields": unknown})
        payload = {key: value[key] for key in value if key in known}
        if "temperature" in payload:
            payload["temperature"] = float(payload["temperature"])
        if "max_tokens" in payload:
            payload["max_tokens"] = int(payload["max_tokens"])
        if "timeout_s" in payload:
            payload["timeout_s"] = float(payload["timeout_s"])
        return cls(**payload)

    def public_dict(self) -> dict[str, Any]:
        """Never includes the resolved credential."""
        return {"provider": self.provider, "model": self.model, "endpoint": self.endpoint,
                "api_key_env": self.api_key_env, "temperature": self.temperature,
                "max_tokens": self.max_tokens, "timeout_s": self.timeout_s,
                "json_mode": self.json_mode}

    def resolve_key(self) -> str | None:
        key = os.environ.get(self.api_key_env, "").strip()
        return key or None



@dataclass
class EditorUsage:
    """What a call consumed, only when the provider reports it."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens}


@dataclass
class OpenAICompatibleGraphEditor:
    """`/chat/completions` on an OpenAI-compatible endpoint, standard library only."""

    config: EditorConfig
    name: str = "openai-compatible"
    last_usage: EditorUsage = field(default_factory=EditorUsage)
    calls: int = 0

    def metadata(self) -> dict[str, Any]:
        return {"provider": self.config.provider, "model": self.config.model,
                "endpoint": self.config.endpoint, "transport": "urllib",
                "temperature": self.config.temperature, "max_tokens": self.config.max_tokens}

    def _payload(self, request: GraphEditRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": request.messages(),
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if self.config.json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def interpret(self, request: GraphEditRequest) -> str:
        key = self.config.resolve_key()
        if not key:
            raise EditorConfigurationError(
                f"the editor credential is not available in {self.config.api_key_env}",
                details={"code": "EDITOR_CREDENTIAL_UNAVAILABLE",
                         "env": self.config.api_key_env})
        url = self.config.endpoint.rstrip("/") + "/chat/completions"
        body = json.dumps(self._payload(request), ensure_ascii=False).encode("utf-8")
        http_request = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type": "application/json",
            self.config.api_key_header: f"{self.config.api_key_prefix}{key}".strip(),
        })
        self.calls += 1
        try:
            with urllib.request.urlopen(http_request, timeout=self.config.timeout_s) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise EditorError(
                f"the editor endpoint returned HTTP {exc.code}",
                details={"code": "EDITOR_HTTP_ERROR", "status": exc.code, "detail": detail}) from exc
        except urllib.error.URLError as exc:
            raise EditorError(
                f"the editor endpoint is unreachable: {exc.reason}",
                details={"code": "EDITOR_UNREACHABLE"}) from exc
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EditorError("the editor endpoint did not return JSON",
                              details={"code": "EDITOR_RESPONSE_NOT_JSON"}) from exc
        usage = data.get("usage") if isinstance(data, Mapping) else None
        if isinstance(usage, Mapping):
            self.last_usage = EditorUsage(
                prompt_tokens=usage.get("prompt_tokens") if isinstance(usage.get("prompt_tokens"), int) else None,
                completion_tokens=(usage.get("completion_tokens")
                                   if isinstance(usage.get("completion_tokens"), int) else None))
        choices = data.get("choices") if isinstance(data, Mapping) else None
        if not isinstance(choices, list) or not choices:
            raise EditorError("the editor response has no choices",
                              details={"code": "EDITOR_RESPONSE_EMPTY"})
        message = choices[0].get("message") if isinstance(choices[0], Mapping) else None
        content = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(content, str) or not content.strip():
            raise EditorError("the editor response has no content",
                              details={"code": "EDITOR_RESPONSE_EMPTY"})
        return content


@dataclass
class RecordedGraphEditor:
    """Deterministic replay of recorded proposals, keyed by `prompt_sha256`.

    This is what lets an edit be reproduced, audited or demonstrated without calling a
    model. A request without a recording is an error, never a fabricated answer.
    """

    responses: Mapping[str, str]
    name: str = "recorded"

    def metadata(self) -> dict[str, Any]:
        return {"provider": "recorded", "model": "recorded", "recordings": len(self.responses)}

    def interpret(self, request: GraphEditRequest) -> str:
        payload = self.responses.get(request.prompt_sha256)
        if payload is None:
            raise EditorError(
                "no recorded proposal matches this request",
                details={"code": "EDITOR_RECORDING_NOT_FOUND",
                         "prompt_sha256": request.prompt_sha256})
        return payload


def editor_prompt_key(request: GraphEditRequest) -> str:
    """The stable key used to record and replay one interpretation."""
    return sha256_text(canonical_json({"prompt": request.prompt_sha256,
                                       "antu_id": request.antu_id}))[:32]
