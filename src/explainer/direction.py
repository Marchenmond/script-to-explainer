"""Scene direction: turns `cues` (anchored on spoken words) plus automatic rules into a gesture timeline.

A gesture is `<base>_entra_s` -> `<base>_s` (loop) -> `<base>_sai_s`. It starts `anticipation_ms`
before its anchor word, so the pose reaches its key moment on the word. Manual cues always win;
automatic rules only fill gaps, keep a minimum spacing and never contradict the sentence.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from . import sprites as SP
from .actions import ACTIONS, STAGE_ACTIONS
from .audio import tokens

XF = 0.12  # seconds of crossfade between two poses

DEFAULTS = {
    "anticipation_ms": 200,
    "min_gap_ms": 1500,
    "max_hold_same_pose_s": 3.5,
    "auto_rules": True,
    "transition_ms": 300,
    "idle": {"breathe_px": 1, "breathe_period_s": 3.2, "blink_every_s": [2.8, 4.5], "sway_px": 6},
}

GREETING = {"hi", "hello", "welcome", "hey", "ola"}
BYE = re.compile(r"\b(that's it|bye|see you|thanks|thank you|tchau|share)\b", re.I)
CELEBRATE = re.compile(r"^(\d+|percent|done|result|results|faster|great|works)$", re.I)
POINT = {"this", "here", "look", "see", "these", "below", "above", "screen", "slide", "command", "highlight"}
LIST_WORDS = {"first", "second", "third", "then", "next"}
OPEN = {"you", "your"}
SHRUG_PHRASES = ("not sure", "maybe", "hmm", "optional")
PRIORITY = {"wave": 0, "bow_wave": 0, "think_chin": 1, "celebrate": 1, "shrug": 2, "point_slide": 3, "explain_open": 4,
            "turn_slide": 5, "happy_beat": 5, "think_simple": 5}
EMOTION_ACTIONS = {"happy": {"wave", "bow_wave", "celebrate", "happy", "happy_beat"},
                   "thinking": {"think", "think_chin", "think_simple"},
                   "pointing": {"point_slide", "point_down"}}
EMOTION_DEFAULT = {"happy": "happy_beat", "thinking": "think_simple", "pointing": "point_slide"}


def settings(user: dict | None) -> dict:
    cfg = {**DEFAULTS, **(user or {})}
    cfg["idle"] = {**DEFAULTS["idle"], **((user or {}).get("idle") or {})}
    return cfg


@dataclass
class Gesture:
    action: str
    onset: float          # absolute seconds when the pose starts (before the word)
    hold: float           # seconds from onset until the "leave" animation starts
    source: str           # manual | auto | emotion | filler
    scene: int
    word: str = ""
    word_t: float = 0.0   # absolute seconds of the anchor word
    cue: str = ""
    cut: float | None = None
    extra: list = field(default_factory=list)   # cues merged into this one (same pose held)

    @property
    def base(self) -> str | None:
        return ACTIONS[self.action][0]

    @property
    def kind(self) -> str:
        return "beat" if self.base is None else "pose"

    @property
    def entra(self) -> float:
        return SP.tag_duration_ms(f"{self.base}_entra_s") / 1000 if self.kind == "pose" else 0.0

    @property
    def sai(self) -> float:
        return SP.tag_duration_ms(f"{self.base}_sai_s") / 1000 if self.kind == "pose" else 0.0

    @property
    def pose_end(self) -> float:
        return self.onset + self.hold

    @property
    def end(self) -> float:
        e = self.pose_end + self.sai
        return min(e, self.cut) if self.cut is not None else e

    @property
    def apex(self) -> float:
        return self.onset + self.entra

    def layer(self, t: float) -> tuple[str, int] | None:
        """(tag, frame index) shown by this gesture at time t, or None."""
        if self.kind == "beat":
            return None
        dt = t - self.onset
        if dt < self.entra and t < self.pose_end:
            tag = f"{self.base}_entra_s"
            return tag, SP.locate(tag, dt * 1000, loop=False)
        if t < self.pose_end:
            tag = f"{self.base}_s"
            return tag, SP.locate(tag, (dt - self.entra) * 1000)
        tag = f"{self.base}_sai_s"
        return tag, SP.locate(tag, (t - self.pose_end) * 1000, loop=False)


class Choreography:
    def __init__(self, gestures: list[Gesture], log: list[dict], cfg: dict):
        self.gestures = gestures
        self.log = log
        self.cfg = cfg

    def active(self, t: float) -> list[Gesture]:
        return [g for g in self.gestures if g.onset <= t < g.end]

    def layers(self, t: float) -> list[tuple[str, int, float]]:
        """[(tag, frame index, weight)] for the body at time t (weights sum to 1)."""
        act = [g for g in self.active(t) if g.kind != "beat"]
        out = []
        left = 1.0
        for g in sorted(act, key=lambda g: -g.onset)[:2]:
            w = min(1.0, (t - g.onset) / XF) if left == 1.0 else left
            w = max(w, 0.0)
            tag, k = g.layer(t)
            if w > 0:
                out.append((tag, k, w))
            left -= w
            if left <= 1e-6:
                break
        if left > 1e-6:
            ms = int(t * 1000)
            out.append(("parada_s", SP.locate("parada_s", ms), left))
        return out

    def y_offset(self, t: float) -> float:
        """Vertical bounce in screen pixels (explain_beat and the small settle at each gesture apex)."""
        y = 0.0
        for g in self.gestures:
            if g.kind == "beat" and g.onset <= t < g.onset + g.hold:
                y -= 16 * math.sin(math.pi * (t - g.onset) / g.hold)
        return y

    def facing(self, t: float) -> str:
        return "w"


def _smooth(p: float) -> float:
    return p * p * (3 - 2 * p)


# ---------------------------------------------------------------- planning


@dataclass
class SceneWords:
    index: int
    start: float           # absolute scene start
    lead: float
    words: list            # [(text, abs t0, abs t1, sentence idx)]
    sentences: list        # [(text, abs start, abs end)]
    scene: object          # explainer.script.Scene
    first: bool = False
    last: bool = False


def scene_words(timeline, script, leads: list[float]) -> list[SceneWords]:
    out = []
    n = len(timeline)
    for i, ((start, _total, a), sc) in enumerate(zip(timeline, script.scenes)):
        o = start + leads[i]
        out.append(SceneWords(
            i, start, leads[i],
            [(w.text, o + w.t0, o + w.t1, w.sentence) for w in a.words],
            [(s, o + s0, o + s1) for s, s0, s1 in a.sentences], sc, i == 0, i == n - 1))
    return out


def lead_for(scene, base_lead: float, cfg: dict) -> float:
    """Silence before the narration of a scene (the scene's own `lead`, else the default)."""
    return scene.lead if scene.lead is not None else base_lead


def _find(words, phrase: str) -> int | None:
    toks = [t.lower() for t in tokens(phrase)]
    seq = [w[0].lower() for w in words]
    for i in range(len(seq) - len(toks) + 1):
        if seq[i:i + len(toks)] == toks:
            return i
    return None


def _manual(sw: SceneWords, cfg: dict) -> list[Gesture]:
    ant = cfg["anticipation_ms"] / 1000
    out = []
    for c in sw.scene.cues:
        action = c["do"]
        if action in STAGE_ACTIONS:
            continue
        default = ACTIONS[action][1]
        hold = float(c.get("hold", default))
        label = c.get("on") if "on" in c else (f"word {c['word']}" if "word" in c else f"at {c['at']}")
        if "on" in c and c["on"] == "start":
            t, word = sw.words[0][1], sw.words[0][0]
        elif "on" in c and c["on"] == "end":
            t, word = sw.words[-1][2], sw.words[-1][0]
        elif "on" in c:
            i = _find(sw.words, c["on"])
            if i is None:
                raise ValueError(f"scene {sw.index + 1}: cue text {c['on']!r} not found in the narration")
            t, word = sw.words[i][1], sw.words[i][0]
        elif "word" in c:
            if c["word"] >= len(sw.words):
                raise ValueError(f"scene {sw.index + 1}: cue word index {c['word']} out of range")
            t, word = sw.words[c["word"]][1], sw.words[c["word"]][0]
        else:
            t, word = sw.start + sw.lead + c["at"], ""
        g = Gesture(action, max(0.0, t - ant), hold, "manual", sw.index, word, t, f"{label}:{action}")
        g.hold = max(g.hold, g.entra + 0.1) if g.kind == "pose" else g.hold
        out.append(g)
    return out


def _candidates(sw: SceneWords, cfg: dict) -> list[Gesture]:
    ant = cfg["anticipation_ms"] / 1000
    cands = []

    def add(action, wi, hold=None, rule=""):
        w = sw.words[wi]
        h = hold if hold is not None else ACTIONS[action][1]
        g = Gesture(action, max(0.0, w[1] - ant), h, "auto", sw.index, w[0], w[1], rule)
        if g.kind == "pose":
            g.hold = max(g.hold, g.entra + 0.1)
        cands.append(g)

    sents: dict[int, list[int]] = {}
    for i, w in enumerate(sw.words):
        sents.setdefault(w[3], []).append(i)
    has_items = bool(sw.scene.slide.get("items"))
    for si, idxs in sents.items():
        text = sw.sentences[si][0]
        question = text.rstrip().endswith("?")
        first = idxs[0]
        low = [sw.words[i][0].lower() for i in idxs]
        if (sw.first and si == 0) or (low and low[0] in GREETING):
            add("wave", first, 1.3, "greeting")
        if sw.last and si == len(sents) - 1 and BYE.search(text):
            add("wave", first, 1.4, "goodbye")
        if question:
            span = sw.sentences[si][2] - sw.words[first][1]
            add("think_chin", first, min(3.0, span + 0.2), "question")
        else:
            for i in idxs:
                w = sw.words[i][0]
                if CELEBRATE.match(w):
                    add("celebrate", i, 1.0, "result")
                elif w.lower() in POINT:
                    add("point_slide", i, 0.9, "deictic")
                elif has_items and w.lower() in LIST_WORDS:
                    add("point_slide", i, 0.9, "list item")
                elif w.lower() in OPEN:
                    add("explain_open", i, 0.8, "addressing viewer")
        joined = " ".join(low)
        for ph in SHRUG_PHRASES:
            if ph in joined:
                add("shrug", idxs[low.index(ph.split()[0])], 0.8, "uncertainty")
    if not sw.first:
        add("turn_slide", 0, 0.45, "new slide")
    if sw.last:
        g = Gesture("bow_wave", max(0.0, sw.words[-1][2] - ant), max(1.0, sw.scene.pause_after), "auto", sw.index,
                    sw.words[-1][0], sw.words[-1][2], "end of video")
        g.hold = max(g.hold, g.entra + 0.1)
        cands.append(g)
    return cands


def _spaced(g: Gesture, kept: list[Gesture], gap: float) -> bool:
    for k in kept:
        if abs(g.onset - k.onset) < gap:
            return False
        if k.onset <= g.onset < k.end + 0.6 or g.onset <= k.onset < g.end + 0.6:
            return False
    return True


def plan(script, timeline, cfg_user: dict | None = None, base_lead: float = 0.5, leads: list[float] | None = None) -> Choreography:
    cfg = settings(cfg_user or script.direction)
    leads = leads or [base_lead] * len(script.scenes)
    scenes = scene_words(timeline, script, leads)
    max_hold = min(float(cfg["max_hold_same_pose_s"]) - 0.1, 3.4)
    gap = cfg["min_gap_ms"] / 1000
    manual: list[Gesture] = []
    for sw in scenes:
        manual += _manual(sw, cfg)
    gestures = list(manual)
    scene_of = {sw.index: sw for sw in scenes}
    if cfg["auto_rules"]:
        autos: list[Gesture] = []
        for sw in scenes:
            for g in _candidates(sw, cfg):
                sent_span = None
                for s_text, s0, s1 in sw.sentences:
                    if s0 - 0.05 <= g.word_t <= s1 + 0.05:
                        sent_span = (s0, s1)
                if sent_span and any(m.scene == sw.index and sent_span[0] - 0.4 <= m.word_t <= sent_span[1] + 0.4 for m in manual
                                     if True):
                    continue
                autos.append(g)
        for g in sorted(autos, key=lambda g: (PRIORITY.get(g.action, 9), g.onset)):
            if _spaced(g, gestures, gap):
                gestures.append(g)
        # make sure the scene mood shows up while talking
        for sw in scenes:
            want = EMOTION_ACTIONS.get(sw.scene.emotion)
            if not want or any(g.scene == sw.index and g.action in want for g in gestures):
                continue
            for wi, w in enumerate(sw.words):
                if wi < 2:
                    continue
                g = Gesture(EMOTION_DEFAULT[sw.scene.emotion], max(0.0, w[1] - cfg["anticipation_ms"] / 1000), 1.0, "emotion",
                            sw.index, w[0], w[1], "scene mood")
                g.hold = max(g.hold, g.entra + 0.1)
                if _spaced(g, gestures, 1.2):
                    gestures.append(g)
                    break
    gestures = _resolve(gestures, max_hold)
    if cfg["auto_rules"]:
        gestures = _fillers(gestures, scenes, timeline, cfg, max_hold)
    log = _log(gestures, manual_only=False)
    return Choreography(gestures, log, cfg)


def _resolve(gestures: list[Gesture], max_hold: float) -> list[Gesture]:
    """Order gestures; join the same pose held across cues; cut a pose when the next one starts."""
    kept: list[Gesture] = []
    for g in sorted(gestures, key=lambda g: (g.onset, g.source != "manual")):
        if g.kind == "pose":
            g.hold = min(g.hold, max_hold)
        prev = kept[-1] if kept else None
        if prev is not None and g.onset < prev.end:
            if g.onset < prev.pose_end:
                if g.action == prev.action and g.kind == "pose" and g.onset + g.hold - prev.onset <= max_hold:
                    prev.hold = max(prev.hold, g.onset + g.hold - prev.onset)
                    prev.extra.append(g)
                    continue
                prev.hold = max(g.onset - prev.onset, 0.05)
            prev.cut = g.onset + XF
        kept.append(g)
    return kept


def _fillers(gestures, scenes, timeline, cfg, max_hold):
    """Break any stretch of the same pose (idle or held) that would pass the limit."""
    total = timeline[-1][0] + timeline[-1][1]
    limit = float(cfg["max_hold_same_pose_s"]) - 0.6
    seq = ["turn_slide", "explain_open", "turn_slide", "happy_beat"]
    out = list(gestures)
    n = 0
    t, k = 0.0, 0
    while t < total:
        nxt = next((g for g in sorted(out, key=lambda g: g.onset) if g.onset >= t), None)
        stretch_end = nxt.onset if nxt else total
        if stretch_end - t > limit:
            act = seq[n % len(seq)]
            n += 1
            sw = next((s for s in scenes if s.start <= t + 1.4 < s.start + (timeline[s.index][1])), scenes[-1])
            g = Gesture(act, t + 1.5, ACTIONS[act][1], "filler", sw.index, "", t + 1.7, "idle limit")
            g.hold = max(g.hold, g.entra + 0.1)
            out.append(g)
            t = g.end
        else:
            t = (nxt.end if nxt else total) + 0.0
            if nxt is None:
                break
    return _resolve(out, max_hold)


def _log(gestures: list[Gesture], manual_only: bool) -> list[dict]:
    rows = []
    for g in gestures:
        for h, status in [(g, "ok")] + [(e, "merged") for e in g.extra]:
            if status == "merged":
                onset, apex, tag = h.word_t, h.word_t, g.base + "_s"
            else:
                onset, apex = g.onset, g.apex
                tag = f"{g.base}_entra_s" if g.base else "(code bounce)"
            rows.append({
                "scene": h.scene + 1, "cue": h.cue or h.action, "do": h.action, "source": h.source, "word": h.word,
                "pose": tag, "status": status,
                "t_palavra_ms": round(h.word_t * 1000), "t_gesto_ms": round(onset * 1000), "t_apice_ms": round(apex * 1000),
                "antecipacao_ms": round((h.word_t - onset) * 1000), "diferenca_ms": round((apex - h.word_t) * 1000),
                "hold_s": round(g.hold, 2),
            })
    rows.sort(key=lambda r: r["t_palavra_ms"])
    return rows
