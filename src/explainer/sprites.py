"""Bit, the presenter: pixel-art body poses (64x64) with a separate mouth layer.

Body frames come from one sheet (poses.png + poses.json). The mouth is a second set of sheets
(mouth_fechada / meio / aberta) with the same layout, composited over the body, so the mouth can
follow the voice without changing the body pose.
"""
from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from pathlib import Path

from PIL import Image

CELL = 64
MOUTHS = ("fechada", "meio", "aberta")
SKY = (24, 30, 62, 255)  # screen color used when the eyes close


def _dir() -> Path:
    return Path(str(resources.files("explainer") / "assets" / "bit"))


@lru_cache(maxsize=1)
def _meta() -> dict:
    return json.loads((_dir() / "poses.json").read_text(encoding="utf-8"))["tags"]


def tag_names() -> list[str]:
    return list(_meta())


def tag_frames(tag: str) -> list[dict]:
    return _meta()[tag]


def tag_duration_ms(tag: str) -> int:
    return sum(f["ms"] for f in _meta()[tag])


def locate(tag: str, ms: float, loop: bool = True) -> int:
    """Index (within the tag) of the frame showing at `ms` after the tag started."""
    frames = _meta()[tag]
    total = sum(f["ms"] for f in frames)
    ms = ms % total if loop else min(max(ms, 0), total - 1)
    for k, f in enumerate(frames):
        if ms < f["ms"]:
            return k
        ms -= f["ms"]
    return len(frames) - 1


def _closed_eyes(im: Image.Image, mouth_top: int) -> Image.Image | None:
    """Return a copy with the eyes closed (a thin line), or None if the eyes are not open."""
    px = im.load()
    eyes = [(x, y) for y in range(14, min(mouth_top - 1, 26)) for x in range(18, 46)
            if px[x, y][3] and px[x, y][1] >= 190 and px[x, y][2] >= 190 and px[x, y][0] <= 150]
    if len(eyes) < 12:
        return None
    out = im.copy()
    op = out.load()
    bottom = {}
    for x, y in eyes:
        bottom[x] = max(bottom.get(x, y), y)
        op[x, y] = SKY
    for x, y in bottom.items():
        op[x, y] = im.getpixel((x, y))
    return out


class Bit:
    """Pose frames with mouth, blink and breathing applied; cached, scaled with nearest neighbour."""

    def __init__(self, scale: int = 8):
        self.scale = scale
        d = _dir()
        self._sheet = Image.open(d / "poses.png").convert("RGBA")
        self._mouth = {m: Image.open(d / f"mouth_{m}.png").convert("RGBA") for m in MOUTHS}
        self._cache: dict = {}
        self._base: dict = {}

    def _cell(self, sheet: Image.Image, i: int) -> Image.Image:
        cols = sheet.width // CELL
        x, y = (i % cols) * CELL, (i // cols) * CELL
        return sheet.crop((x, y, x + CELL, y + CELL))

    def _body(self, tag: str, k: int, mouth: str) -> Image.Image:
        key = (tag, k, mouth)
        if key not in self._base:
            i = _meta()[tag][k]["i"]
            im = self._cell(self._sheet, i)
            im.alpha_composite(self._cell(self._mouth[mouth], i))
            self._base[key] = im
        return self._base[key]

    def frame(self, tag: str, k: int, mouth: str = "fechada", blink: bool = False, lift: int = 0) -> Image.Image:
        """Scaled RGBA frame. `lift` (0 or 1) raises the upper body one source pixel (breathing)."""
        key = (tag, k, mouth, blink, lift)
        if key in self._cache:
            return self._cache[key]
        im = self._body(tag, k, mouth)
        if blink:
            closed = _closed_eyes(im, 25)
            im = closed if closed is not None else im
        if lift:
            out = im.copy()
            top = im.crop((0, 0, CELL, 50))
            out.paste(top, (0, -lift))  # rows 50-lift..49 keep the original pixels (no gap)
            im = out
        big = im.resize((CELL * self.scale, CELL * self.scale), Image.NEAREST)
        self._cache[key] = big
        return big


@lru_cache(maxsize=4)
def sole_shifts(tag: str) -> tuple[int, ...]:
    """How far (sprite pixels) the soles move between each frame of a walk tag and the next one (wraps around).

    Measured on the two bottom rows of the sheet: the shift that best lines the soles of frame k up with
    frame k+1. This is how far the body must travel while frame k shows so the supporting foot does not skate.
    """
    import numpy as np

    sheet = Image.open(_dir() / "poses.png").convert("RGBA")
    frames = []
    for f in _meta()[tag]:
        i = f["i"]
        x, y = (i % 16) * CELL, (i // 16) * CELL
        a = np.array(sheet.crop((x, y, x + CELL, y + CELL)))[:, :, 3] > 0
        frames.append(a[56:59])
    out = []
    for k, a in enumerate(frames):
        b = frames[(k + 1) % len(frames)]
        best = min(range(-8, 9), key=lambda s: ((a != np.roll(b, -s, axis=1)).sum(), abs(s)))
        out.append(abs(best))
    return tuple(out)
