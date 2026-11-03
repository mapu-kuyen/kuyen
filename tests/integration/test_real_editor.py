"""Opt-in integration with a real editor model (§8.2, last paragraph).

Default: **skipped**. Enable only with an explicit provider, model and credential:

    KUYEN_RUN_REAL_MODEL=1 \
    KUYEN_EDITOR_MODEL=gpt-4.1-mini \
    KUYEN_EDITOR_ENDPOINT=https://api.openai.com/v1 \
    KUYEN_EDITOR_API_KEY_ENV=OPENAI_API_KEY \
    python -m pytest tests/integration/test_real_editor.py

A skipped test is not evidence of a real inference. This file exists so the capability is
executable and auditable the moment the environment is available; it records provider,
model, temperature, the proposal and the usage the provider reports, and it makes exactly
one call — no retries, no loop.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from kuyen.editing import EditorConfig, OpenAICompatibleGraphEditor
from tests.editing import helpers as h

ENABLED = os.environ.get("KUYEN_RUN_REAL_MODEL") == "1"
REPORT = Path(__file__).resolve().parents[2] / "experiments/KUYEN_PRODUCTIVE_GRAPH_AND_ANTU_VERSIONING_11/evidence/real_model_inference.json"

pytestmark = pytest.mark.skipif(
    not ENABLED, reason="set KUYEN_RUN_REAL_MODEL=1 with a configured KUYEN_EDITOR_* provider")


def test_a_real_model_proposes_and_kuyen_versions_it(tmp_path) -> None:
    memory = h.memory_at(tmp_path)
    identifiers = h.ids(memory)
    config = EditorConfig.from_env()
    editor = OpenAICompatibleGraphEditor(config)
    instruction = ("Cambia la cantidad de luminarias instaladas de 12 a 18: "
                   "el dato correcto es 18")
    result = memory.apply_antu(
        instruction, editor=editor,
        actor={"leftraru_id": "LR-REAL", "authenticated_user": "integration",
               "authenticated_account": "integration", "service_identity": "svc-kuyen"})
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({
        "provider": config.public_dict(),
        "instruction": instruction,
        "result": result.to_dict(),
        "base_version_id": result.base_version_id,
        "version_id": result.version_id,
        "status": result.status,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    assert result.status in ("COMMITTED", "CLARIFICATION_REQUIRED", "REJECTED"), result.to_dict()
    if result.status == "COMMITTED":
        graph = memory.graph()
        assert graph["provenance"]["edits"][-1]["model"]["model"] == config.model
        assert len(memory.versions()) == 2
        assert memory.verify()["ok"]
