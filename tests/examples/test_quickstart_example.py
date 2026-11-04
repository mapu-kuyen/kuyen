"""The shipped quickstart must run, and its evidence must cite its own MAPU.

KUYEN_RELEASE_QUICKSTART_REPAIR_02. The example called `build_document` without
`source_uris`, so the MAPU received the default URI while every evidence record cited
another one. Hardening A1 rejects that inconsistency with `EVIDENCE_URI_MISMATCH`, and
the example only failed at the moment a real user ran it — no test executed it.

These tests close that gap without touching private details:

* they run the example exactly as a user does (a subprocess, working directory outside
  the repository, the package importable as the ordinary product suite has it);
* they then open the memory it produced through the public API and check the provenance
  contract itself (each evidence cites the source URI of its own MAPU), rather than
  matching printed text.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from kuyen import KuyenMemory

REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "examples" / "quickstart.py"


def run_example(target: Path) -> subprocess.CompletedProcess:
    """Run the quickstart the way an external user does: outside the source tree."""
    env = dict(os.environ)
    env.pop("KUYEN_RUN_OPENVIKING", None)
    # A source checkout is not an installed package: the product suite itself runs with
    # `pythonpath = ["src"]`, so the example gets the same path and nothing more.
    env["PYTHONPATH"] = str(REPO / "src")
    return subprocess.run([sys.executable, str(EXAMPLE), str(target)], cwd=str(target),
                          env=env, capture_output=True, text=True, timeout=300)


@pytest.fixture()
def example_run(tmp_path: Path) -> tuple[subprocess.CompletedProcess, Path]:
    target = tmp_path / "demo"
    target.mkdir()
    return run_example(target), target


class TestQuickstartExecutes:
    def test_it_exits_zero_without_the_uri_mismatch(self,
                                                    example_run: tuple[subprocess.CompletedProcess, Path]) -> None:
        result, _ = example_run
        assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        assert "EVIDENCE_URI_MISMATCH" not in (result.stdout + result.stderr)

    def test_it_reports_a_validated_antu_and_a_verified_memory(self,
                                                               example_run: tuple[subprocess.CompletedProcess, Path]) -> None:
        result, _ = example_run
        assert "VALIDATED" in result.stdout
        assert "verify: ok=True" in result.stdout
        assert "accepted=True" in result.stdout
        assert "provenance:" in result.stdout


class TestQuickstartProvenanceContract:
    def test_it_commits_two_versions_that_verify(self,
                                                 example_run: tuple[subprocess.CompletedProcess, Path]) -> None:
        _, target = example_run
        memory = KuyenMemory.open(target / "memory")
        assert len(memory.versions()) == 2
        assert memory.current() is not None
        assert memory.current().parent_version_id is not None
        assert memory.verify()["ok"] is True

    def test_every_evidence_cites_the_source_uri_of_its_own_mapu(self,
                                                                 example_run: tuple[subprocess.CompletedProcess, Path]) -> None:
        _, target = example_run
        sidecar = KuyenMemory.open(target / "memory").sidecar()
        source_uris = {mapu["mapu_id"]: mapu["source_uri"] for mapu in sidecar["mapus"]}
        evidence = sidecar["canonical"]["evidence"]
        assert evidence, "the example must demonstrate evidence"
        for item in evidence:
            assert item["source_uri"] == source_uris[item["mapu_id"]], (
                f"evidence {item['evidence_id']} cites {item['source_uri']} but its MAPU "
                f"{item['mapu_id']} declares {source_uris[item['mapu_id']]}")

    def test_each_claim_resolves_to_its_quote_in_the_source(self,
                                                             example_run: tuple[subprocess.CompletedProcess, Path]) -> None:
        _, target = example_run
        memory = KuyenMemory.open(target / "memory")
        graph = memory.graph()
        claims = ([entity["entity_id"] for entity in graph["entities"]]
                  + [relation["relation_id"] for relation in graph["relations"]]
                  + [assertion["assertion_id"] for assertion in graph["assertions"]])
        checked = 0
        for claim_id in claims:
            for item in memory.trace(claim_id)["evidence"]:
                unit = memory.source_unit(item["source_unit_id"])
                assert unit["mapu_id"] == item["mapu_id"], (
                    f"claim {claim_id} cites {item['mapu_id']} but resolved SOURCE_UNIT "
                    f"{item['source_unit_id']} belongs to {unit['mapu_id']}")
                assert unit["content"][item["char_start"]:item["char_end"]] == item["quote"]
                checked += 1
        assert checked >= 2, "the example must resolve evidence for both documents"
