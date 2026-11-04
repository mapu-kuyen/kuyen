"""Persistence: local bundle assembly plus real OpenViking storage/read-back.

Only interfaces verified in the previous experiment are used: content/write,
content/read, fs/mkdir, fs/stat, fs/ls, fs/tree, search/grep. Custom metadata is
never assumed to survive: everything canonical lives inside the sidecar and the
integrity manifest, which are stored as ordinary files.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..canonical import canonical_json, digest, read_json, sha256_file, sha256_text, write_canonical

BUNDLE_SCHEMA = "KUYEN_SIDECAR_BUNDLE"
BUNDLE_SCHEMA_VERSION = "1.0.0"
INTEGRITY_SCHEMA = "KUYEN_BUNDLE_INTEGRITY"
INTEGRITY_SCHEMA_VERSION = "1.0.0"


def build_bundle(bundle_dir: Path, *, sidecar: dict[str, Any], mapping: dict[str, Any],
                 projection_manifest: dict[str, Any], artifacts: dict[str, str],
                 run_log: dict[str, Any], created_at: str | None = None) -> dict[str, Any]:
    """Write every artifact locally in a deterministic layout and seal it."""
    bundle_dir = Path(bundle_dir)
    written: dict[str, str] = {}
    for name, text in sorted(artifacts.items()):
        target = bundle_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        written[name] = sha256_text(text)
    written["native/projection_manifest.json"] = write_canonical(bundle_dir / "native/projection_manifest.json", projection_manifest)
    written["sidecar/KUYEN_CANONICAL_SIDECAR.json"] = write_canonical(bundle_dir / "sidecar/KUYEN_CANONICAL_SIDECAR.json", sidecar)
    written["mapping/CORRESPONDENCE_MANIFEST.json"] = write_canonical(bundle_dir / "mapping/CORRESPONDENCE_MANIFEST.json", mapping)
    written["RUN_LOG.json"] = write_canonical(bundle_dir / "RUN_LOG.json", run_log)

    integrity = {
        "schema_name": INTEGRITY_SCHEMA,
        "schema_version": INTEGRITY_SCHEMA_VERSION,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "kuyen_id": sidecar["kuyen_id"],
        "kuyen_version": sidecar["kuyen_version"],
        "canonical_graph_hash": sidecar["canonical_graph_hash"],
        "sidecar_content_hash": sidecar["integrity"]["sidecar_content_hash"],
        "mapping_id": mapping["mapping_id"],
        "projection_id": projection_manifest["projection_id"],
        "openviking_version": sidecar.get("openviking_version"),
        "exporter_version": sidecar.get("exporter_version"),
        "projector_version": sidecar.get("projector_version"),
        "file_hashes": dict(sorted(written.items())),
        "file_count": len(written),
        "hash_scope": "every file of the bundle except manifests/INTEGRITY.json itself",
    }
    integrity["bundle_id"] = digest({key: value for key, value in integrity.items() if key != "bundle_id"})
    write_canonical(bundle_dir / "manifests/INTEGRITY.json", integrity)

    bundle = {
        "schema_name": BUNDLE_SCHEMA,
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "kuyen_id": sidecar["kuyen_id"],
        "kuyen_version": sidecar["kuyen_version"],
        "bundle_id": integrity["bundle_id"],
        "sidecar_content_hash": sidecar["integrity"]["sidecar_content_hash"],
        "mapping_id": mapping["mapping_id"],
        "projection_id": projection_manifest["projection_id"],
        "files": sorted(list(written) + ["manifests/INTEGRITY.json"]),
        "uri_root": None,
    }
    return {"bundle": bundle, "integrity": integrity, "file_hashes": written}


def verify_integrity(integrity: dict[str, Any], files: dict[str, bytes]) -> dict[str, Any]:
    problems: list[str] = []
    missing, mismatched = [], []
    for name, expected in (integrity.get("file_hashes") or {}).items():
        payload = files.get(name)
        if payload is None:
            missing.append(name)
            continue
        if sha256_text(payload.decode("utf-8")) != expected:
            mismatched.append(name)
    extra = sorted(set(files) - set((integrity.get("file_hashes") or {})) - {"manifests/INTEGRITY.json"})
    if missing:
        problems.append(f"MANIFEST_MISMATCH: missing bundle files {missing}")
    if mismatched:
        problems.append(f"PROJECTION_HASH_MISMATCH: bundle files changed {mismatched}")
    if extra:
        problems.append(f"MANIFEST_MISMATCH: undeclared bundle files {extra}")
    recomputed = digest({key: value for key, value in integrity.items() if key != "bundle_id"})
    if recomputed != integrity.get("bundle_id"):
        problems.append("MANIFEST_MISMATCH: bundle_id does not match the recomputed digest")
    return {"ok": not problems, "problems": problems, "missing": missing, "mismatched": mismatched, "extra": extra,
            "bundle_id": integrity.get("bundle_id"), "recomputed_bundle_id": recomputed}


@dataclass
class Response:
    status: int | str
    payload: Any

    @property
    def ok(self) -> bool:
        return self.status == 200 and isinstance(self.payload, dict) and self.payload.get("status") == "ok"

    @property
    def result(self) -> Any:
        return (self.payload or {}).get("result") if isinstance(self.payload, dict) else None

    @property
    def error_code(self) -> str | None:
        if isinstance(self.payload, dict) and self.payload.get("error"):
            return (self.payload.get("error") or {}).get("code")
        return None

    @property
    def error_message(self) -> str | None:
        if isinstance(self.payload, dict) and self.payload.get("error"):
            return (self.payload.get("error") or {}).get("message")
        return None

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "ok": self.ok, "error_code": self.error_code,
                "error_message": self.error_message, "result": self.result if self.ok else self.payload}


class OpenVikingStore:
    """Minimal loopback-only client using only verified endpoints."""

    def __init__(self, base_url: str, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, body: Any = None) -> Response:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(self.base_url + path, data=data, method=method,
                                        headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
                return Response(response.status, json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8") if exc.fp else ""
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload = {"raw": raw[:500]}
            return Response(exc.code, payload)
        except Exception as exc:  # noqa: BLE001
            return Response("ERR", {"transport_error": str(exc)})

    def health(self) -> Response:
        return self._request("GET", "/health")

    def mkdir(self, uri: str) -> Response:
        return self._request("POST", "/api/v1/fs/mkdir", {"uri": uri})

    def write(self, uri: str, content: str) -> Response:
        return self._request("POST", "/api/v1/content/write",
                             {"uri": uri, "content": content, "mode": "replace", "wait": False})

    def read(self, uri: str) -> Response:
        query = urllib.parse.urlencode({"uri": uri, "raw": "true"})
        return self._request("GET", f"/api/v1/content/read?{query}")

    def stat(self, uri: str) -> Response:
        query = urllib.parse.urlencode({"uri": uri})
        return self._request("GET", f"/api/v1/fs/stat?{query}")

    def ls(self, uri: str, *, recursive: bool = False) -> Response:
        query = urllib.parse.urlencode({"uri": uri, "recursive": str(recursive).lower()})
        return self._request("GET", f"/api/v1/fs/ls?{query}")

    def tree(self, uri: str) -> Response:
        query = urllib.parse.urlencode({"uri": uri, "output": "original"})
        return self._request("GET", f"/api/v1/fs/tree?{query}")

    def grep(self, uri: str, pattern: str, **extra: Any) -> Response:
        return self._request("POST", "/api/v1/search/grep", {"uri": uri, "pattern": pattern, **extra})

    def rm(self, uri: str, *, recursive: bool = True) -> Response:
        query = urllib.parse.urlencode({"uri": uri, "recursive": str(recursive).lower()})
        return self._request("DELETE", f"/api/v1/fs?{query}")


def persist_bundle(store: OpenVikingStore, bundle_dir: Path, uri_root: str) -> dict[str, Any]:
    """Write every bundle file through the real native API and read it back."""
    bundle_dir = Path(bundle_dir)
    results: list[dict[str, Any]] = []
    mkdir = store.mkdir(uri_root)
    for path in sorted(p for p in bundle_dir.rglob("*") if p.is_file()):
        relative = path.relative_to(bundle_dir).as_posix()
        text = path.read_text(encoding="utf-8")
        uri = f"{uri_root}/{relative}"
        write = store.write(uri, text)
        read = store.read(uri)
        content = read.result if read.ok else None
        results.append({
            "path": relative, "uri": uri, "bytes": len(text.encode("utf-8")),
            "local_sha256": sha256_text(text),
            "write_status": write.status, "write_ok": write.ok,
            "read_status": read.status, "read_ok": read.ok,
            "read_sha256": sha256_text(content) if isinstance(content, str) else None,
            "byte_exact": bool(isinstance(content, str) and sha256_text(content) == sha256_text(text)),
        })
    return {
        "uri_root": uri_root,
        "mkdir_status": mkdir.status, "mkdir_ok": mkdir.ok,
        "files": len(results), "writes_ok": sum(1 for item in results if item["write_ok"]),
        "reads_ok": sum(1 for item in results if item["read_ok"]),
        "byte_exact": sum(1 for item in results if item["byte_exact"]),
        "results": results,
    }


UNHASHED_BUNDLE_FILES: tuple[str, ...] = ("manifests/INTEGRITY.json",)


def recover_bundle(store: OpenVikingStore, uri_root: str, target_dir: Path,
                   expected: dict[str, str],
                   extra_files: tuple[str, ...] = UNHASHED_BUNDLE_FILES) -> dict[str, Any]:
    """Read the bundle back from OpenViking into a directory (no local copy is read).

    The integrity manifest cannot hash itself, so it is recovered through the same
    native read path and recorded separately; the reconstructor verifies it against
    the recovered bytes of every other file.
    """
    target_dir = Path(target_dir)
    recovered: dict[str, str] = {}
    missing, mismatched = [], []
    for relative in extra_files:
        response = store.read(f"{uri_root}/{relative}")
        if not response.ok or not isinstance(response.result, str):
            missing.append(relative)
            continue
        target = target_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(response.result, encoding="utf-8")
        recovered[relative] = sha256_text(response.result)
    for relative, expected_hash in sorted(expected.items()):
        uri = f"{uri_root}/{relative}"
        response = store.read(uri)
        if not response.ok or not isinstance(response.result, str):
            missing.append(relative)
            continue
        text = response.result
        target = target_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        actual = sha256_text(text)
        recovered[relative] = actual
        if actual != expected_hash:
            mismatched.append(relative)
    return {"uri_root": uri_root, "recovered": len(recovered), "expected": len(expected) + len(extra_files),
            "missing": missing, "mismatched": mismatched, "hashes": recovered,
            "ok": not missing and not mismatched,
            "target_dir": str(target_dir)}


def start_isolated_server(root: Path, *, server_bin: Path | None = None,
                          port: int | None = None, health_timeout: float = 150.0,
                          vlm: Any | None = None,
                          server_overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Start one isolated OpenViking instance from a KÜYEN-owned `ov.conf`.

    Single lifecycle manager of the package: `kuyen.vlm.OpenVikingVlmRuntime` and the
    projection path both end up here, so there is exactly one place that writes a config,
    spawns the process, waits for `/health` and stops it.

    `vlm` (optional) is a `kuyen.vlm.VlmProviderConfig`. When given:

    * the credential is resolved **before** any file is written or process is spawned, so a
      missing key fails closed and leaves no partial state;
    * `ov.conf` receives a `${KUYEN_VLM_API_KEY}` **reference** — never the value;
    * the value travels only in the environment of the child process; `os.environ` of the
      caller is never modified;
    * the returned mapping reports the credential source and never a secret.

    `server_overrides` merges into the `server` section (used for diagnostics such as
    `with_bot` / `bot_api_url`); nothing is invented and no global OpenViking file is read
    or written: the instance lives entirely under `root`.
    """
    from ..vlm import EMBEDDING_SECRET_ENV_VAR as _EMBEDDING_SECRET_ENV
    from ..vlm import SECRET_ENV_VAR as _VLM_SECRET_ENV

    root = Path(root).resolve()
    (root / "workspace").mkdir(parents=True, exist_ok=True)
    (root / "home").mkdir(parents=True, exist_ok=True)
    binary = Path(server_bin or os.environ.get("OV_SERVER_BIN") or Path.home() / ".venvs/openviking/bin/openviking-server")
    if not binary.is_file():
        raise RuntimeError(f"openviking-server not found: {binary}")
    if port is None:
        port = _free_port()
    secret: str | None = None
    embedding_secret: str | None = None
    if vlm is not None:
        # fail closed before writing anything or spawning a process
        vlm.validated()
        secret = vlm.resolve_secret()
        embedding_secret = vlm.resolve_embedding_secret()
    config = {
        "server": {"host": "127.0.0.1", "port": port, "workers": 1, "auth_mode": "dev",
                   "cors_origins": ["http://127.0.0.1"], **(server_overrides or {})},
        "storage": {"workspace": str(root / "workspace"),
                    "vectordb": {"name": "context", "backend": "local", "project": "default"},
                    "agfs": {"backend": "local"}},
    }
    if vlm is not None:
        config["vlm"] = vlm.to_openviking(env_var=_VLM_SECRET_ENV)
        # Without an embedding provider the instance falls back to a local embedder that is not
        # installed and every ingestion fails (KUYEN_DISTRIBUTED_ANTU_12, measured).
        embedding_block = vlm.to_openviking_embedding(env_var=_VLM_SECRET_ENV)
        if embedding_block is not None:
            config["embedding"] = embedding_block
    config_path = root / "ov.conf"
    _write_private_config(config_path, config)
    env = dict(os.environ)
    # a stale provider key inherited from the caller must never decide what the instance
    # authenticates with: the environment of the child is owned by KÜYEN
    env.pop(_VLM_SECRET_ENV, None)
    env.pop(_EMBEDDING_SECRET_ENV, None)
    env.update({"HOME": str(root / "home"), "OPENVIKING_CONFIG_FILE": str(config_path),
                "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
                "HTTP_PROXY": "", "HTTPS_PROXY": "", "http_proxy": "", "https_proxy": ""})
    if secret is not None:
        env[_VLM_SECRET_ENV] = secret
    if embedding_secret is not None:
        env[_EMBEDDING_SECRET_ENV] = embedding_secret
    log_path = root / "server.log"
    # A compile needs a local compile backend: without `--bot` OpenViking answers
    # `compile API: compile_api.base_url is not configured` and no document can be compiled
    # (measured in KUYEN_DISTRIBUTED_ANTU_12). The bot runs on its own port, inside the same
    # isolated root, and is only started when the caller asks for it.
    command = [str(binary), "--host", "127.0.0.1", "--port", str(port)]
    config_server = config.get("server") or {}
    if config_server.get("with_bot"):
        bot_port = int(config_server.get("bot_port") or (port + 1))
        command += ["--bot", "--bot-port", str(bot_port)]
        config["server"]["bot_api_url"] = f"http://127.0.0.1:{bot_port}"
        _write_private_config(config_path, config)
    log = log_path.open("w", encoding="utf-8")
    try:
        proc = subprocess.Popen(command,
                                cwd=str(root), env=env, stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True)
    finally:
        log.close()
    store = OpenVikingStore(f"http://127.0.0.1:{port}")
    deadline = time.time() + health_timeout
    health: dict[str, Any] = {}
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"server exited early ({proc.returncode}); see {log_path}")
        response = store.health()
        if response.ok and (response.payload or {}).get("healthy"):
            health = response.payload
            break
        time.sleep(0.5)
    if not health:
        stop_server(proc, port)
        raise RuntimeError(f"server did not become healthy; see {log_path}")
    handle: dict[str, Any] = {
        "proc": proc, "port": port, "store": store, "health": health,
        "config_path": config_path, "log_path": log_path, "root": root, "binary": str(binary),
        "config_sha256": sha256_file(config_path),
        # names only: a full environment dump would leak the caller's secrets
        "child_env_keys": sorted({name for name, value in
                                  ((_VLM_SECRET_ENV, secret),
                                   (_EMBEDDING_SECRET_ENV, embedding_secret))
                                  if value is not None}),
        "vlm": vlm.to_public_dict() if vlm is not None else None,
        "vlm_credential_fingerprint": vlm.credential_fingerprint() if vlm is not None else None,
        "vlm_secret_env": _VLM_SECRET_ENV if vlm is not None else None,
        "embedding_secret_env": (_EMBEDDING_SECRET_ENV if embedding_secret is not None else None),
        "embedding_credential_fingerprint": (vlm.embedding_credential_fingerprint()
                                            if vlm is not None else None),
        "bot": bool(config_server.get("with_bot")),
        "embedding": (vlm.to_public_dict().get("embedding_model") if vlm is not None else None),
    }
    return handle


def _write_private_config(path: Path, config: dict[str, Any]) -> str:
    """Write `ov.conf` atomically with owner-only permissions (0600).

    The file carries a `${...}` reference, never a credential; the mode still matters so a
    future field cannot be read by another account by accident.
    """
    payload = json.dumps(config, indent=2) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        os.write(descriptor, payload.encode("utf-8"))
    finally:
        os.close(descriptor)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    os.chmod(path, 0o600)
    return sha256_text(payload)



def _free_port(start: int = 21500, stop: int = 21600) -> int:
    for port in range(start, stop):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"no free loopback port in [{start},{stop})")


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def stop_server(proc: subprocess.Popen, port: int, *, timeout: float = 20.0) -> dict[str, Any]:
    terminated = False
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(10)
        terminated = True
    time.sleep(0.5)
    alive = False
    try:
        os.kill(proc.pid, 0)
        alive = True
    except OSError:
        alive = False
    return {"pid": proc.pid, "terminated": terminated, "exit_code": proc.returncode,
            "port": port, "port_still_open": port_open(port), "pid_alive": alive}
