"""Single, explicit version resolution for KÜYEN.

There is exactly one source of truth for the version: the ``VERSION`` file at the
project root. ``pyproject.toml`` reads it at build time (``dynamic = ["version"]``),
so distribution metadata, ``kuyen.__version__`` and the engine's internal
implementation version all derive from the same string.

Resolution order, and why:

1. **Source checkout** — if ``VERSION`` exists in the project root above this module,
   that file is authoritative. Doing this *first* prevents a stale installed
   distribution elsewhere in the environment from masking the checkout version.
2. **Installed distribution** — otherwise read ``importlib.metadata.version("kuyen")``,
   which is the authoritative version of an installed wheel/sdist.
3. **Neither** — raise. A silent numeric fallback is exactly what made an installed
   KÜYEN 0.1.9 report ``0.1.2``; it must never happen again.
"""
from __future__ import annotations

from pathlib import Path

#: Error message used when no version source is reachable.
UNAVAILABLE = (
    "KÜYEN version unavailable: no VERSION file in the source tree and no installed "
    "distribution metadata. Refusing to fall back to a guessed version."
)


def version_file_path() -> Path:
    """Location of the source-tree ``VERSION`` file (may not exist when installed)."""
    return Path(__file__).resolve().parents[2] / "VERSION"


def resolve_version() -> str:
    """Return the KÜYEN version, or raise ``RuntimeError`` if it cannot be determined."""
    source = version_file_path()
    if source.is_file():
        value = source.read_text(encoding="utf-8").strip()
        if value:
            return value
        raise RuntimeError(f"{UNAVAILABLE} (VERSION file is empty: {source})")

    try:
        from importlib.metadata import PackageNotFoundError, version
    except Exception as exc:  # pragma: no cover - importlib.metadata is stdlib >=3.8
        raise RuntimeError(UNAVAILABLE) from exc

    try:
        installed = version("kuyen")
    except PackageNotFoundError as exc:
        raise RuntimeError(UNAVAILABLE) from exc
    if not installed:
        raise RuntimeError(UNAVAILABLE)
    return installed


def version_source() -> str:
    """Describe which mechanism produced the current version (for provenance)."""
    if version_file_path().is_file():
        return "source_tree_version_file"
    return "distribution_metadata"
