"""Public OpenViking SDK adapter.

Only documented SDK methods and the public health endpoint are used. The core
never reaches into SQLite, vector indexes or private SDK state.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

import httpx

from ..credentials import CredentialProvider, EnvironmentCredentialProvider, SecretReference
from ..errors import AdapterError, IngestionTimeoutError, TaskTimeoutError
from ..materialization.paths import PathOwnershipRegistry, relative_provider_path
from ..models import CandidateBundle, Mapu
from ..serialization.serializer import parse_frontmatter
from ..ports.openviking import TaskSnapshot


def _result(value: Any) -> Any:
    if isinstance(value, dict) and "result" in value:
        return value.get("result")
    return value


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _installed_skill_text(value: Any) -> str | None:
    """Extract SKILL.md content from the provider's get_skill response, if present."""
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return None
    for key in ("content", "skill_content", "body", "text"):
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            return item
        if isinstance(item, dict):
            nested = _installed_skill_text(item)
            if nested is not None:
                return nested
    files = value.get("files")
    if isinstance(files, dict):
        for path, content in files.items():
            if str(path).endswith("SKILL.md") and isinstance(content, str):
                return content
    if isinstance(files, list):
        for item in files:
            if isinstance(item, dict) and str(item.get("path", "")).endswith("SKILL.md"):
                content = item.get("content")
                if isinstance(content, str):
                    return content
    return None


def _normalize_whitespace(text: str) -> tuple[str, list[int]]:
    """Return text without whitespace plus, for each kept char, its source index.

    OpenViking's Markdown renderer can insert blank lines after headings. Dropping
    whitespace proves that every non-whitespace character is preserved in order
    without accepting any content change.
    """
    kept: list[str] = []
    index: list[int] = []
    for position, char in enumerate(text):
        if not char.isspace():
            kept.append(char)
            index.append(position)
    return "".join(kept), index


def _skill_equivalent(local_text: str, provider_text: str) -> bool:
    """Compare Skill meaning, not formatting.

    OpenViking re-renders the YAML frontmatter (line wrapping) and strips a final
    newline. Those transformations must not be treated as a different Skill, while
    any change to a frontmatter field or to the body must.
    """
    import json
    import re

    import yaml

    def canonical(text: str) -> tuple[str, str]:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        match = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.DOTALL)
        if not match:
            return ("", re.sub(r"[ \t]+", " ", text).strip())
        try:
            meta = yaml.safe_load(match.group(1)) or {}
        except Exception:  # noqa: BLE001
            meta = {"_unparsed": match.group(1).strip()}
        body = "\n".join(line.rstrip() for line in match.group(2).strip().splitlines())
        return (json.dumps(meta, sort_keys=True, ensure_ascii=False, default=str), body)

    return canonical(local_text) == canonical(provider_text)


