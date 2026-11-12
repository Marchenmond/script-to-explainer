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


DEFAULT_VOICE = "am_fenrir"


def parse_mix(spec: str) -> list[tuple[str, float]]:
    """'am_puck:0.7,am_fenrir:0.3' -> [('am_puck', 0.7), ('am_fenrir', 0.3)] (weights are normalized)."""
    parts = []
    for item in spec.split(","):
        name, _, w = item.strip().partition(":")
        if not name:
            raise ValueError(f"bad voice mix {spec!r}")
        parts.append((name, float(w) if w else 1.0))
    total = sum(w for _, w in parts)
    if total <= 0:
        raise ValueError(f"voice mix weights must be positive: {spec!r}")
    return [(n, w / total) for n, w in parts]


class KokoroEngine:
    name = "kokoro"

    def __init__(self, voice: str = DEFAULT_VOICE, speed: float = 1.0, lang: str = "en-us", **_):
        from kokoro_onnx import Kokoro

        model, voices = ensure_models()
        self._k = Kokoro(str(model), str(voices))
        self.voice, self.speed, self.lang = voice, float(speed), lang
        mix = parse_mix(voice)
        self._style = voice if len(mix) == 1 else sum(w * self._k.get_voice_style(n) for n, w in mix)

    def synthesize(self, text: str, speed: float | None = None) -> tuple[np.ndarray, int]:
        samples, sr = self._k.create(text, voice=self._style, speed=self.speed if speed is None else speed, lang=self.lang)
        return np.asarray(samples, dtype=np.float32), int(sr)
