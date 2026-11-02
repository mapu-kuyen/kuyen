"""Optional adapters.

Nothing here is imported when the core is imported: the OpenViking adapters need an HTTP
client and a running server, and the core must work without either.
"""
from __future__ import annotations

_LAZY = {"SdkOpenVikingAdapter": ".openviking",
         "SdkOpenVikingPublicationAdapter": ".openviking_publication"}

__all__ = sorted(_LAZY)


def __getattr__(name: str):
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(module_name, __name__), name)
