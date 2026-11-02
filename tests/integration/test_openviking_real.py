"""Opt-in real OpenViking integration.

Default: skipped. Enable only with an isolated server, a pre-ingested source URI
and a service key in the environment. A skipped test is not evidence of a real
compilation.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from kuyen.adapters.openviking import SdkOpenVikingAdapter
from kuyen.config import KuyenConfig
from kuyen.engine import KuyenEngine
from tests.helpers import actor, antu, mapu

import kuyen as _kuyen


def _package_root() -> Path:
    """Directory of the installed package (assets ship as package data)."""
    return Path(_kuyen.__file__).resolve().parent



ROOT = _package_root()
ENABLED = os.environ.get("KUYEN_RUN_OPENVIKING") == "1"


@unittest.skipUnless(ENABLED, "set KUYEN_RUN_OPENVIKING=1 and provider credentials for real integration")
class RealOpenVikingTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_against_isolated_openviking(self) -> None:
        url = os.environ.get("KUYEN_OPENVIKING_URL", "")
        key = os.environ.get("KUYEN_OPENVIKING_API_KEY", "")
        source_uri = os.environ.get("KUYEN_OPENVIKING_SOURCE_URI", "")
        if not url or not key or not source_uri:
            self.skipTest("KUYEN_OPENVIKING_URL/API_KEY/SOURCE_URI are required")
        m = mapu()
        m = type(m)(**{**m.__dict__, "source_uri": source_uri})
        with tempfile.TemporaryDirectory() as tmp:
            adapter = SdkOpenVikingAdapter(url=url, api_key=key, timeout_s=60, poll_interval_s=3)
            engine = KuyenEngine(
                KuyenConfig(
                    data_dir=Path(tmp) / "data",
                    ontology_path=ROOT / "config" / "ontologies" / "generic-v1.yaml",
                    skill_dir=ROOT / "skills" / "knowledge-graph",
                    openviking_url=url,
                ),
                adapter=adapter,
            )
            try:
                result = await engine.build_async(
                    antu=antu(), mapu_sources=[m], actor=actor(),
                    instruction="Use the KÜYEN evidence sidecar and preserve exact quotes.",
                )
            finally:
                await engine.close()
            self.assertIn(result.status, {"ACCEPTED", "REJECTED"})
            self.assertTrue(result.request_key.startswith("req_"))
