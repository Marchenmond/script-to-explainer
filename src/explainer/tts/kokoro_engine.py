"""Default engine: Kokoro, running locally through ONNX (no network at render time)."""
from __future__ import annotations

import os
import urllib.request
from pathlib import Path

import numpy as np

BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
FILES = ("kokoro-v1.0.onnx", "voices-v1.0.bin")


def model_dir() -> Path:
    d = os.environ.get("EXPLAINER_MODELS")
    return Path(d) if d else Path.cwd() / "models"


def ensure_models() -> tuple[Path, Path]:
    d = model_dir()
    d.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        if not (d / f).exists():
            print(f"downloading {f} (one time only) ...")
            urllib.request.urlretrieve(BASE + f, d / f)
    return d / FILES[0], d / FILES[1]


class KokoroEngine:
    name = "kokoro"

    def __init__(self, voice: str = "af_heart", speed: float = 1.0, lang: str = "en-us", **_):
        from kokoro_onnx import Kokoro

        model, voices = ensure_models()
        self._k = Kokoro(str(model), str(voices))
        self.voice, self.speed, self.lang = voice, float(speed), lang

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        samples, sr = self._k.create(text, voice=self.voice, speed=self.speed, lang=self.lang)
        return np.asarray(samples, dtype=np.float32), int(sr)
