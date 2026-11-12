"""Stage planner: where Bit stands and walks, which way he faces, the camera, and what the slide does.

The planner turns the script (cues anchored on spoken words) into `stage.json` (what the HTML
composition draws) and `stage.report.json` (one row per cue, with the timings the checks read).
Nothing here draws pixels.
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass

from . import audio as A
from . import direction as D
from . import sprites as SP
from .actions import ACTIONS, STAGE_ACTIONS
from .slides import caption_chunks

DEFAULT_STAGE = {
    "stations": {"off": 2080, "R": 1700, "H": 1500, "M": 1320, "N": 1180},
    "floor_y": 802,
    "walk": {"speed_px_s": 240, "stride_px": None, "accel_s": 0.20, "decel_s": 0.25, "min_move_px": 120,
             "min_speed_px_s": 200, "max_speed_px_s": 280, "settle_s": 0.15},
    "timing": {"anticipation_ms": 200, "sync_tolerance_ms": 250, "min_stay_s": 2.0, "max_stay_s": 7.0},
    "springs": {"FAST": [14, 0.70], "MORPH": [9, 0.80], "SOFT": [6, 0.85], "CAM": [4.5, 1.00], "POP": [16, 0.56]},
    "views": {
        "wide": {"cx": 960, "cy": 540, "zoom": 1.00},
        "slide": {"cx": 560, "cy": 550, "zoom": 1.10},
        "bit": {"cx": "bit_x", "cx_follow": 0.35, "cy": 600, "zoom": 1.10},
        "caption": {"cx": 960, "cy": 600, "zoom": 1.06},
    },
    "card_states": {
        "title": {"w": 980, "h": 750, "radius": 28, "border": "accent"},
        "bullets": {"w": 980, "h": 750, "radius": 28, "border": "accent", "side_bar": "warm"},
        "highlight": {"w": 980, "h": 560, "radius": 56, "border": "gold"},
    },
    "background": {"grid_drift_px_s": -8, "blobs_drift_px_s": 3, "parallax_cam": [0.5, 0.3], "parallax_bit": -0.03,
                   "parallax_bit_grid": -0.1},
    "idle_camera": {"zoom_to": 1.03, "period_s": 9, "pan_px": 12},
    "captions": {"bar": False, "style": "karaoke", "y": 940},
    "auto_rules": True,
}
AREA = (1090, 1900)
OFF_X = 2080


class StageError(ValueError):
    """The planned stage cannot be done (for example a walk that does not fit between two cues)."""


def merge(base: dict, over: dict | None) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def stage_settings(script) -> dict:
    return merge(DEFAULT_STAGE, script.stage)


# ------------------------------------------------------------------ walking profile


def walk_steps(stride_px=None, tag: str = "andando_w") -> list[float]:
    """Body distance (px) to cover while each of the 6 walk frames shows.

    Default: calibrated on the sprite, 8 px (one screen pixel block per sprite pixel) for every sprite pixel the
    soles move between two frames, at least 4 px, so the supporting foot stays put. A fixed `stride_px` gives six equal steps.
    """
    if stride_px:
        return [stride_px / 6] * 6
    return [max(8.0 * s, 4.0) for s in SP.sole_shifts(tag)]


def walk_frame(dist: float, steps: list[float]) -> int:
    d = dist % sum(steps)
    for k, st in enumerate(steps):
        if d < st:
            return k
        d -= st
    return len(steps) - 1


def walk_profile(dist: float, v: float, ta: float, td: float) -> tuple[float, float, float, float]:
    """Trapezoid: returns (cruise speed, accel s, decel s, total s) for a walk of `dist` px."""
    if dist <= 0:
        return v, ta, td, 0.0
    if dist < v * (ta + td) / 2:
        s = math.sqrt(dist / (v * (ta + td) / 2))
        v, ta, td = v * s, ta * s, td * s
    cruise = dist - v * (ta + td) / 2
    return v, ta, td, ta + td + cruise / v


def walk_duration(dist: float, v: float, ta: float, td: float) -> float:
    return walk_profile(dist, v, ta, td)[3]


@dataclass
class Move:
    t0: float
    x0: float
    x1: float
    v: float
    ta: float
    td: float
    kind: str = "walk"          # walk | shift (small weight shift, no steps)
    cue: str = ""
    station: str = ""
    scene: int = 0

    def __post_init__(self):
        self.dist = abs(self.x1 - self.x0)
        if self.kind == "shift":
            self.dur = 0.5
            self.vp = self.v
        else:
            self.vp, self.ta, self.td, self.dur = walk_profile(self.dist, self.v, self.ta, self.td)

    @property
    def t1(self) -> float:
        return self.t0 + self.dur

    @property
    def direction(self) -> int:
        return -1 if self.x1 < self.x0 else 1

    def travelled(self, t: float) -> float:
        """Distance walked at absolute time t (0 .. dist)."""
        u = min(max(t - self.t0, 0.0), self.dur)
        if self.kind == "shift":
            p = u / self.dur
            return self.dist * p * p * (3 - 2 * p)
        if u < self.ta:
            return 0.5 * (self.vp / self.ta) * u * u
        d_acc = self.vp * self.ta / 2
        cruise_t = self.dur - self.ta - self.td
        if u < self.ta + cruise_t:
            return d_acc + self.vp * (u - self.ta)
        r = self.dur - u
        return self.dist - 0.5 * (self.vp / self.td) * r * r

    def x(self, t: float) -> float:
        return self.x0 + self.direction * self.travelled(t)


# ------------------------------------------------------------------ anchors


def resolve_on(sw: D.SceneWords, on, what: str = "cue") -> tuple[float, str, int]:
    """Absolute time, word and word index for an `on` anchor ('start', 'end', text or word index)."""
    if isinstance(on, int):
        if on >= len(sw.words):
            raise ValueError(f"scene {sw.index + 1}: {what} word index {on} out of range")
        return sw.words[on][1], sw.words[on][0], on
    if on == "start":
        return sw.words[0][1], sw.words[0][0], 0
    if on == "end":
        return sw.words[-1][2], sw.words[-1][0], len(sw.words) - 1
    i = D._find(sw.words, on)
    if i is None:
        raise ValueError(f"scene {sw.index + 1}: {what} text {on!r} not found in the narration")
    return sw.words[i][1], sw.words[i][0], i


def station_x(cfg: dict, x, where: str) -> float:
    if isinstance(x, str):
        if x not in cfg["stations"]:
            raise StageError(f"{where}: unknown station {x!r}")
        return float(cfg["stations"][x])
    if not isinstance(x, (int, float)) or isinstance(x, bool) or not AREA[0] <= x <= AREA[1]:
        raise StageError(f"{where}: x must be a station name or a number between {AREA[0]} and {AREA[1]}")
    return float(x)


def station_name(cfg: dict, x: float) -> str:
    return min(cfg["stations"], key=lambda k: abs(cfg["stations"][k] - x))


# ------------------------------------------------------------------ plan


class StagePlan:
    """Everything decided before drawing: gestures, moves, faces, camera, elements."""

    def __init__(self, script, timeline, leads, base_lead: float = 0.5):
        self.script, self.timeline, self.leads = script, timeline, leads
        self.cfg = stage_settings(script)
        self.dcfg = D.settings(script.direction)
        self.scenes = D.scene_words(timeline, script, leads)
        self.total = timeline[-1][0] + timeline[-1][1]
        self.warnings: list[str] = []
        self.errors: list[str] = []
        self.moves: list[Move] = []
        self.faces: list[tuple[float, str]] = [(0.0, "camera")]
        self._plan_gestures(base_lead)
        self._plan_camera()
        self.choreo.cfg = self.dcfg

    # --- gestures and moves
    def _plan_gestures(self, base_lead: float) -> None:
        cfg, ant = self.cfg, self.cfg["timing"]["anticipation_ms"] / 1000
        w = cfg["walk"]
        self.choreo = D.plan(self.script, self.timeline, self.dcfg, base_lead, self.leads)
        gestures = self.choreo.gestures
        stage_cues = []
        for sw in self.scenes:
            for c in sw.scene.cues:
                if c["do"] in STAGE_ACTIONS or c.get("face"):
                    stage_cues.append((sw, c))
        # face changes (any cue with `face`) and the stage cues, in time order
        items = []
        for sw, c in stage_cues:
            t, word, _ = resolve_on(sw, c["on"], "cue") if "on" in c else (sw.start + sw.lead + c["at"], "", 0)
            items.append((t, sw, c, word))
        items.sort(key=lambda x: x[0])
        x = None
        for t, sw, c, word in items:
            do = c["do"]
            where = f"scene {sw.index + 1}, cue {do}"
            if do == "enter":
                x0 = station_x(cfg, c.get("from", "off"), where)
                x1 = station_x(cfg, c.get("x", "R"), where)
                v, ta, td = w["speed_px_s"], w["accel_s"], w["decel_s"]
                m = Move(max(0.0, t - 0.0) if c.get("on") == "start" else t - ant, x0, x1, v, ta, td, "walk", f"{c['on']}:enter",
                         station_name(cfg, x1), sw.index)
                m.t0 = sw.start if c.get("on") == "start" else m.t0
                first = next((g for g in sorted(gestures, key=lambda g: g.onset) if g.kind == "pose" and g.onset >= m.t0), None)
                if first is not None and m.t1 > first.onset - 0.02:
                    # walk in a little faster (up to the maximum) so the first gesture is not pushed back
                    v2 = m.dist / max(first.onset - 0.02 - m.t0 - (ta + td) / 2, 0.05)
                    m = Move(m.t0, x0, x1, min(v2, w["max_speed_px_s"]), ta, td, "walk", m.cue, m.station, m.scene)
                self.moves.append(m)
                x = x1
            elif do == "walk_to":
                if x is None:
                    x = self._x_before(t)
                x1 = station_x(cfg, c.get("x", "H"), where)
                self._add_walk(sw, c, t, ant, x, x1, gestures)
                x = x1
            elif do == "exit":
                x1 = station_x(cfg, c.get("to", "off"), where)
                if x is None:
                    x = self._x_before(t)
                start = t + float(c.get("after_s", 0.0))
                self._add_move(sw, c, start, x, x1, 240.0, "exit")
                x = x1
            if c.get("face"):
                self.faces.append((max(0.0, t - ant), c["face"]))
        self.faces.sort()
        self._clean_gestures()
        self._face_gestures()
        self._check_stay()

    def _x_before(self, t: float) -> float:
        prev = [m for m in self.moves if m.t1 <= t + 1e-6]
        return prev[-1].x1 if prev else float(self.cfg["stations"]["H"])

    def _add_move(self, sw, c, t0, x0, x1, v, tag) -> Move:
        w = self.cfg["walk"]
        kind = "walk" if abs(x1 - x0) >= w["min_move_px"] else "shift"
        if kind == "shift":
            x1 = x0 + max(-6, min(6, x1 - x0)) if x1 != x0 else x0
        m = Move(t0, x0, x1, v, w["accel_s"], w["decel_s"], kind, f"{c.get('on', '')}:{c['do']}", station_name(self.cfg, x1), sw.index)
        self.moves.append(m)
        return m

    def _add_walk(self, sw, c, t_word, ant, x0, x1, gestures) -> None:
        """Start trigger = the word; if an arm gesture follows soon, start earlier so Bit has arrived (never delay a gesture)."""
        w = self.cfg["walk"]
        dist = abs(x1 - x0)
        if dist < w["min_move_px"]:
            self._add_move(sw, c, t_word - ant, x0, x1, w["speed_px_s"], "shift")
            return
        trigger = t_word - ant
        prev_end = max([m.t1 for m in self.moves] + [0.0])
        arm = [g for g in gestures if g.kind == "pose" and g.action not in ("turn_slide", "look_slide") and g.onset > t_word - 0.05]
        deadline = (arm[0].onset - w["settle_s"]) if arm else None
        # earliest start: after the previous gesture could be trimmed to its minimum
        floor = prev_end
        for g in gestures:
            if g.kind == "pose" and g.onset < trigger and g.action not in ("turn_slide", "look_slide"):
                floor = max(floor, min(g.end, g.onset + g.entra + g.sai + 0.1))
        v = float(w["speed_px_s"])
        t0 = trigger
        dur = walk_duration(dist, v, w["accel_s"], w["decel_s"])
        if deadline is not None and t0 + dur > deadline:
            t0 = max(floor, deadline - dur)
            if t0 + dur > deadline:
                avail = deadline - floor
                v = dist / max(avail - (w["accel_s"] + w["decel_s"]) / 2, 0.05)
                if v > w["max_speed_px_s"]:
                    msg = (f"scene {sw.index + 1}: walk to {station_name(self.cfg, x1)} at word {c.get('on')!r} does not fit before the "
                           f"next gesture ({avail:.2f} s available, needs {dur:.2f} s at {w['speed_px_s']} px/s and "
                           f"{v:.0f} px/s would be too fast)")
                    self.errors.append(msg)
                    v = float(w["max_speed_px_s"])
                    t0 = max(floor, deadline - walk_duration(dist, v, w["accel_s"], w["decel_s"]))
                else:
                    t0 = floor
        t0 = max(t0, prev_end)
        m = Move(t0, x0, x1, v, w["accel_s"], w["decel_s"], "walk", f"{c.get('on', '')}:walk_to", station_name(self.cfg, x1), sw.index)
        self.moves.append(m)

    def _clean_gestures(self) -> None:
        """No arm pose while walking: trim a gesture that runs into a walk, drop an automatic one that starts inside it."""
        keep = []
        for g in self.choreo.gestures:
            drop = False
            for m in self.moves:
                if m.kind != "walk":
                    continue
                if g.onset >= m.t0 - 0.02 and g.onset < m.t1:
                    if g.source != "manual" or g.action in ("turn_slide", "look_slide", "happy_beat", "explain_beat"):
                        drop = True
                    else:
                        # a manual cue that starts mid-walk: the walk has priority, the gesture starts when it ends
                        g.hold = max(g.hold, 0.3)
                        shift = m.t1 + 0.0 - g.onset
                        self.warnings.append(f"scene {g.scene + 1}: cue {g.cue!r} starts while walking, moved {shift:.2f} s later")
                        g.onset += shift
                elif g.onset < m.t0 and g.end > m.t0:
                    g.hold = max(g.entra + 0.1, m.t0 - g.onset - g.sai)
                    g.cut = m.t0 + 0.0
            if not drop:
                keep.append(g)
        self.choreo.gestures = D._resolve(keep, 3.4)
        self.choreo.log = D._log(self.choreo.gestures, False)

    def _face_gestures(self) -> None:
        """While facing the slide and not otherwise busy, Bit shows the look-at-slide pose."""
        busy = sorted([(g.onset, g.end) for g in self.choreo.gestures] + [(m.t0 - 0.05, m.t1 + 0.05) for m in self.moves if m.kind == "walk"])
        extra = []
        faces = self.faces + [(self.total, "camera")]
        for (t0, f), (t1, _f2) in zip(faces, faces[1:]):
            if f != "slide" or t1 - t0 < 0.5:
                continue
            free = [(t0, t1)]
            for b0, b1 in busy:
                nxt = []
                for a, b in free:
                    if b1 <= a or b0 >= b:
                        nxt.append((a, b))
                    else:
                        if b0 - a > 0.5:
                            nxt.append((a, b0))
                        if b - b1 > 0.5:
                            nxt.append((b1, b))
                free = nxt
            for a, b in free:
                g = D.Gesture("look_slide", a, min(b - a - 0.3, 3.4), "face", 0, "", a + 0.2, "face:slide")
                g.hold = max(g.hold, g.entra + 0.1)
                g.scene = next((s.index for s in self.scenes if s.start <= a < s.start + self.timeline[s.index][1]), 0)
                extra.append(g)
        if extra:
            self.choreo.gestures = D._resolve(self.choreo.gestures + extra, 3.4)
            self.choreo.log = D._log(self.choreo.gestures, False)

    def _check_stay(self) -> None:
        """Warn when Bit stays more than max_stay_s at the same x with no change of station."""
        pts = [(0.0, self.x(0.0))] + [(m.t1, m.x1) for m in self.moves]
        pts.append((self.total, pts[-1][1]))
        mx = self.cfg["timing"]["max_stay_s"]
        mn = self.cfg["timing"]["min_stay_s"]
        for (t0, x0), (t1, _x1) in zip(pts, pts[1:]):
            if t1 - t0 >= mx and abs(_x1 - x0) < 40:
                self.warnings.append(f"Bit stays near x={x0:.0f} for {t1 - t0:.1f} s (over {mx} s); add a move or a camera change")
        for a, b in zip(self.moves, self.moves[1:]):
            if a.kind == "walk" and b.kind == "walk" and not a.cue.endswith(":enter") and b.t0 - a.t1 < mn - 1e-6:
                self.warnings.append(f"scene {b.scene + 1}: stay at {a.station} is only {b.t0 - a.t1:.1f} s (min {mn} s)")

    # --- position queries
    def move_at(self, t: float) -> Move | None:
        for m in self.moves:
            if m.t0 <= t < m.t1:
                return m
        return None

    def x(self, t: float) -> float:
        x = float(self.cfg["stations"]["H"]) if not self.moves else self.moves[0].x0
        for m in self.moves:
            if t >= m.t1:
                x = m.x1
            elif t >= m.t0:
                return m.x(t)
            else:
                break
        return x

    def walking(self, t: float) -> Move | None:
        m = self.move_at(t)
        return m if m is not None and m.kind == "walk" else None

    def y_offset(self, t: float) -> float:
        return self.choreo.y_offset(t)

    def layers(self, t: float) -> list[tuple[str, int, float]]:
        base = self.choreo.layers(t)
        m = self.walking(t)
        if m is None:
            return base
        lead_in = 1.0 if m.x0 >= OFF_X - 1 else (t - m.t0) / 0.06      # no blend when coming from / going off stage
        lead_out = 1.0 if m.x1 >= OFF_X - 1 else (m.t1 - t) / 0.06
        ww = max(0.0, min(1.0, lead_in, lead_out))
        tag = "andando_w" if m.direction < 0 else "andando_e"
        k = walk_frame(m.travelled(t), walk_steps(self.cfg["walk"]["stride_px"], tag))
        out = [(tag, k, ww)] if ww > 0 else []
        out += [(tg, kk, w * (1 - ww)) for tg, kk, w in base if w * (1 - ww) > 1e-6]
        return out

    def shadow(self, t: float) -> float:
        for g in self.choreo.active(t):
            if g.action == "celebrate" and g.kind == "pose" and g.onset + g.entra <= t < g.pose_end:
                return 0.94
        return 1.0

    # --- camera
    def _plan_camera(self) -> None:
        views = self.cfg["views"]
        ev = []
        for sw in self.scenes:
            for c in sw.scene.camera:
                if c.get("on", "start") == "start":
                    t, word = sw.start + 0.1, ""
                else:
                    t, word, _ = resolve_on(sw, c["on"], "camera cue")
                name = c.get("view", "wide")
                if name not in views:
                    raise StageError(f"scene {sw.index + 1}: unknown camera view {name!r}")
                ev.append((max(0.0, t - 0.1), name, c, word))
        ev.sort(key=lambda e: e[0])
        out = []
        for t, name, c, word in ev:
            v = dict(views[name])
            if "zoom" in c:
                v["zoom"] = float(c["zoom"])
            z = min(max(float(v["zoom"]), 1.0), 1.15)
            cx = 960 + (self.x(t + 0.6) - 960) * float(v.get("cx_follow", 0.35)) if v["cx"] == "bit_x" else float(v["cx"])
            cy = float(v["cy"])
            cx = min(max(cx, 960 / z), 1920 - 960 / z)
            cy = min(max(cy, 540 / z), 1080 - 540 / z)
            if out and t - out[-1]["t"] < 1.5 - 1e-6:
                self.warnings.append(f"camera change at {t:.2f} s moved to {out[-1]['t'] + 1.5:.2f} s (min 1.5 s between changes)")
                t = out[-1]["t"] + 1.5
            out.append({"t": round(t, 3), "view": name, "cx": round(cx, 1), "cy": round(cy, 1), "zoom": round(z, 3), "word": word})
        if not out or out[0]["t"] > 0.01:
            out.insert(0, {"t": 0.0, "view": "wide", "cx": 960.0, "cy": 540.0, "zoom": 1.0, "word": ""})
        self.camera = out

    # --- elements (slide behaviour)
    def elements(self) -> dict:
        marks, reveals, counts, rings = [], [], [], []
        for sw in self.scenes:
            sc = sw.scene
            for e in sc.emph:
                t, word, _ = resolve_on(sw, e["on"], "emph")
                marks.append({"scene": sw.index, "t": round(t - 0.12, 3), "t_word": round(t, 3), "target": e["target"],
                              "style": e.get("style", "mark"), "word": word})
            items = sc.slide.get("items", [])
            if items:
                if sc.reveal:
                    for r in sc.reveal:
                        t, word, _ = resolve_on(sw, r["on"], "reveal")
                        reveals.append({"scene": sw.index, "item": r["item"], "t": round(t - 0.12, 3), "t_word": round(t, 3), "word": word})
                else:
                    for j in range(len(items)):
                        wi = min(len(sw.words) - 1, (j * len(sw.words)) // len(items))
                        t = sw.words[wi][1]
                        reveals.append({"scene": sw.index, "item": j, "t": round(t - 0.12, 3), "t_word": round(t, 3), "word": sw.words[wi][0]})
            for c in sc.count:
                t, word, _ = resolve_on(sw, c["on"], "count")
                counts.append({"scene": sw.index, "item": c.get("item"), "target": c.get("target"), "from": c.get("from", 0), "to": c["to"],
                               "suffix": c.get("suffix", ""), "t": round(t - 0.12, 3), "t_word": round(t, 3), "ms": c.get("ms", 750), "word": word})
        for g in self.choreo.gestures:
            pass
        # pointing rings come from cues that carry a `target`
        for sw in self.scenes:
            for c in sw.scene.cues:
                if c.get("target") and c["do"] not in STAGE_ACTIONS:
                    t, word, _ = resolve_on(sw, c["on"], "cue")
                    g = next((g for g in self.choreo.gestures if g.cue == f"{c['on']}:{c['do']}" or abs(g.word_t - t) < 1e-6), None)
                    hold = float(c.get("hold", ACTIONS[c["do"]][1]))
                    t_in = (g.onset if g else t - 0.2)
                    rings.append({"scene": sw.index, "target": c["target"], "t_in": round(t_in, 3), "t_click": round(t + 0.05, 3),
                                  "t_out": round(t_in + hold + 0.1, 3), "word": word})
        rings.sort(key=lambda r: r["t_in"])
        return {"marks": marks, "reveals": reveals, "counts": counts, "rings": rings}


# ------------------------------------------------------------------ stage.json


def caption_words(plan: StagePlan) -> list[dict]:
    """Caption chunks with the audio word timings attached (for karaoke fill)."""
    out = []
    for si, ((start, total, a), lead) in enumerate(zip(plan.timeline, plan.leads)):
        words = [(w.text, start + lead + w.t0, start + lead + w.t1, w.sentence) for w in a.words]
        wi = 0
        for (s0, s1, lines) in caption_chunks(a.sentences, lead):
            chunk = {"t0": round(start + s0, 3), "t1": round(start + s1, 3), "scene": si, "lines": []}
            for line in lines:
                row = []
                for tok in line.split():
                    n = len(A.tokens(tok))
                    seg = words[wi:wi + n]
                    wi += n
                    if seg:
                        row.append({"w": tok, "t0": round(seg[0][1], 3), "t1": round(seg[-1][2], 3)})
                    else:
                        row.append({"w": tok, "t0": None, "t1": None})
                chunk["lines"].append(row)
            out.append(chunk)
    return out


def build_stage(plan: StagePlan, bit_frames: list, fps: int, total_s: float) -> dict:
    scenes = []
    for sw in plan.scenes:
        start, total, _a = plan.timeline[sw.index]
        sc = sw.scene
        scenes.append({"i": sw.index, "t0": round(start, 3), "t1": round(start + total, 3), "lead": sw.lead,
                       "t_first_word": round(sw.words[0][1], 3), "slide": sc.slide, "emotion": sc.emotion})
    el = plan.elements()
    return {
        "fps": fps, "duration": round(total_s, 3), "width": 1920, "height": 1080, "floor_y": plan.cfg["floor_y"],
        "springs": plan.cfg["springs"], "card_states": plan.cfg["card_states"], "background": plan.cfg["background"],
        "idle_camera": plan.cfg["idle_camera"], "idle": plan.dcfg["idle"], "captions_cfg": plan.cfg["captions"],
        "scenes": scenes, "camera": plan.camera, "captions": caption_words(plan), **el,
        "moves": [{"t0": round(m.t0, 3), "t1": round(m.t1, 3), "x0": m.x0, "x1": m.x1, "kind": m.kind, "station": m.station}
                  for m in plan.moves],
        "faces": [{"t": round(t, 3), "face": f} for t, f in plan.faces],
        "bit": {"fps": fps, "frames": bit_frames, "cols": "x,y,blink,mouth,lift,shadow,i1,w1,i2,w2"},
    }


def bit_frames(stage, fps: int, n_frames: int) -> list:
    """Per-frame Bit state as compact rows: [x, y, blink, mouth, lift, shadow, i1, w1, i2, w2] (i = sheet frame index)."""
    rows = []
    mouth_idx = {m: i for i, m in enumerate(SP.MOUTHS)}
    for q in range(n_frames):
        fs = stage.state(q)
        b = fs.bit
        lay = sorted(b.layers, key=lambda l: -l[2])[:2]
        flat = []
        for tag, k, w in lay:
            flat += [SP.tag_frames(tag)[k]["i"], round(w, 3)]
        while len(flat) < 4:
            flat += [0, 0]
        rows.append([round(b.x, 1), round(b.y, 1), int(b.blink), mouth_idx[b.mouth], b.lift, round(b.shadow, 3)] + flat)
    return rows


def report(plan: StagePlan) -> dict:
    """stage.report.json: one row per cue with the times the checks read, plus warnings and errors."""
    rows = []
    for r in plan.choreo.log:
        t_apex = r["t_apice_ms"] / 1000
        rows.append({**r, "estacao": station_name(plan.cfg, plan.x(t_apex)),
                     "face": next(f for t, f in reversed(plan.faces) if t <= t_apex + 1e-6)})
    for m in plan.moves:
        rows.append({"cue": m.cue, "do": "walk" if m.kind == "walk" else "shift", "source": "manual", "scene": m.scene + 1,
                     "t_inicio_ms": round(m.t0 * 1000), "t_fim_ms": round(m.t1 * 1000), "estacao": m.station,
                     "x0": m.x0, "x1": m.x1, "speed_px_s": round(m.vp), "dist_px": round(m.dist)})
    rows.sort(key=lambda r: r.get("t_palavra_ms", r.get("t_inicio_ms", 0)))
    return {"cues": rows, "warnings": plan.warnings, "ERRO": plan.errors}
