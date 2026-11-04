"""VLM provider configuration for the KÜYEN-managed OpenViking instance.

Scope: this module **configures** the model provider that OpenViking uses to run its own
semantic generation (L0/L1). It performs no inference and no extraction: KÜYEN never calls
a model provider here. The only HTTP conversation that happens is between OpenViking and
the provider it was configured with.

Verified against the OpenViking build pinned by KÜYEN (0.5.0):

* the `vlm` block of `ov.conf` is `openviking_cli.utils.config.vlm_config.VLMConfig`, with
  `provider`, `model`, `api_key`, `api_base`, `temperature`, `max_retries`, `timeout`;
* OpenViking applies `os.path.expandvars()` to the raw config text before parsing it
  (`openviking_cli/utils/config/config_loader.py`, `load_json_config`), so `"${VAR}"` is
  resolved from the **server process** environment. Unset variables are left untouched,
  which is why the secret is verified to exist before the process starts;
* `OPENVIKING_VLM_API_KEY` exists in `consts.py` of that same build but is never read, so
  it is **not** used as a fallback here;
* the config file is located through `OPENVIKING_CONFIG_FILE`.

Security contract of this module:

* the credential is held in a private field, never rendered by `repr()` or `str()`, never
  serialized, never logged and never written to `ov.conf`;
* `ov.conf` carries a `${...}` reference and the value travels only in the environment of
  the child process (`start_isolated_server`), never in `os.environ` of the caller;
* the OpenAI provider key and the OpenViking HTTP authentication key are different secrets
  and are never exchanged (see `credentials.py` and `adapters/openviking.py`).
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import KuyenError

OPENAI_API_BASE = "https://api.openai.com/v1"

#: Providers that may be configured. A local OpenAI-compatible endpoint is deliberately
#: **not** supported yet (KUYEN_OPENVIKING_VLM_CONFIGURATION_05, §10).
SUPPORTED_PROVIDERS = ("openai",)

#: Name of the variable that carries the provider key into the OpenViking process. It is
#: referenced from `ov.conf` as `"${KUYEN_VLM_API_KEY}"`; the value itself never touches
#: the file.
SECRET_ENV_VAR = "KUYEN_VLM_API_KEY"

#: Second variable, only used when the embedding provider is *not* the inference provider.
#: KÜYEN's single inference configuration covers the VLM and the Antü editor; embeddings are
#: a different model with its own provider (DeepSeek, for instance, publishes no embedding
#: endpoint), so they may keep their own base URL and credential. It is still one
#: configuration object, not a second credential system.
EMBEDDING_SECRET_ENV_VAR = "KUYEN_EMBEDDING_API_KEY"

#: Environment variable KÜYEN reads when the caller does not pass the key explicitly.
DEFAULT_API_KEY_ENV = "OPENAI_API_KEY"
#: Explicit default for the embedding provider of an isolated instance.
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
#: Declared dimension of the known embedding models. The vector store fixes the dimension
#: when the collection is created, so an undeclared dimension is not harmless: the store
#: is built with 2048 and every later embedding fails with "Dense vector dimension
#: mismatch: expected 2048, got 1536" (measured, KUYEN_DISTRIBUTED_ANTU_12).
EMBEDDING_DIMENSIONS = {"text-embedding-3-small": 1536, "text-embedding-3-large": 3072,
                       "text-embedding-ada-002": 1536}


class VlmConfigurationError(KuyenError):
    """The VLM provider configuration is incomplete or unusable.

    The message names the field or environment variable that needs configuration and
    never contains the credential.
    """

    code = "VLM_CONFIGURATION_INVALID"


@dataclass(frozen=True)
class VlmProviderConfig:
    """How OpenViking reaches its VLM provider.

    `model` is mandatory and has no default: KÜYEN never fixes a model, and an implicit
    fallback would make the configuration unreproducible.

    The credential may be given directly (`api_key=...`) or resolved from the caller's
    environment through `api_key_env`. Either way it is stored in a private field and
    `repr()`/`str()` only report whether it is configured.
    """

    model: str
    provider: str = "openai"
    api_base: str = OPENAI_API_BASE
    api_key_env: str = DEFAULT_API_KEY_ENV
    timeout_s: float = 60.0
    max_retries: int = 0
    temperature: float | None = None
    # An isolated instance that cannot embed cannot ingest anything: without this block
    # OpenViking falls back to a local embedder that is not installed, and every MAPU fails
    # with `Local embedding is enabled but 'llama-cpp-python' is not installed` (measured in
    # KUYEN_DISTRIBUTED_ANTU_12). The provider is the same OpenAI-compatible endpoint and the
    # same credential reference as the VLM; the model is explicit, never guessed.
    embedding_model: str | None = DEFAULT_EMBEDDING_MODEL
    embedding_dimension: int | None = None
    #: Embedding provider, when it is not the inference provider. Both are optional: with
    #: neither, the embedding block reuses `api_base`/`api_key_env` (the previous behaviour).
    embedding_api_base: str | None = None
    embedding_api_key_env: str | None = None
    _api_key: str | None = field(default=None, repr=False, compare=False)

    def __init__(self, model: str, provider: str = "openai", api_base: str = OPENAI_API_BASE,
                 api_key_env: str = DEFAULT_API_KEY_ENV, timeout_s: float = 60.0,
                 max_retries: int = 0, temperature: float | None = None,
                 api_key: str | None = None,
                 embedding_model: str | None = DEFAULT_EMBEDDING_MODEL,
                 embedding_dimension: int | None = None,
                 embedding_api_base: str | None = None,
                 embedding_api_key_env: str | None = None) -> None:
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "api_base", api_base)
        object.__setattr__(self, "api_key_env", api_key_env)
        object.__setattr__(self, "timeout_s", timeout_s)
        object.__setattr__(self, "max_retries", max_retries)
        object.__setattr__(self, "temperature", temperature)
        object.__setattr__(self, "embedding_model", embedding_model)
        object.__setattr__(self, "embedding_dimension", embedding_dimension)
        object.__setattr__(self, "embedding_api_base", embedding_api_base)
        object.__setattr__(self, "embedding_api_key_env", embedding_api_key_env)
        object.__setattr__(self, "_api_key", api_key or None)

    @property
    def credential_configured(self) -> bool:
        return bool(self._api_key or os.environ.get(self.api_key_env or ""))

    # -- construction -------------------------------------------------------
    @classmethod
    def from_environment(cls, *, model: str, api_key_env: str = DEFAULT_API_KEY_ENV,
                         **overrides: Any) -> "VlmProviderConfig":
        """Build a configuration whose key is resolved from `api_key_env` at use time."""
        return cls(model=model, api_key_env=api_key_env, **overrides)

    def rotated(self, api_key: str) -> "VlmProviderConfig":
        """Return a copy that carries a new credential (never mutates in place)."""
        return VlmProviderConfig(
            model=self.model, provider=self.provider, api_base=self.api_base,
            api_key_env=self.api_key_env, timeout_s=self.timeout_s,
            max_retries=self.max_retries, temperature=self.temperature, api_key=api_key,
            embedding_model=self.embedding_model, embedding_dimension=self.embedding_dimension,
            embedding_api_base=self.embedding_api_base,
            embedding_api_key_env=self.embedding_api_key_env)

    # -- secret handling ----------------------------------------------------
    def secret_source(self) -> str:
        """Where the credential comes from, without revealing it."""
        if self._api_key:
            return "argument"
        if self.api_key_env and os.environ.get(self.api_key_env):
            return f"environment:{self.api_key_env}"
        return "missing"

    def resolve_secret(self) -> str:
        """Return the credential for the child process environment.

        Never log, print or serialize the returned value. Raises
        `VlmConfigurationError` naming the variable that must be configured.
        """
        if self._api_key:
            return self._api_key
        if not self.api_key_env:
            raise VlmConfigurationError(
                "VLM_CONFIGURATION_INVALID: no api_key was given and no api_key_env is set",
                details={"field": "api_key", "status": "VLM_CONFIGURATION_INVALID"})
        value = os.environ.get(self.api_key_env)
        if not value:
            raise VlmConfigurationError(
                f"VLM_CONFIGURATION_INVALID: set the environment variable {self.api_key_env} "
                "or pass api_key=... to VlmProviderConfig",
                details={"missing": self.api_key_env, "status": "VLM_CONFIGURATION_INVALID"})
        return value

    def credential_fingerprint(self) -> str:
        """Non-reversible marker used only to decide whether a restart is required."""
        try:
            secret = self.resolve_secret()
        except VlmConfigurationError:
            return "missing"
        return "sha256:" + hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]

    # -- embedding credential (only when it differs from the inference one) --
    def embedding_secret_source(self) -> str:
        """Where the embedding credential comes from, without revealing it."""
        if not self.embedding_api_key_env:
            return self.secret_source()
        return (f"environment:{self.embedding_api_key_env}"
                if os.environ.get(self.embedding_api_key_env) else "missing")

    def resolve_embedding_secret(self) -> str | None:
        """The embedding credential, or None when it is the inference credential.

        Raises instead of falling back: an unset variable must fail closed before any file
        is written or any process is started.
        """
        if not self.embedding_api_key_env:
            return None
        value = os.environ.get(self.embedding_api_key_env)
        if not value:
            raise VlmConfigurationError(
                "VLM_CONFIGURATION_INVALID: set the environment variable "
                f"{self.embedding_api_key_env} or declare embedding_api_key_env=None",
                details={"missing": self.embedding_api_key_env,
                         "status": "VLM_CONFIGURATION_INVALID"})
        return value

    def embedding_credential_fingerprint(self) -> str:
        if not self.embedding_api_key_env:
            return self.credential_fingerprint()
        try:
            secret = self.resolve_embedding_secret()
        except VlmConfigurationError:
            return "missing"
        return "sha256:" + hashlib.sha256(str(secret).encode("utf-8")).hexdigest()[:16]

    # -- rendering ----------------------------------------------------------
    def __repr__(self) -> str:  # never render the credential
        return (f"VlmProviderConfig(provider={self.provider!r}, model={self.model!r}, "
                f"api_base={self.api_base!r}, timeout_s={self.timeout_s!r}, "
                f"max_retries={self.max_retries!r}, "
                f"credential={self.secret_source()!r})")

    __str__ = __repr__

    def validated(self) -> "VlmProviderConfig":
        """Return self after checking every field; never touches the credential."""
        problems: list[dict[str, str]] = []
        if not isinstance(self.model, str) or not self.model.strip():
            problems.append({"field": "model", "reason": "a model must be declared explicitly"})
        if self.provider not in SUPPORTED_PROVIDERS:
            problems.append({"field": "provider",
                             "reason": f"must be one of {list(SUPPORTED_PROVIDERS)}"})
        if not isinstance(self.api_base, str) or "://" not in self.api_base:
            problems.append({"field": "api_base", "reason": "must be an absolute URL"})
        if (self.embedding_api_base is not None
                and (not isinstance(self.embedding_api_base, str)
                     or "://" not in self.embedding_api_base)):
            problems.append({"field": "embedding_api_base",
                             "reason": "must be an absolute URL when present"})
        if not isinstance(self.timeout_s, (int, float)) or self.timeout_s <= 0:
            problems.append({"field": "timeout_s", "reason": "must be greater than zero"})
        if not isinstance(self.max_retries, int) or not 0 <= self.max_retries <= 10:
            problems.append({"field": "max_retries", "reason": "must be an integer 0..10"})
        if self.temperature is not None and not isinstance(self.temperature, (int, float)):
            problems.append({"field": "temperature", "reason": "must be a number when present"})
        if problems:
            raise VlmConfigurationError(
                "VLM_CONFIGURATION_INVALID: " + "; ".join(f"{p['field']} {p['reason']}"
                                                          for p in problems),
                details={"status": "VLM_CONFIGURATION_INVALID", "problems": problems})
        return self

    def to_openviking(self, *, env_var: str = SECRET_ENV_VAR) -> dict[str, Any]:
        """The `vlm` block for `ov.conf`. Contains a reference, never the secret.

        `env_var` is the variable OpenViking will expand with `os.path.expandvars()` from
        its own process environment.
        """
        block: dict[str, Any] = {
            "provider": self.provider,
            "model": self.model,
            "api_base": self.api_base,
            "api_key": "${" + env_var + "}",
            "timeout": float(self.timeout_s),
            "max_retries": int(self.max_retries),
        }
        if self.temperature is not None:
            block["temperature"] = float(self.temperature)
        return block

    def to_openviking_embedding(self, *, env_var: str = SECRET_ENV_VAR) -> dict[str, Any] | None:
        """The `embedding` block for `ov.conf`, or None when no embedding model is declared.

        Same rule as the VLM block: the credential travels as a reference that OpenViking
        expands from the environment of its own process, never as a literal.
        """
        if not self.embedding_model:
            return None
        reference = (EMBEDDING_SECRET_ENV_VAR if self.embedding_api_key_env else env_var)
        dense: dict[str, Any] = {
            "model": self.embedding_model,
            "api_key": "${" + reference + "}",
            "api_base": self.embedding_api_base or self.api_base,
            "input": "text",
            "batch_size": 32,
        }
        dimension = self.embedding_dimension or EMBEDDING_DIMENSIONS.get(
            str(self.embedding_model or ""))
        if dimension:
            dense["dimension"] = int(dimension)
        return {"dense": dense, "max_retries": int(self.max_retries)}

    def to_public_dict(self) -> dict[str, Any]:
        """Safe to serialize, log and persist: never includes the credential."""
        return {
            "provider": self.provider,
            "model": self.model,
            "api_base": self.api_base,
            "timeout_s": float(self.timeout_s),
            "max_retries": int(self.max_retries),
            "temperature": self.temperature,
            "credential_configured": self.credential_configured,
            "credential_source": self.secret_source(),
            "credential_reference": "${" + SECRET_ENV_VAR + "}",
            "embedding_model": self.embedding_model,
            "embedding_dimension": (self.embedding_dimension
                                    or EMBEDDING_DIMENSIONS.get(str(self.embedding_model or ""))),
            "embedding_api_base": self.embedding_api_base or self.api_base,
            "embedding_credential_source": self.embedding_secret_source(),
            "embedding_credential_reference": (
                "${" + EMBEDDING_SECRET_ENV_VAR + "}" if self.embedding_api_key_env
                else "${" + SECRET_ENV_VAR + "}"),
        }


class OpenVikingVlmRuntime:
    """Configures the VLM provider of one isolated OpenViking instance.

    This class is a **facade, not a second lifecycle manager**: starting, stopping and the
    health gate are the ones already implemented by
    `kuyen.projection.openviking.start_isolated_server` / `stop_server`. It adds only what a
    configuration facade needs:

    * idempotent `start()` — the same configuration does not spawn a second process;
    * `restart()` — a controlled restart when the model, the endpoint or the credential
      changes, never an implicit one;
    * `status()` — running state and the public (secret-free) VLM view.

    It never writes a global OpenViking file and never touches a server KÜYEN did not start:
    everything lives under `root`.
    """

    def __init__(self, root: str | Path, config: VlmProviderConfig, *,
                 server_bin: str | Path | None = None, port: int | None = None,
                 health_timeout: float = 150.0) -> None:
        self.root = Path(root)
        self.config = config.validated()
        self.server_bin = Path(server_bin) if server_bin is not None else None
        self.port = port
        self.health_timeout = health_timeout
        self._handle: dict[str, Any] | None = None
        self._fingerprint: str | None = None

    # -- state --------------------------------------------------------------
    def _config_fingerprint(self) -> str:
        payload = json.dumps(
            {"vlm": self.config.to_openviking(), "credential": self.config.credential_fingerprint()},
            sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    @property
    def running(self) -> bool:
        if self._handle is None:
            return False
        proc = self._handle["proc"]
        return proc.poll() is None

    def status(self) -> dict[str, Any]:
        """Public, secret-free view of the managed instance."""
        handle = self._handle
        return {
            "configured": True,
            "running": self.running,
            "pid": handle["proc"].pid if handle else None,
            "port": handle["port"] if handle else self.port,
            "root": str(self.root),
            "config_path": str(handle["config_path"]) if handle else None,
            "config_sha256": handle.get("config_sha256") if handle else None,
            "log_path": str(handle["log_path"]) if handle else None,
            "server_binary": str(handle["binary"]) if handle else None,
            "child_env_keys": handle.get("child_env_keys") if handle else [],
            "vlm": self.config.to_public_dict(),
            "credential_fingerprint": self.config.credential_fingerprint(),
        }

    # -- lifecycle (delegated) ---------------------------------------------
    def start(self) -> dict[str, Any]:
        """Start the instance, or keep the current one if nothing changed."""
        fingerprint = self._config_fingerprint()
        if self.running and fingerprint == self._fingerprint:
            return self.status()
        if self._handle is not None:
            self.stop()
        from .projection.openviking import start_isolated_server

        handle = start_isolated_server(
            self.root, server_bin=self.server_bin, port=self.port,
            health_timeout=self.health_timeout, vlm=self.config,
            # A compile needs the local compile backend (measured: without it every compile
            # answers `compile_api.base_url is not configured`).
            server_overrides={"with_bot": True})
        self._handle = handle
        self._fingerprint = fingerprint
        return self.status()

    def restart(self, config: VlmProviderConfig | None = None) -> dict[str, Any]:
        """Stop and start again — the only way a new provider or credential takes effect."""
        if config is not None:
            self.config = config.validated()
        self.stop()
        return self.start()

    def stop(self) -> dict[str, Any]:
        """Stop the instance this facade started; never an external server."""
        from .projection.openviking import stop_server

        if self._handle is None:
            return {"stopped": False, "reason": "not started by this runtime"}
        proc, port = self._handle["proc"], self._handle["port"]
        report = stop_server(proc, port)
        self._handle = None
        self._fingerprint = None
        return {"stopped": True, **report}

    def __repr__(self) -> str:
        return (f"OpenVikingVlmRuntime(root={str(self.root)!r}, running={self.running!r}, "
                f"vlm={self.config!r})")

    __str__ = __repr__

    def __enter__(self) -> "OpenVikingVlmRuntime":
        self.start()
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.stop()
