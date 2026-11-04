"""Offline tests for the KÜYEN-managed OpenViking VLM provider configuration.

The real smoke test (one inference through OpenViking) lives in the experiment directory and
needs a credential; these tests never touch a network, never call a model provider and use a
fake server binary that only answers `/health`.

KUYEN_OPENVIKING_VLM_CONFIGURATION_05, §9.
"""
from __future__ import annotations

import json
import os
import socket
import stat
import sys
import time
from pathlib import Path

import pytest

import kuyen
from kuyen.vlm import (
    DEFAULT_API_KEY_ENV, SECRET_ENV_VAR, OpenVikingVlmRuntime, VlmConfigurationError,
    VlmProviderConfig,
)

FAKE_KEY = "sk-offline-test-not-a-real-credential"
OV_KEY = "ov-offline-server-key"


FAKE_SERVER = '''\
import json, os, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

port = int(sys.argv[sys.argv.index("--port") + 1])
dump = os.environ.get("FAKE_ENV_DUMP")
if dump:
    with open(dump, "w", encoding="utf-8") as handle:
        json.dump(dict(os.environ), handle)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"healthy": True, "status": "ok", "uri": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass

HTTPServer(("127.0.0.1", port), Handler).serve_forever()
'''


@pytest.fixture()
def fake_binary(tmp_path: Path) -> Path:
    """A stand-in for `openviking-server` that answers the health probe and nothing else."""
    path = tmp_path / "fake-openviking-server"
    path.write_text(f"#!{sys.executable}\n" + FAKE_SERVER, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def config(**overrides) -> VlmProviderConfig:
    values = {"model": "kuyen-test-model", "api_key": FAKE_KEY}
    values.update(overrides)
    return VlmProviderConfig(**values)


# 1 ---------------------------------------------------------------------------
def test_valid_configuration_renders_the_openviking_block():
    block = config(timeout_s=30.0, max_retries=0, temperature=0.0).to_openviking()
    assert block["provider"] == "openai"
    assert block["model"] == "kuyen-test-model"
    assert block["api_base"] == "https://api.openai.com/v1"
    assert block["api_key"] == "${" + SECRET_ENV_VAR + "}"
    assert block["timeout"] == 30.0
    assert block["max_retries"] == 0
    assert block["temperature"] == 0.0


def test_openai_is_the_default_provider_and_api_base():
    cfg = config()
    assert cfg.provider == "openai"
    assert cfg.api_base == "https://api.openai.com/v1"


# 2 ---------------------------------------------------------------------------
@pytest.mark.parametrize("overrides,field", [
    ({"model": ""}, "model"),
    ({"model": "   "}, "model"),


    ({"provider": "local-openai-compatible"}, "provider"),
    ({"api_base": "api.openai.com/v1"}, "api_base"),
    ({"timeout_s": 0}, "timeout_s"),
    ({"timeout_s": -1}, "timeout_s"),
    ({"max_retries": -1}, "max_retries"),
    ({"max_retries": 11}, "max_retries"),
])
def test_incomplete_configuration_is_rejected(overrides, field):
    with pytest.raises(VlmConfigurationError) as caught:
        config(**overrides).validated()
    assert caught.value.code == "VLM_CONFIGURATION_INVALID"
    assert any(problem["field"] == field for problem in caught.value.details["problems"])


# 3 ---------------------------------------------------------------------------
def test_missing_api_key_names_the_variable_and_never_leaks(monkeypatch):
    monkeypatch.delenv(DEFAULT_API_KEY_ENV, raising=False)
    cfg = VlmProviderConfig(model="kuyen-test-model")
    assert cfg.credential_configured is False
    assert cfg.secret_source() == "missing"
    with pytest.raises(VlmConfigurationError) as caught:
        cfg.resolve_secret()
    assert DEFAULT_API_KEY_ENV in caught.value.message
    assert caught.value.code == "VLM_CONFIGURATION_INVALID"
    assert FAKE_KEY not in json.dumps(caught.value.to_dict())


def test_api_key_can_come_from_the_environment(monkeypatch):
    monkeypatch.setenv(DEFAULT_API_KEY_ENV, FAKE_KEY)
    cfg = VlmProviderConfig.from_environment(model="kuyen-test-model")
    assert cfg.secret_source() == f"environment:{DEFAULT_API_KEY_ENV}"
    assert cfg.resolve_secret() == FAKE_KEY


# 4 ---------------------------------------------------------------------------
def test_model_must_be_declared_explicitly():
    with pytest.raises(TypeError):
        VlmProviderConfig()  # no model keyword at all
    with pytest.raises(VlmConfigurationError):
        VlmProviderConfig(model="").validated()


# 8 ---------------------------------------------------------------------------
def test_secret_is_absent_from_every_artifact(tmp_path: Path, fake_binary: Path):
    cfg = config()
    runtime = OpenVikingVlmRuntime(tmp_path / "inst", cfg, server_bin=fake_binary,
                                   health_timeout=20.0)
    try:
        status = runtime.start()
        assert FAKE_KEY not in json.dumps(status, ensure_ascii=False)
        assert SECRET_ENV_VAR in status["child_env_keys"]
        assert FAKE_KEY not in repr(runtime)
        assert FAKE_KEY not in repr(cfg)
        assert FAKE_KEY not in str(cfg)
        assert FAKE_KEY not in json.dumps(cfg.to_public_dict(), ensure_ascii=False)
        assert FAKE_KEY not in json.dumps(runtime.status(), ensure_ascii=False)
        for path in sorted((tmp_path / "inst").rglob("*")):
            if path.is_file():
                assert FAKE_KEY.encode() not in path.read_bytes(), f"leaked into {path}"
    finally:
        runtime.stop()


# 9 ---------------------------------------------------------------------------
def test_start_is_idempotent_and_restart_follows_a_configuration_change(
        tmp_path: Path, fake_binary: Path):
    runtime = OpenVikingVlmRuntime(tmp_path / "inst", config(), server_bin=fake_binary,
                                   health_timeout=20.0)
    try:
        first = runtime.start()
        second = runtime.start()
        assert first["pid"] == second["pid"]

        rotated = runtime.restart(config(model="kuyen-other-model", api_key=FAKE_KEY + "-2"))
        assert rotated["pid"] != first["pid"]
        assert rotated["vlm"]["model"] == "kuyen-other-model"
        assert rotated["credential_fingerprint"] != first["credential_fingerprint"]

        third = runtime.start()
        assert third["pid"] == rotated["pid"]
    finally:
        report = runtime.stop()
    assert report["stopped"] is True
    assert report["port_still_open"] is False


# 10 --------------------------------------------------------------------------
def test_missing_binary_fails_before_writing_anything(tmp_path: Path):
    with pytest.raises(RuntimeError):
        OpenVikingVlmRuntime(tmp_path / "inst", config(), server_bin=tmp_path / "nope",
                             health_timeout=5.0).start()
    assert not (tmp_path / "inst" / "ov.conf").exists()


def test_missing_credential_fails_before_spawning(tmp_path: Path, fake_binary: Path, monkeypatch):
    monkeypatch.delenv(DEFAULT_API_KEY_ENV, raising=False)
    cfg = VlmProviderConfig(model="kuyen-test-model")
    with pytest.raises(VlmConfigurationError):
        OpenVikingVlmRuntime(tmp_path / "inst", cfg, server_bin=fake_binary,
                             health_timeout=5.0).start()
    assert not (tmp_path / "inst" / "ov.conf").exists()


def test_server_that_exits_early_is_reported(tmp_path: Path):
    dying = tmp_path / "dying-server"
    dying.write_text(f"#!{sys.executable}\nimport sys\nsys.exit(3)\n", encoding="utf-8")
    dying.chmod(dying.stat().st_mode | stat.S_IXUSR)
    with pytest.raises(RuntimeError) as caught:
        OpenVikingVlmRuntime(tmp_path / "inst", config(), server_bin=dying,
                             health_timeout=5.0).start()
    assert "exited early" in str(caught.value)


# 11 --------------------------------------------------------------------------
def test_openai_key_and_openviking_server_key_are_different_secrets(
        tmp_path: Path, fake_binary: Path, monkeypatch):
    from kuyen.projection.openviking import start_isolated_server, stop_server

    monkeypatch.setenv("KUYEN_OPENVIKING_API_KEY", OV_KEY)
    handle = start_isolated_server(tmp_path / "inst", server_bin=fake_binary,
                                   health_timeout=20.0, vlm=config())
    try:
        text = handle["config_path"].read_text(encoding="utf-8")
        # the OpenViking client key never becomes the VLM key and vice versa
        assert OV_KEY not in text
        assert FAKE_KEY not in text
        assert json.loads(text)["vlm"]["api_key"] == "${" + SECRET_ENV_VAR + "}"
        assert json.loads(text)["server"].get("root_api_key") is None
        assert FAKE_KEY not in handle["child_env_keys"]
        assert handle["vlm"]["credential_source"] == "argument"
    finally:
        stop_server(handle["proc"], handle["port"])


# 12 --------------------------------------------------------------------------
def test_no_direct_extraction_is_reachable_from_the_vlm_configuration(
        tmp_path: Path, fake_binary: Path):
    """Configuring the VLM must not create a KÜYEN-side model client.

    * the module imports no provider SDK and no HTTP client;
    * using it never imports `kuyen.extraction` nor the `openai` package;
    * the only socket opened is the loopback health probe.
    """
    source = Path(kuyen.__file__).parent.joinpath("vlm.py").read_text(encoding="utf-8")
    for forbidden in ("from openai", "import openai", "import httpx", "import requests",
                      "openai_provider", "OpenAIExtractionProvider"):
        assert forbidden not in source, forbidden

    opened: list[tuple] = []
    original = socket.socket.connect

    def recording(self, address):
        opened.append(address)
        return original(self, address)

    before = set(sys.modules)
    socket.socket.connect = recording
    runtime = OpenVikingVlmRuntime(tmp_path / "inst", config(), server_bin=fake_binary,
                                   health_timeout=20.0)
    try:
        runtime.start()
        runtime.stop()
    finally:
        socket.socket.connect = original

    new_modules = set(sys.modules) - before
    assert not {name for name in new_modules if name.startswith("kuyen.extraction")}
    assert not {name for name in new_modules if name == "openai" or name.startswith("openai.")}
    hosts = {item[0] for item in opened if isinstance(item, tuple)}
    assert hosts <= {"127.0.0.1", "localhost"}, hosts
    assert not any(str(host).endswith("openai.com") for host in hosts)

    assert "gpt-6-luna" not in Path(kuyen.__file__).parent.joinpath("vlm.py").read_text()


# 5 ---------------------------------------------------------------------------
def test_ov_conf_serialization_contains_a_reference_and_no_secret(tmp_path: Path, fake_binary: Path):
    from kuyen.projection.openviking import start_isolated_server, stop_server

    handle = start_isolated_server(tmp_path / "inst", server_bin=fake_binary,
                                   health_timeout=20.0, vlm=config())
    try:
        text = handle["config_path"].read_text(encoding="utf-8")
        parsed = json.loads(text)
        assert parsed["vlm"]["api_key"] == "${" + SECRET_ENV_VAR + "}"
        assert parsed["vlm"]["provider"] == "openai"
        assert parsed["vlm"]["model"] == "kuyen-test-model"
        assert FAKE_KEY not in text
        assert (handle["config_path"].stat().st_mode & 0o777) == 0o600
    finally:
        stop_server(handle["proc"], handle["port"])


# 6 ---------------------------------------------------------------------------
def test_the_isolated_instance_declares_its_embedding_provider(tmp_path: Path,
                                                              fake_binary: Path):
    """Without an embedding provider the instance cannot ingest anything.

    Measured: OpenViking falls back to a local embedder that is not installed and every MAPU
    fails with `Local embedding is enabled but 'llama-cpp-python' is not installed`
    (KUYEN_DISTRIBUTED_ANTU_APPLICABILITY_12). The block reuses the same credential reference
    as the VLM and never carries the secret.
    """
    from kuyen.projection.openviking import start_isolated_server, stop_server

    handle = start_isolated_server(tmp_path / "inst", server_bin=fake_binary,
                                   health_timeout=20.0, vlm=config())
    try:
        text = handle["config_path"].read_text(encoding="utf-8")
        parsed = json.loads(text)
        assert parsed["embedding"]["dense"]["model"] == "text-embedding-3-small"
        assert parsed["embedding"]["dense"]["api_key"] == "${" + SECRET_ENV_VAR + "}"
        assert parsed["embedding"]["dense"]["input"] == "text"
        # the store fixes its dimension at creation: declaring it is not cosmetic
        assert parsed["embedding"]["dense"]["dimension"] == 1536
        assert FAKE_KEY not in text
        assert handle["embedding"] == "text-embedding-3-small"
    finally:
        stop_server(handle["proc"], handle["port"])


def test_an_instance_without_embedding_model_omits_the_block(tmp_path: Path,
                                                             fake_binary: Path):
    from kuyen.projection.openviking import start_isolated_server, stop_server

    handle = start_isolated_server(tmp_path / "inst", server_bin=fake_binary,
                                   health_timeout=20.0,
                                   vlm=config(embedding_model=None))
    try:
        parsed = json.loads(handle["config_path"].read_text(encoding="utf-8"))
        assert "embedding" not in parsed
    finally:
        stop_server(handle["proc"], handle["port"])


def test_environment_reference_is_used_and_os_environ_is_untouched(tmp_path: Path, fake_binary: Path):
    from kuyen.projection.openviking import start_isolated_server, stop_server

    before = dict(os.environ)
    handle = start_isolated_server(tmp_path / "inst", server_bin=fake_binary,
                                   health_timeout=20.0, vlm=config())
    try:
        assert handle["vlm_secret_env"] == SECRET_ENV_VAR
        assert handle["child_env_keys"] == [SECRET_ENV_VAR]
        assert SECRET_ENV_VAR not in os.environ
        assert dict(os.environ) == before
        assert handle["vlm"]["credential_reference"] == "${" + SECRET_ENV_VAR + "}"
    finally:
        stop_server(handle["proc"], handle["port"])


# 7 ---------------------------------------------------------------------------
def test_secret_reaches_only_the_child_environment(tmp_path: Path, fake_binary: Path, monkeypatch):
    from kuyen.projection.openviking import start_isolated_server, stop_server

    dump = tmp_path / "child_env.json"
    monkeypatch.setenv("FAKE_ENV_DUMP", str(dump))
    handle = start_isolated_server(tmp_path / "inst", server_bin=fake_binary,
                                   health_timeout=20.0, vlm=config())
    try:
        deadline = time.time() + 10
        while not dump.exists() and time.time() < deadline:
            time.sleep(0.05)
        child = json.loads(dump.read_text(encoding="utf-8"))
        assert child[SECRET_ENV_VAR] == FAKE_KEY
        assert child["OPENVIKING_CONFIG_FILE"] == str(handle["config_path"])
        assert SECRET_ENV_VAR not in os.environ
    finally:
        stop_server(handle["proc"], handle["port"])
        dump.unlink(missing_ok=True)


# 12 --------------------------------------------------------------------------
def test_embedding_provider_may_differ_from_the_inference_provider(tmp_path: Path,
                                                                  fake_binary: Path,
                                                                  monkeypatch):
    """One inference configuration, two providers where the platform requires it.

    DeepSeek publishes no embedding endpoint (measured: HTTP 404 on /v1/embeddings), so the
    embedding block may keep its own base URL and credential. It is the same configuration
    object; only the embedding model and its credential differ, and neither is ever written
    to `ov.conf` or to `os.environ` of the caller.
    """
    from kuyen.projection.openviking import start_isolated_server, stop_server
    from kuyen.vlm import EMBEDDING_SECRET_ENV_VAR

    monkeypatch.setenv("KUYEN_TEST_EMBEDDING_KEY", "sk-embedding-offline")
    cfg = config(api_base="https://api.deepseek.com/v1",
                 embedding_api_base="https://api.openai.com/v1",
                 embedding_api_key_env="KUYEN_TEST_EMBEDDING_KEY")
    assert cfg.embedding_secret_source() == "environment:KUYEN_TEST_EMBEDDING_KEY"
    assert cfg.resolve_embedding_secret() == "sk-embedding-offline"
    handle = start_isolated_server(tmp_path / "inst", server_bin=fake_binary,
                                   health_timeout=20.0, vlm=cfg)
    try:
        text = handle["config_path"].read_text(encoding="utf-8")
        parsed = json.loads(text)
        assert parsed["vlm"]["api_base"] == "https://api.deepseek.com/v1"
        assert parsed["vlm"]["api_key"] == "${" + SECRET_ENV_VAR + "}"
        assert parsed["embedding"]["dense"]["api_base"] == "https://api.openai.com/v1"
        assert parsed["embedding"]["dense"]["api_key"] == "${" + EMBEDDING_SECRET_ENV_VAR + "}"
        assert "sk-embedding-offline" not in text
        assert handle["embedding_secret_env"] == EMBEDDING_SECRET_ENV_VAR
        assert set(handle["child_env_keys"]) == {SECRET_ENV_VAR, EMBEDDING_SECRET_ENV_VAR}
        assert "sk-embedding-offline" not in json.dumps(handle["vlm"])
    finally:
        stop_server(handle["proc"], handle["port"])


def test_a_missing_embedding_credential_fails_closed(tmp_path: Path, fake_binary: Path,
                                                     monkeypatch):
    from kuyen.projection.openviking import start_isolated_server

    monkeypatch.delenv("KUYEN_TEST_EMBEDDING_KEY", raising=False)
    cfg = config(embedding_api_key_env="KUYEN_TEST_EMBEDDING_KEY")
    with pytest.raises(VlmConfigurationError) as caught:
        start_isolated_server(tmp_path / "inst", server_bin=fake_binary, health_timeout=5.0,
                              vlm=cfg)
    assert "KUYEN_TEST_EMBEDDING_KEY" in caught.value.message
    assert not (tmp_path / "inst" / "ov.conf").exists()
