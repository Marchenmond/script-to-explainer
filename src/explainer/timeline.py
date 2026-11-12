"""Per-frame state of the video: where Bit is, which pose layers show, camera, slide progress.

The renderer only draws what `Stage.state(q)` says, so new things (walking across the stage,
camera moves, spring text) can be added by extending the state instead of rewriting the renderer.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import numpy as np

from . import audio as A
from .direction import Choreography
from .slides import H, W
from .sprites import MOUTHS

BIT_CENTER_X = 1090 + 810 // 2     # default stand position on the right side of the stage
BIT_FEET_Y = 850


@dataclass
class BitState:
    layers: list[tuple[str, int, float]]      # (tag, frame index, weight) - body poses, weights sum to 1
    mouth: str = "fechada"                    # fechada | meio | aberta
    blink: bool = False
    lift: int = 0                             # breathing: raise the upper body by this many source pixels
    x: float = BIT_CENTER_X                   # center of the sprite, screen pixels
    y: float = BIT_FEET_Y                     # feet line, screen pixels
    facing: str = "w"                         # w = faces the slide (left), e = faces right


@dataclass
class Camera:
    zoom: float = 1.0
    cx: float = W / 2
    cy: float = H / 2

    @property
    def identity(self) -> bool:
        return abs(self.zoom - 1.0) < 1e-6 and abs(self.cx - W / 2) < 0.5 and abs(self.cy - H / 2) < 0.5


@dataclass
class FrameState:
    q: int
    t: float
    scene: int
    scene_t: float                 # seconds since the scene started
    lead: float
    fade: float
    bit: BitState
    camera: Camera = field(default_factory=Camera)


def blink_times(total: float, every=(2.8, 4.5), seed: int = 7) -> list[float]:
    rng = random.Random(seed)
    t, out = rng.uniform(*every), []
    while t < total:
        out.append(t)
        t += rng.uniform(*every)
    return out


class Stage:
    def __init__(self, timeline, leads: list[float], track: np.ndarray, fps: int, choreo: Choreography):
        self.timeline, self.leads, self.fps, self.choreo = timeline, leads, fps, choreo
        self.levels = A.mouth_levels(track, fps)
        self.total = len(track) / A.SR
        idle = choreo.cfg["idle"]
        self.idle = idle
        self.blinks = blink_times(self.total + 1, tuple(idle["blink_every_s"]))
        self._scene = 0

    def scene_at(self, t: float) -> int:
        tl = self.timeline
        i = self._scene if t >= tl[self._scene][0] else 0
        while i < len(tl) - 1 and t >= tl[i][0] + tl[i][1]:
            i += 1
        self._scene = i
        return i

    def state(self, q: int) -> FrameState:
        t = q / self.fps
        i = self.scene_at(t)
        start, total, _a = self.timeline[i]
        st = t - start
        fade = max(0.0, min(1.0, st / 0.25, (total - st) / 0.25))
        idle = self.idle
        sway = idle["sway_px"] * math.sin(2 * math.pi * t / 6.0)
        breathe = math.sin(2 * math.pi * t / idle["breathe_period_s"])
        lift = int(idle["breathe_px"]) if breathe > 0.0 else 0
        level = int(self.levels[q]) if q < len(self.levels) else 0
        blink = any(b <= t < b + 0.12 for b in self.blinks)
        walking = any(g.kind == "walk" for g in self.choreo.active(t))
        bit = BitState(
            layers=self.choreo.layers(t),
            mouth=MOUTHS[level],
            blink=blink and not walking,
            lift=0 if walking else lift,
            x=BIT_CENTER_X + sway + self.choreo.x_offset(t),
            y=BIT_FEET_Y + self.choreo.y_offset(t),
            facing=self.choreo.facing(t),
        )
        return FrameState(q, t, i, st, self.leads[i], fade, bit)
