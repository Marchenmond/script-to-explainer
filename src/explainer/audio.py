"""Build the narration track, per-sentence captions and per-word timings (engine independent).

Narration is spoken clause by clause (split at commas, colons, ellipses and dashes), each clause is
synthesized on its own, trimmed, faded and joined with silences chosen by punctuation. That gives
exact clause boundaries and lets pauses and speed be configured.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .script import Script, split_sentences

SR = 24000
FADE = 0.008          # seconds, linear ramp at both ends of every clause
TRIM_LEVEL = 0.01     # edges below this amplitude are cut
EMPHASIS_SPEED = 0.9  # speed factor for emphatic clauses (expressive style)

# silence after a clause, in seconds, by the punctuation that ends it (override with "pauses" in the script)
DEFAULT_PAUSES = {
    "comma": 0.2, "semicolon": 0.25, "colon": 0.25, "dash": 0.25,
    "ellipsis": 0.5, "period": 0.45, "question": 0.45, "exclaim": 0.5,
}
GAP = DEFAULT_PAUSES["period"]  # one typical sentence gap

_CLAUSE_SEP = re.compile(r"(?<=[,;:])\s+|\s+[-–—]\s+")


@dataclass
class Word:
    text: str
    t0: float          # seconds from the start of the scene speech
    t1: float
    sentence: int


@dataclass
class SceneAudio:
    samples: np.ndarray                          # float32 mono at SR (speech + pauses)
    sentences: list[tuple[str, float, float]]    # (text, start, end) relative to the start of speech
    words: list[Word] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return len(self.samples) / SR


def _resample(x: np.ndarray, sr: int) -> np.ndarray:
    if sr == SR or len(x) == 0:
        return x
    n = int(round(len(x) * SR / sr))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def trim_fade(x: np.ndarray) -> np.ndarray:
    """Cut near-silent edges and apply the short linear fades."""
    idx = np.flatnonzero(np.abs(x) >= TRIM_LEVEL)
    if len(idx) == 0:
        return x[:0]
    x = x[idx[0]: idx[-1] + 1].copy()
    n = min(int(FADE * SR), len(x) // 2)
    if n:
        ramp = np.linspace(0, 1, n, dtype=np.float32)
        x[:n] *= ramp
        x[-n:] *= ramp[::-1]
    return x


def _kind(text: str, dash: bool = False) -> str:
    if dash:
        return "dash"
    if text.endswith("..."):
        return "ellipsis"
    return {",": "comma", ";": "semicolon", ":": "colon", "?": "question", "!": "exclaim"}.get(text[-1:], "period")


def split_clauses(sentence: str) -> list[tuple[str, str]]:
    """Split one sentence into (spoken text, pause kind) pieces."""
    pieces = _CLAUSE_SEP.split(sentence)
    seps = _CLAUSE_SEP.findall(sentence)
    out = []
    for i, p in enumerate(pieces):
        p = p.strip()
        if not p:
            continue
        sep = seps[i] if i < len(seps) else ""
        out.append((p, _kind(p, dash=bool(sep.strip()))))
    return out


def is_emphatic(text: str) -> bool:
    """Clauses that carry stress: ALL-CAPS word, trailing '!' or an ellipsis -> spoken a little slower."""
    return bool(re.search(r"\b[A-Z]{2,}\b", text)) or text.endswith(("!", "..."))


def tokens(text: str) -> list[str]:
    return re.findall(r"[\w']+", text)


def _weight(word: str) -> float:
    syl = max(1, len(re.findall(r"[aeiouy]+", word.lower())))
    return syl + 0.12 * len(word)


def distribute_words(text: str, t0: float, t1: float, sentence: int) -> list[Word]:
    """Give each word of a clause a start/end, proportional to a syllable-based weight."""
    toks = tokens(text)
    if not toks:
        return []
    w = np.array([_weight(t) for t in toks])
    edges = t0 + (t1 - t0) * np.concatenate([[0], np.cumsum(w) / w.sum()])
    return [Word(t, float(edges[i]), float(edges[i + 1]), sentence) for i, t in enumerate(toks)]


def synth_scene(engine, text: str, cache: Path | None = None, key: str = "", pauses: dict | None = None,
                speed_mult: float = 1.0, expressive: bool = True) -> SceneAudio:
    pz = {**DEFAULT_PAUSES, **(pauses or {})}
    base_speed = float(getattr(engine, "speed", 1.0))
    pieces, sentences, words, t = [], [], [], 0.0
    sents = split_sentences(text)
    for si, sent in enumerate(sents):
        clauses = split_clauses(sent)
        s_start, s_end = None, 0.0
        for ci, (clause, kind) in enumerate(clauses):
            mult = speed_mult * (EMPHASIS_SPEED if expressive and is_emphatic(clause) else 1.0)
            h = hashlib.sha1(json.dumps([key, clause, round(mult, 3)]).encode()).hexdigest()[:20]
            f = cache / f"{h}.npy" if cache else None
            if f and f.exists():
                x = np.load(f)
            else:
                if abs(mult - 1.0) > 1e-6:
                    x, sr = engine.synthesize(clause, speed=base_speed * mult)
                else:
                    x, sr = engine.synthesize(clause)
                x = trim_fade(_resample(np.asarray(x, np.float32), sr))
                if f:
                    np.save(f, x)
            d = len(x) / SR
            if s_start is None:
                s_start = t
            words += distribute_words(clause, t, t + d, si)
            pieces.append(x)
            t += d
            s_end = t
            if not (si == len(sents) - 1 and ci == len(clauses) - 1):
                n_gap = int(pz[kind] * SR)
                pieces.append(np.zeros(n_gap, np.float32))
                t += n_gap / SR
        sentences.append((sent, s_start if s_start is not None else t, s_end))
    samples = np.concatenate(pieces) if pieces else np.zeros(0, np.float32)
    return SceneAudio(samples, sentences, words)


def build_track(script: Script, engine, cache: Path | None = None, lead: float | list[float] = 0.5, align: str | None = None):
    """Return (full float32 track, [(scene_start, scene_total, SceneAudio)]). `lead` may differ per scene."""
    leads = list(lead) if isinstance(lead, (list, tuple)) else [lead] * len(script.scenes)
    key = f"{engine.name}:{getattr(engine, 'voice', '')}:{getattr(engine, 'speed', '')}"
    expressive = script.voice.get("style", "expressive") != "plain"
    mode = align or script.align
    if mode == "auto":
        from . import align as AL

        mode = "whisper" if AL.available() else "proportional"
    if cache:
        cache.mkdir(parents=True, exist_ok=True)
    parts, timeline, t = [], [], 0.0
    for sc, lead in zip(script.scenes, leads):
        a = synth_scene(engine, sc.say, cache, key, script.pauses, sc.speed or 1.0, expressive)
        if mode == "whisper":
            from . import align as AL

            AL.refine_scene(a, cache)
        total = lead + a.duration + sc.pause_after
        n = int(round(total * SR))
        buf = np.zeros(n, np.float32)
        s0 = int(lead * SR)
        buf[s0:s0 + len(a.samples)] = a.samples[: n - s0]
        parts.append(buf)
        timeline.append((t, total, a))
        t += total
    return np.concatenate(parts), timeline


def frame_rms(x: np.ndarray, fps: int) -> np.ndarray:
    w = SR // fps
    n = len(x) // w + 1
    return np.array([np.sqrt(np.mean(x[i * w:(i + 1) * w] ** 2)) if len(x[i * w:(i + 1) * w]) else 0.0 for i in range(n)])


def speech_envelope(x: np.ndarray, fps: int) -> np.ndarray:
    """True for each video frame that has voice."""
    rms = frame_rms(x, fps)
    return rms > max(0.01, rms.max() * 0.06)


def mouth_levels(x: np.ndarray, fps: int) -> np.ndarray:
    """Mouth opening per video frame: 0 closed, 1 half, 2 open. Opens at once, closes slowly (~66 ms/step)."""
    rms = frame_rms(x, fps)
    loud = rms[rms > 0.01]
    ref = float(np.percentile(loud, 90)) if len(loud) else 1.0
    raw = np.where(rms < 0.006, 0, np.where(rms > 0.6 * ref, 2, np.where(rms > 0.18 * ref, 1, 0)))
    out = raw.copy()
    cur, hold = 0, 0
    for i, r in enumerate(raw):
        if r >= cur:
            cur, hold = int(r), 0
        elif rms[i] < 0.006:
            cur, hold = 0, 0
        else:
            hold += 1
            if hold >= 2:
                cur, hold = cur - 1, 0
        out[i] = cur
    return out
