from __future__ import annotations

from typing import Protocol

import numpy as np


class TTSEngine(Protocol):
    """A speech engine turns one piece of text into mono float32 samples."""

    name: str

    def synthesize(self, text: str, speed: float | None = None) -> tuple[np.ndarray, int]:
        """Return (samples in [-1, 1] as float32, sample_rate)."""
        ...
