"""`write_atomic` under concurrent writers and interruptions (front 2).

KUYEN_TRANSACTION_BOUNDARY_HARDENING_03. The primitive promises an atomic replacement:
the destination holds the old content or the new one, never a mixture, and a temporary is
never presented as a result. Two threads of the same process share the PID, so a temporary
name derived only from the PID cannot distinguish them.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

import kuyen.canonical as canonical_module
from kuyen.canonical import write_atomic

ROUNDS = 12
PAYLOAD_A = b"A" * (2 * 1024 * 1024)
PAYLOAD_B = b"B" * (2 * 1024 * 1024)


def leftovers(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.glob(".tmp-*"))


class _OsShim:
    """Delegating os proxy that fails only where the test wants it to fail."""

    def __init__(self, real, *, fail: str) -> None:
        self._real = real
        self._fail = fail

    def __getattr__(self, name):
        if name == self._fail:
            def boom(*args, **kwargs):
                raise OSError(f"simulated interruption in os.{name}")

            return boom
        return getattr(self._real, name)


class TestSameDestination:
    def test_two_threads_never_publish_a_mixed_or_partial_file(self, tmp_path: Path) -> None:
        target = tmp_path / "shared.bin"
        for round_index in range(ROUNDS):
            barrier = threading.Barrier(2)
            errors: list[str] = []

            def run(payload: bytes) -> None:
                try:
                    barrier.wait(timeout=20)
                    write_atomic(target, payload)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{type(exc).__name__}: {exc}")

            threads = [threading.Thread(target=run, args=(payload,))
                       for payload in (PAYLOAD_A, PAYLOAD_B)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=60)

            assert errors == [], f"round {round_index}: {errors}"
            published = target.read_bytes()
            assert published in (PAYLOAD_A, PAYLOAD_B), (
                f"round {round_index}: the destination is a mixture ({len(published)} bytes)")
            assert len(published) == len(PAYLOAD_A)
            assert leftovers(tmp_path) == [], f"round {round_index}: {leftovers(tmp_path)}"

    def test_two_threads_writing_different_destinations_both_succeed(self, tmp_path: Path) -> None:
        barrier = threading.Barrier(2)
        errors: list[str] = []

        def run(name: str, payload: bytes) -> None:
            try:
                barrier.wait(timeout=20)
                write_atomic(tmp_path / name, payload)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=run, args=("a.bin", PAYLOAD_A)),
                   threading.Thread(target=run, args=("b.bin", PAYLOAD_B))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        assert errors == []
        assert (tmp_path / "a.bin").read_bytes() == PAYLOAD_A
        assert (tmp_path / "b.bin").read_bytes() == PAYLOAD_B
        assert leftovers(tmp_path) == []


def test_two_processes_writing_the_same_destination(tmp_path: Path) -> None:
    """Cross-process names differ by PID; this guards the property anyway."""
    target = tmp_path / "shared.bin"
    script = tmp_path / "writer.py"
    script.write_text(textwrap.dedent(
        '''
        import sys, time
        from pathlib import Path
        sys.path.insert(0, sys.argv[1])
        from kuyen.canonical import write_atomic
        target, letter, go = Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4])
        deadline = time.time() + 30
        while not go.exists():
            if time.time() > deadline:
                raise SystemExit("barrier timeout")
            time.sleep(0.01)
        write_atomic(target, letter.encode() * (2 * 1024 * 1024))
        '''), encoding="utf-8")
    go = tmp_path / "go"
    package_root = str(Path(__file__).resolve().parents[2] / "src")
    processes = [subprocess.Popen([sys.executable, str(script), package_root, str(target), letter,
                                   str(go)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True) for letter in ("C", "D")]
    go.write_text("go", encoding="utf-8")
    results = [process.communicate(timeout=120) for process in processes]

    assert all(process.returncode == 0 for process in processes), results
    published = target.read_bytes()
    assert published in (b"C" * (2 * 1024 * 1024), b"D" * (2 * 1024 * 1024))
    assert leftovers(tmp_path) == []


class TestTemporaries:
    def test_an_abandoned_temporary_is_ignored_and_never_published(self, tmp_path: Path) -> None:
        """A leftover temporary is inert: it is not read, not published and not deleted.

        It is not removed on purpose: a temporary of another live writer must never be
        deleted by a write that does not own it. It can only be swept by an explicit
        maintenance step, which this package does not have.
        """
        target = tmp_path / "target.json"
        target.write_text('{"old": true}', encoding="utf-8")
        abandoned = tmp_path / f".tmp-{target.name}-{os.getpid()}"
        abandoned.write_text("restos de una ejecución anterior", encoding="utf-8")

        write_atomic(target, '{"new": true}')

        assert target.read_text(encoding="utf-8") == '{"new": true}'
        assert abandoned.read_text(encoding="utf-8") == "restos de una ejecución anterior"
        assert leftovers(tmp_path) == [abandoned.name]
        assert not target.read_text(encoding="utf-8").startswith("restos")

    def test_interruption_before_the_replacement_keeps_the_destination_and_no_temporary(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        target = tmp_path / "target.json"
        target.write_text("contenido anterior", encoding="utf-8")
        monkeypatch.setattr(canonical_module, "_os", _OsShim(canonical_module._os, fail="replace"))

        with pytest.raises(OSError):
            write_atomic(target, "contenido nuevo")

        assert target.read_text(encoding="utf-8") == "contenido anterior"
        assert leftovers(tmp_path) == [], "a failed write must not leave a temporary behind"

    def test_interruption_after_the_replacement_publishes_a_complete_file(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        target = tmp_path / "target.json"
        target.write_text("contenido anterior", encoding="utf-8")
        monkeypatch.setattr(canonical_module, "fsync_dir", _OsShim(canonical_module._os, fail="fsync").fsync)

        with pytest.raises(OSError):
            write_atomic(target, "contenido nuevo")

        assert target.read_text(encoding="utf-8") == "contenido nuevo"
        assert leftovers(tmp_path) == []
