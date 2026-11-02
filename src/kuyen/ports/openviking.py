"""Provider boundary. The core depends on this protocol, never on SDK internals."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..models import CandidateBundle, Mapu


@dataclass
class TaskSnapshot:
    task_id: str
    status: str
    raw: dict[str, Any]


class OpenVikingPort(Protocol):
    async def health(self) -> dict[str, Any]: ...

    async def ensure_source(self, mapu: Mapu, container_uri: str) -> str: ...

    async def verify_source(self, mapu: Mapu, uri: str) -> None: ...

    async def wait_processed(self, timeout_s: float) -> dict[str, Any]: ...

    async def ensure_skill(self, skill_dir: str, target_uri: str) -> str: ...

    async def compile(self, *, from_uris: list[str], to_uri: str, skill_uri: str, instruction: str) -> str: ...

    async def wait_task(self, task_id: str, timeout_s: float) -> TaskSnapshot: ...

    async def read_candidate(self, output_uri: str) -> CandidateBundle: ...

    async def close(self) -> None: ...