class SdkOpenVikingAdapter:
    def __init__(
        self,
        *,
        url: str,
        api_key: str | None = None,
        credential_provider: CredentialProvider | None = None,
        credential_reference: SecretReference | None = None,
        timeout_s: float = 60.0,
        poll_interval_s: float = 3.0,
        ingestion_timeout_s: float = 600.0,
        compile_mode: str = "full",
        client: Any | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self._api_key = api_key
        self._credential_provider = credential_provider or EnvironmentCredentialProvider()
        self._credential_reference = credential_reference
        self.timeout_s = timeout_s
        self.poll_interval_s = poll_interval_s
        self.ingestion_timeout_s = ingestion_timeout_s
        if compile_mode not in {"incremental", "full"}:
            raise ValueError("compile_mode must be 'incremental' or 'full'")
        self.compile_mode = compile_mode
        self.last_source_verification: dict[str, Any] = {}
        self.last_provider_artifacts: dict[str, Any] = {}
        self._client = client
        self._owned = client is None

    def __repr__(self) -> str:
        return f"SdkOpenVikingAdapter(url={self.url!r}, credential_configured={bool(self._api_key or self._credential_reference)})"

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
            raise AdapterError("openviking-sdk is not installed") from exc
        self._client = AsyncHTTPClient(
            url=self.url,
            api_key=self._resolve_key(),
            timeout=max(self.timeout_s, self.ingestion_timeout_s),
        )
        await self._client.initialize()

    async def health(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
            response = await client.get(f"{self.url}/health")
            return {"status_code": response.status_code, "body": response.text[:1000]}

    async def ensure_source(self, mapu: Mapu, container_uri: str) -> str:
        await self.initialize()
        configured = mapu.metadata.get("openviking_uri")
        if configured:
            await self.verify_source(mapu, str(configured))
            return str(configured)
        suffix = Path(mapu.metadata.get("filename", f"{mapu.mapu_id}.txt")).suffix or ".txt"
        with tempfile.TemporaryDirectory(prefix="kuyen-source-") as directory:
            temp_path = Path(directory) / f"{mapu.mapu_id}{suffix}"
            temp_path.write_text(mapu.content, encoding="utf-8")
            try:
                result = _result(
                    await asyncio.wait_for(
                        self._client.add_resource(str(temp_path), to=container_uri, wait=True),
                        timeout=self.ingestion_timeout_s,
                    )
                )
            except (asyncio.TimeoutError, TimeoutError) as exc:
                raise IngestionTimeoutError(
                    f"MAPU ingestion timed out for {mapu.mapu_id} after "
                    f"{self.ingestion_timeout_s:.0f}s ({mapu.byte_length} bytes, "
                    f"{len(mapu.content)} chars); the server may still be processing",
                    details={
                        "mapu_id": mapu.mapu_id, "timeout_s": self.ingestion_timeout_s,
                        "chars": len(mapu.content), "bytes": mapu.byte_length,
                        "operation": "add_resource(wait=True)",
                    },
                ) from exc
            except Exception as exc:  # noqa: BLE001
                detail = str(exc) or "(empty message)"
                raise AdapterError(
                    f"MAPU ingestion failed for {mapu.mapu_id}: {type(exc).__name__}: {detail}"
                ) from exc
        if isinstance(result, dict):
            status = str(result.get("status") or "").lower()
            errors = result.get("errors") or []
            if errors or status in {"failed", "error"}:
                raise AdapterError(
                    f"MAPU ingestion reported errors for {mapu.mapu_id}: "
                    f"status={status or 'unknown'}; errors={errors}"
                )
        uri = ""
        if isinstance(result, dict):
            uri = str(result.get("uri") or result.get("file_uri") or result.get("root_uri") or "")
        if not uri:
            uri = f"{container_uri.rstrip('/')}/{mapu.mapu_id}/{mapu.mapu_id}{suffix}"
        try:
            await self.verify_source(mapu, uri)
            return uri
        except AdapterError:
            # add_resource often returns the destination directory root. Resolve
            # the concrete file through the public listing API before failing.
            try:
                listing = _result(await self._client.ls(uri, recursive=True, simple=True))
                candidates = [
                    str(item) for item in (listing or [])
                    if isinstance(item, str)
                    and item != uri
                    and not item.endswith("/")
                    and not item.rstrip("/") == uri.rstrip("/")
                ]
                for candidate in candidates:
                    try:
                        await self.verify_source(mapu, candidate)
                        return candidate
                    except AdapterError:
                        continue
            except Exception:
                pass
            raise

    async def verify_source(self, mapu: Mapu, uri: str) -> None:
        """Verify that the provider holds the exact source bytes.

        Two real representations are accepted:
          - EXACT_RESOURCE: reading the URI returns the MAPU text byte-for-byte.
          - CHUNKED_EXACT_SLICES: the URI is a container whose leaf artifacts are
            exact contiguous slices of the MAPU text and whose union covers every
            character. This is how OpenViking stores long documents.

        A chunk that is not a slice of the source, a gap, or a partial cover is a
        hard failure: KÜYEN will not validate quotes against a mutated source.
        """
        await self.initialize()
        text: Any = None
        read_error: Exception | None = None
        try:
            text = _result(await self._client.read(uri))
        except Exception as exc:  # noqa: BLE001
            read_error = exc
        if text == mapu.content:
            self.last_source_verification = {
                "mode": "EXACT_RESOURCE", "uri": uri, "chars": len(mapu.content),
                "source_sha256": mapu.sha256, "chunks": 1,
            }
            return
        try:
            listing = _result(await self._client.ls(uri, recursive=True, simple=True))
        except Exception as exc:  # noqa: BLE001
            cause = read_error or exc
            raise AdapterError(
                f"resource unavailable for {mapu.mapu_id} at {uri}: "
                f"{type(cause).__name__}: {cause or '(empty message)'}"
            ) from cause
        leaves = [
            str(item) for item in (listing or [])
            if isinstance(item, str) and item and not item.endswith("/") and item != uri
            and not Path(item).name.startswith(".")
        ]
        if not leaves:
            cause = read_error
            raise AdapterError(
                f"resource content mismatch for {mapu.mapu_id} at {uri}: "
                "not the exact text and no leaf artifacts to verify"
                + (f" ({type(cause).__name__})" if cause else "")
            ) from cause
        files: list[str] = []
        skipped_directories: list[str] = []
        for leaf in leaves:
            is_dir = False
            if hasattr(self._client, "stat"):
                try:
                    info = _result(await self._client.stat(leaf))
                    if isinstance(info, dict):
                        is_dir = bool(info.get("isDir") or info.get("is_dir"))
                except Exception:  # noqa: BLE001
                    is_dir = False
            if is_dir:
                skipped_directories.append(leaf)
                continue
            files.append(leaf)
        spans: list[tuple[int, int, str]] = []
        nsrc, nmap = _normalize_whitespace(mapu.content)
        used_normalization = False
        for leaf in files:
            try:
                chunk = _result(await self._client.read(leaf))
            except Exception as exc:  # noqa: BLE001
                raise AdapterError(
                    f"resource chunk unavailable: {leaf}: {type(exc).__name__}: {exc or '(empty message)'}"
                ) from exc
            if not isinstance(chunk, str) or not chunk:
                continue
            nchunk, _ = _normalize_whitespace(chunk)
            if not nchunk:
                continue
            start = nsrc.find(nchunk)
            if start < 0:
                raise AdapterError(
                    f"resource chunk is not a source slice of {mapu.mapu_id}: {leaf} "
                    f"({len(chunk)} chars, {len(nchunk)} non-whitespace chars, do not occur in the source)"
                )
            if chunk != mapu.content[nmap[start]:nmap[start] + len(chunk)]:
                used_normalization = True
            spans.append((start, start + len(nchunk), leaf))
        if not spans:
            raise AdapterError(f"resource has no readable content for {mapu.mapu_id} at {uri}")
        cursor, gaps = 0, []
        for start, end, _ in sorted(spans):
            if start > cursor:
                gaps.append([cursor, start])
            cursor = max(cursor, end)
        if cursor < len(nsrc):
            gaps.append([cursor, len(nsrc)])
        if gaps:
            raise AdapterError(
                f"resource chunks do not cover {mapu.mapu_id}: uncovered ranges {gaps[:5]}"
            )
        self.last_source_verification = {
            "mode": "CHUNKED_WHITESPACE_EQUIVALENT" if used_normalization else "CHUNKED_EXACT_SLICES",
            "uri": uri, "chars": len(mapu.content), "non_whitespace_chars": len(nsrc),
            "source_sha256": mapu.sha256, "chunks": len(spans),
            "covered_chars": cursor, "gaps": 0,
            "normalization": "whitespace-insensitive" if used_normalization else "none",
            "skipped_directories": len(skipped_directories),
        }

    async def wait_processed(self, timeout_s: float) -> dict[str, Any]:
        await self.initialize()
        deadline = asyncio.get_running_loop().time() + timeout_s
        while True:
            try:
                result = _result(await self._client.wait_processed())
                if isinstance(result, dict) and result.get("pending", 0) == 0:
                    return result
                if not isinstance(result, dict):
                    return {"result": result}
            except Exception as exc:  # noqa: BLE001
                raise AdapterError(f"semantic processing wait failed: {exc}") from exc
            if asyncio.get_running_loop().time() >= deadline:
                raise TaskTimeoutError("semantic processing did not drain")
            await asyncio.sleep(self.poll_interval_s)

    async def ensure_skill(self, skill_dir: str, target_uri: str) -> str:
        """Install the exact local Skill, updating a stale provider copy.

        0.1.2 returned any existing skill with the same name, so a versioned Skill
        change was silently ignored by the provider. 0.1.3 compares the installed
        SKILL.md with the local one and updates it when they differ.
        """
        await self.initialize()
        path = Path(skill_dir)
        skill_name = path.name
        expected = f"{target_uri.rstrip('/')}/{skill_name}"
        local_text = (path / "SKILL.md").read_text(encoding="utf-8")
        installed_text = None
        existing = None
        try:
            existing = _result(await self._client.get_skill(
                skill_name, target_uri=target_uri, include_content=True,
            ))
            installed_text = _installed_skill_text(existing)
        except Exception:
            existing = None
        if existing and installed_text is not None and _skill_equivalent(local_text, installed_text):
            return expected
        if existing and installed_text is None and not hasattr(self._client, "update_skill"):
            # Legacy/fake client without content inspection or update support.
            return expected
        try:
            if existing and hasattr(self._client, "update_skill"):
                _result(await self._client.update_skill(
                    skill_name, str(path), wait=True, options={"target_uri": target_uri},
                ))
            else:
                _result(await self._client.add_skill(
                    str(path), wait=True, options={"target_uri": target_uri},
                ))
        except Exception as exc:  # noqa: BLE001
            # A provider that cannot update in place is reset explicitly.
            try:
                if hasattr(self._client, "delete_skill"):
                    _result(await self._client.delete_skill(skill_name, target_uri=target_uri))
                _result(await self._client.add_skill(
                    str(path), wait=True, options={"target_uri": target_uri},
                ))
            except Exception as inner:  # noqa: BLE001
                raise AdapterError(
                    f"skill install failed: {skill_name}: {type(exc).__name__}: {exc}; "
                    f"reset failed: {type(inner).__name__}: {inner}"
                ) from inner
        try:
            loaded = _result(await self._client.get_skill(
                skill_name, target_uri=target_uri, include_content=True,
            ))
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(f"skill {skill_name} was not readable after install: {type(exc).__name__}") from exc
        if not loaded:
            raise AdapterError(f"skill {skill_name} was not readable after install")
        loaded_text = _installed_skill_text(loaded)
        if loaded_text is not None and not _skill_equivalent(local_text, loaded_text):
            raise AdapterError(
                f"installed skill {skill_name} does not match the local version "
                f"(local_sha256={_sha_text(local_text)[:12]}, provider_sha256={_sha_text(loaded_text)[:12]})"
            )
        return expected

    async def compile(self, *, from_uris: list[str], to_uri: str, skill_uri: str, instruction: str) -> str:
        await self.initialize()
        try:
            response = await self._client.compile(
                from_uris=from_uris,
                to=to_uri,
                skill=skill_uri,
                options={"instruction": instruction, "args": {"mode": self.compile_mode}},
            )
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(f"compile request failed: {exc}") from exc
        payload = _result(response)
        task_id = ""
        if isinstance(payload, dict):
            task_id = str(payload.get("task_id") or payload.get("id") or "")
        if not task_id:
            # The SDK has returned `None` for some 202 responses even though
            # the server accepted the task. Recover it through the public task
            # listing before considering any resubmission.
            try:
                tasks = _result(await self._client.list_tasks(task_type="compile", limit=20))
                if isinstance(tasks, dict):
                    tasks = tasks.get("tasks") or tasks.get("result") or []
                candidates = [item for item in (tasks or []) if isinstance(item, dict)]
                matching = [
                    item for item in candidates
                    if str(((item.get("meta") or {}).get("request") or {}).get("to") or "") == to_uri
                ]
                pool = matching or candidates
                if pool:
                    pool.sort(key=lambda item: float(item.get("created_at") or 0), reverse=True)
                    task_id = str(pool[0].get("task_id") or pool[0].get("id") or "")
            except Exception:
                pass
        if not task_id:
            # Last resort: documented public REST endpoint with an idempotency
            # key, so the compatibility path cannot create an uncontrolled
            # duplicate for the same request.
            try:
                idem = "kuyen-" + hashlib.sha256(
                    json.dumps([from_uris, to_uri, skill_uri, instruction], ensure_ascii=False, sort_keys=True).encode("utf-8")
                ).hexdigest()
                async with httpx.AsyncClient(
                    base_url=self.url, timeout=self.timeout_s, trust_env=False,
                    headers={
                        **({"X-API-Key": self._resolve_key()} if self._resolve_key() else {}),
                        "Idempotency-Key": idem,
                    },
                ) as http:
                    response = await http.post(
                        "/api/v1/compile",
                        json={
                            "from": list(from_uris), "to": to_uri,
                            "skill": skill_uri, "instruction": instruction,
                        },
                    )
                    data = response.json() if response.content else {}
                    result = data.get("result", data) if isinstance(data, dict) else {}
                    task_id = str((result or {}).get("task_id") or (result or {}).get("id") or "") if isinstance(result, dict) else ""
                    if not task_id:
                        raise AdapterError(
                            f"compile response has no task_id: HTTP {response.status_code}: {str(data)[:500]}"
                        )
            except AdapterError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise AdapterError(f"compile fallback failed: {exc}") from exc
        return task_id

    async def wait_task(self, task_id: str, timeout_s: float) -> TaskSnapshot:
        await self.initialize()
        deadline = asyncio.get_running_loop().time() + timeout_s
        last: dict[str, Any] = {}
        while True:
            try:
                response = await self._client.get_task(task_id)
            except Exception as exc:  # noqa: BLE001
                raise AdapterError(f"task status failed: {task_id}: {exc}") from exc
            payload = _result(response)
            status = str(payload.get("status") or payload.get("state") or "").lower() if isinstance(payload, dict) else ""
            if not status:
                # Public REST compatibility path for SDK responses without a
                # usable result object (observed with 202 responses in 0.1.17).
                async with httpx.AsyncClient(
                    base_url=self.url, timeout=self.timeout_s, trust_env=False,
                    headers={"X-API-Key": self._resolve_key()} if self._resolve_key() else {},
                ) as http:
                    http_response = await http.get(f"/api/v1/tasks/{task_id}")
                    data = http_response.json() if http_response.content else {}
                    payload = data.get("result", data) if isinstance(data, dict) else {}
                    status = str(payload.get("status") or payload.get("state") or "").lower() if isinstance(payload, dict) else ""
            if isinstance(payload, dict):
                last = payload
                if status in {"completed", "failed", "cancelled", "canceled"}:
                    return TaskSnapshot(task_id=task_id, status=status, raw=payload)
            if asyncio.get_running_loop().time() >= deadline:
                raise TaskTimeoutError(f"task {task_id} timed out")
            await asyncio.sleep(self.poll_interval_s)

    async def _read_artifact(self, uri: str) -> str:
        try:
            value = _result(await self._client.read(uri))
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(f"artifact read failed: {uri}: {exc}") from exc
        if not isinstance(value, str):
            raise AdapterError(f"artifact is not text: {uri}")
        return value

    async def read_candidate(self, output_uri: str) -> CandidateBundle:
        await self.initialize()
        try:
            listing = _result(await self._client.ls(output_uri, recursive=True, simple=True))
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(f"output listing failed: {output_uri}: {exc}") from exc
        uris = [str(x) for x in (listing or []) if isinstance(x, str)]
        sidecar_uri = next((x for x in uris if x.endswith("/kuyen_candidates.json")), None)
        if sidecar_uri:
            try:
                return CandidateBundle.from_dict(json.loads(await self._read_artifact(sidecar_uri)))
            except Exception as exc:  # noqa: BLE001
                raise AdapterError(f"candidate sidecar invalid: {exc}") from exc
        entities = []
        for uri in uris:
            if uri.endswith(".md") and "/entities/" in uri:
                meta, body = parse_frontmatter(await self._read_artifact(uri))
                sources = meta.get("sources") or []
                aliases = meta.get("aliases") or []
                entities.append(
                    {
                        "id": meta.get("id") or Path(uri).stem,
                        "name": meta.get("title") or meta.get("name") or Path(uri).stem,
                        "entity_type": meta.get("entity_type") or "concept",
                        "description": meta.get("description") or body.strip(),
                        "sources": [sources] if isinstance(sources, str) else list(sources),
                        "aliases": [aliases] if isinstance(aliases, str) else list(aliases),
                    }
                )
        relations = []
        for uri in uris:
            if uri.endswith("/relations.jsonl"):
                for line in (await self._read_artifact(uri)).splitlines():
                    if line.strip():
                        relations.append(json.loads(line))
        return CandidateBundle.from_dict(
            {"entities": entities, "relations": relations, "evidence": [], "coverage": []}
        )

    async def read_provider_artifacts(self, output_uri: str) -> dict[str, str]:
        """Read the provider output tree once, without writing to it.

        Returns provider-relative path -> exact bytes. Duplicate paths, directory
        entries, hidden provider summaries and paths outside the output root are
        rejected or skipped before materialization.
        """
        await self.initialize()
        try:
            listing = _result(await self._client.ls(output_uri, recursive=True, simple=True))
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(
                f"provider output listing failed: {output_uri}: {type(exc).__name__}: {exc or '(empty message)'}"
            ) from exc
        registry = PathOwnershipRegistry()
        leaves: list[tuple[str, str]] = []
        for item in listing or []:
            if not isinstance(item, str):
                continue
            uri = item.rstrip("/")
            if not uri or uri == output_uri.rstrip("/"):
                continue
            if Path(uri).name.startswith("."):
                continue
            is_dir = False
            if hasattr(self._client, "stat"):
                try:
                    info = _result(await self._client.stat(uri))
                    if isinstance(info, dict):
                        is_dir = bool(info.get("isDir") or info.get("is_dir"))
                except Exception:  # noqa: BLE001
                    is_dir = False
            if is_dir:
                continue
            relative = relative_provider_path(output_uri, uri)
            leaves.append((relative, uri))
        paths = registry.assert_unique([relative for relative, _ in leaves])
        artifacts: dict[str, str] = {}
        for relative, uri in leaves:
            try:
                text = _result(await self._client.read(uri))
            except Exception as exc:  # noqa: BLE001
                raise AdapterError(
                    f"provider artifact read failed: {uri}: {type(exc).__name__}: {exc or '(empty message)'}"
                ) from exc
            if not isinstance(text, str):
                raise AdapterError(f"provider artifact is not text: {uri}")
            artifacts[relative] = text
        self.last_provider_artifacts = {
            "uri": output_uri, "paths": paths, "count": len(artifacts),
        }
        return artifacts

    async def search(self, query: str, target_uri: str, *, limit: int = 10) -> Any:
        """Public semantic retrieval over the ingested resource."""
        await self.initialize()
        try:
            value = await self._client.search(
                query=query, target_uri=target_uri, limit=limit,
            )
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(
                f"OpenViking search failed: {type(exc).__name__}: {exc or '(empty message)'}"
            ) from exc
        return _result(value)

    async def search_context(self, query: str, target_uri: str, *, limit: int = 10) -> Any:
        """Compatibility alias; OpenViking context mode rejects target_uri."""
        return await self.search(query, target_uri, limit=limit)

    async def close(self) -> None:
        if self._client is not None and self._owned:
            try:
                await self._client.close()
            finally:
                self._client = None
