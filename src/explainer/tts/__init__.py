"""Swappable speech engines. Add one by implementing `synthesize(text)` and registering it here."""
from __future__ import annotations

from .base import TTSEngine


def _kokoro(**kw):
    from .kokoro_engine import KokoroEngine

    return KokoroEngine(**kw)


def _azure(**kw):
    from .azure_engine import AzureEngine

    return AzureEngine(**kw)


ENGINES = {"kokoro": _kokoro, "azure": _azure}


def get_engine(name: str, **options) -> TTSEngine:
    if name not in ENGINES:
        raise ValueError(f"unknown TTS engine {name!r}; available: {', '.join(ENGINES)}")
    return ENGINES[name](**options)
