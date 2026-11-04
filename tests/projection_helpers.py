"""Minimal OpenViking-shaped engine for the projection tests.

It implements the three calls the projection layer uses (`mkdir`, `write`, `read`), keeps
the bundle in memory, can be slowed down so two runners overlap deterministically, and can
fail after a number of writes to simulate an interrupted engine.
"""
from __future__ import annotations

import threading
import time
from typing import Any


class Response:
    def __init__(self, ok: bool, result: Any = None, error: str | None = None) -> None:
        self.ok = ok
        self.result = result
        self.error_message = error


class FakeEngine:
    def __init__(self, *, delay: float = 0.02, fail_after: int | None = None) -> None:
        self.files: dict[str, str] = {}
        self.writes = 0
        self.delay = delay
        self.fail_after = fail_after
        self._lock = threading.Lock()

    def mkdir(self, uri: str) -> Response:
        return Response(True)

    def write(self, uri: str, text: str) -> Response:
        if self.fail_after is not None:
            with self._lock:
                if self.writes >= self.fail_after:
                    raise RuntimeError("simulated engine failure")
        time.sleep(self.delay)
        with self._lock:
            self.writes += 1
            self.files[uri] = text
        return Response(True)

    def read(self, uri: str) -> Response:
        return Response(uri in self.files, self.files.get(uri))
