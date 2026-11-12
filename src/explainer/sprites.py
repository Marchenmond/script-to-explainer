"""Bit, the presenter: pixel-art frames (64x64) with per-frame durations in ms."""
from __future__ import annotations

from importlib import resources
from pathlib import Path

from PIL import Image

# tag -> frame durations (ms)
TAGS = {
    "parada_s": [900, 450, 110, 450, 110],
    "falando_s": [110, 100, 120, 100],
    "feliz_s": [140, 100, 90, 110, 90, 100],
    "pensando_s": [450, 350, 450, 140],
    "surpresa_s": [70, 70, 70, 70],
}
# script emotion -> idle tag ("pointing" reuses the arm-out pose)
EMOTION_TAG = {"neutral": "parada_s", "happy": "feliz_s", "thinking": "pensando_s", "pointing": "surpresa_s"}
TALK_TAG = "falando_s"


def _dir() -> Path:
    return Path(str(resources.files("explainer") / "assets" / "sprites"))


class Bit:
    def __init__(self, scale: int = 8):
        self.scale = scale
        self._cache: dict = {}

    def frame(self, tag: str, ms: int) -> Image.Image:
        dur = TAGS[tag]
        ms %= sum(dur)
        i = 0
        while ms >= dur[i]:
            ms -= dur[i]
            i += 1
        key = (tag, i)
        if key not in self._cache:
            im = Image.open(_dir() / f"anim_{tag}_{i + 1}.png").convert("RGBA")
            self._cache[key] = im.resize((im.width * self.scale, im.height * self.scale), Image.NEAREST)
        return self._cache[key]
