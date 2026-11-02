"""OpenViking SDK adapter for governed publication.

Only public SDK methods are used. The adapter is a separate boundary from the
compile adapter and never exposes credentials through the public result.
"""
from __future__ import annotations

from typing import Any

from ..credentials import CredentialProvider, EnvironmentCredentialProvider, SecretReference
from ..errors import PublicationAdapterError
from ..ports.publication import OpenVikingPublicationPort


class SdkOpenVikingPublicationAdapter(OpenVikingPublicationPort):
    def __init__(
        self,
        *,
        url: str,
        api_key: str | None = None,
        credential_provider: CredentialProvider | None = None,
        credential_reference: SecretReference | None = None,
        timeout_s: float = 120.0,
        client: Any | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self._api_key = api_key
        self._credential_provider = credential_provider or EnvironmentCredentialProvider()
        self._credential_reference = credential_reference
        self.timeout_s = timeout_s
        self._client = client
        self._owned = client is None

    def __repr__(self) -> str:
        return f"SdkOpenVikingPublicationAdapter(url={self.url!r}, credential_configured={bool(self._api_key or self._credential_reference)})"

    def _resolve_key(self) -> str | None:
        if self._api_key:
            return self._api_key
        if self._credential_reference is not None:
            return self._credential_provider.resolve(self._credential_reference)
        return None

    async def initialize(self) -> None:
        if self._client is not None:
            return
        try:
            from openviking_sdk import AsyncHTTPClient
        except Exception as exc:  # noqa: BLE001
            raise PublicationAdapterError("openviking-sdk is not installed") from exc
        self._client = AsyncHTTPClient(
            url=self.url, api_key=self._resolve_key(), timeout=self.timeout_s,
        )
        await self._client.initialize()

    async def health(self) -> dict[str, Any]:
        await self.initialize()
        try:
            value = await self._client.health()
            return value if isinstance(value, dict) else {"result": value}
        except Exception as exc:  # noqa: BLE001
            raise PublicationAdapterError(f"publication health failed: {type(exc).__name__}") from exc

    async def stat(self, uri: str) -> dict[str, Any] | None:
        await self.initialize()
        try:
            value = await self._client.stat(uri)
            return value if isinstance(value, dict) else {"result": value}
        except Exception as exc:  # noqa: BLE001
            text = str(exc).lower()
            if "404" in text or "not found" in text or "notfound" in text:
                return None
            raise PublicationAdapterError(f"publication stat failed: {uri}: {type(exc).__name__}") from exc

    async def ls(self, uri: str, *, recursive: bool = True) -> list[Any]:
        await self.initialize()
        try:
            value = await self._client.ls(uri, recursive=recursive, simple=True)
            return list(value or [])
        except Exception as exc:  # noqa: BLE001
            raise PublicationAdapterError(f"publication ls failed: {uri}: {type(exc).__name__}") from exc

    async def read(self, uri: str) -> str:
        await self.initialize()
        try:
            raw = getattr(self._client, "read_raw", None)
            value = await (raw(uri) if raw else self._client.read(uri))
            if not isinstance(value, str):
                raise PublicationAdapterError(f"publication artifact is not text: {uri}")
            return value
        except PublicationAdapterError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise PublicationAdapterError(f"publication read failed: {uri}: {type(exc).__name__}") from exc

    async def mkdir(self, uri: str, *, acl: dict[str, Any] | None = None) -> None:
        # OpenViking 0.5.2.1 cannot ACL an empty directory (no context record).
        # The coordinator applies ACL after the payload is indexed.
        await self.initialize()
        try:
            await self._client.mkdir(uri)
        except Exception as exc:  # noqa: BLE001
            raise PublicationAdapterError(f"publication mkdir failed: {uri}: {type(exc).__name__}") from exc

    async def acl_set(self, uri: str, acl: dict[str, Any]) -> None:
        await self.initialize()
        try:
            await self._client.acl_set(
                uri, entries=acl.get("entries"), acl_mode=acl.get("acl_mode"),
            )
        except Exception as exc:  # noqa: BLE001
            raise PublicationAdapterError(f"publication acl_set failed: {uri}: {type(exc).__name__}") from exc

    async def write(self, uri: str, content: str, *, mode: str = "create", wait: bool = True) -> dict[str, Any]:
        await self.initialize()
        try:
            value = await self._client.write(uri, content, mode=mode, wait=wait)
            return value if isinstance(value, dict) else {"result": value}
        except Exception as exc:  # noqa: BLE001
            raise PublicationAdapterError(f"publication write failed: {uri}: {type(exc).__name__}") from exc

    async def batch_write(self, root_uri: str, operations: list[dict[str, Any]], *, wait: bool = True) -> dict[str, Any]:
        await self.initialize()
        try:
            value = await self._client.batch_write(root_uri, operations, wait=wait)
            return value if isinstance(value, dict) else {"result": value}
        except Exception as exc:  # noqa: BLE001
            raise PublicationAdapterError(f"publication batch_write failed: {type(exc).__name__}") from exc

    async def acl_get(self, uri: str) -> dict[str, Any]:
        await self.initialize()
        try:
            value = await self._client.acl_get(uri)
            return value if isinstance(value, dict) else {"result": value}
        except Exception as exc:  # noqa: BLE001
            raise PublicationAdapterError(f"publication acl_get failed: {uri}: {type(exc).__name__}") from exc

    async def wait_processed(self) -> dict[str, Any]:
        await self.initialize()
        try:
            value = await self._client.wait_processed()
            return value if isinstance(value, dict) else {"result": value}
        except Exception as exc:  # noqa: BLE001
            raise PublicationAdapterError(f"publication wait_processed failed: {type(exc).__name__}") from exc

    async def close(self) -> None:
        if self._client is not None and self._owned:
            try:
                await self._client.close()
            finally:
                self._client = None
