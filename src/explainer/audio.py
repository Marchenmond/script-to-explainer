"""Build the narration track and per-sentence timings (engine independent)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .script import Script, split_sentences

SR = 24000
GAP = 0.18  # seconds of silence between sentences


@dataclass
class SceneAudio:
    samples: np.ndarray                          # float32 mono at SR (speech + inter-sentence gaps)
    sentences: list[tuple[str, float, float]]    # (text, start, end) relative to the start of speech

    @property
    def duration(self) -> float:
        return len(self.samples) / SR


def _resample(x: np.ndarray, sr: int) -> np.ndarray:
    if sr == SR or len(x) == 0:
        return x
    n = int(round(len(x) * SR / sr))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def synth_scene(engine, text: str, cache: Path | None = None, key: str = "") -> SceneAudio:
    pieces, sentences, t = [], [], 0.0
    gap = np.zeros(int(GAP * SR), np.float32)
    for sent in split_sentences(text):
        h = hashlib.sha1(json.dumps([key, sent]).encode()).hexdigest()[:20]
        f = cache / f"{h}.npy" if cache else None
        if f and f.exists():
            x = np.load(f)
        else:
            x, sr = engine.synthesize(sent)
            x = _resample(np.asarray(x, np.float32), sr)
            if f:
                np.save(f, x)
        sentences.append((sent, t, t + len(x) / SR))
        pieces += [x, gap]
        t += len(x) / SR + GAP
    samples = np.concatenate(pieces[:-1]) if pieces else np.zeros(0, np.float32)
    return SceneAudio(samples, sentences)


def build_track(script: Script, engine, cache: Path | None = None, lead: float = 0.5):
    """Return (full float32 track, [(scene_start, scene_total, SceneAudio)])."""
    key = f"{engine.name}:{getattr(engine, 'voice', '')}:{getattr(engine, 'speed', '')}"
    if cache:
        cache.mkdir(parents=True, exist_ok=True)
    parts, timeline, t = [], [], 0.0
    for sc in script.scenes:
        a = synth_scene(engine, sc.say, cache, key)
        total = lead + a.duration + sc.pause_after
        n = int(round(total * SR))
        buf = np.zeros(n, np.float32)
        s0 = int(lead * SR)
        buf[s0:s0 + len(a.samples)] = a.samples[: n - s0]
        parts.append(buf)
        timeline.append((t, total, a))
        t += total
    return np.concatenate(parts), timeline


def speech_envelope(x: np.ndarray, fps: int) -> np.ndarray:
    """True for each video frame that has voice (drives the simple mouth sync)."""
    w = SR // fps
    n = len(x) // w + 1
    rms = np.array([np.sqrt(np.mean(x[i * w:(i + 1) * w] ** 2)) if len(x[i * w:(i + 1) * w]) else 0.0 for i in range(n)])
    on = rms > max(0.01, rms.max() * 0.06)
    out = on.copy()
    for i in range(n):  # close tiny gaps so the mouth does not flicker
        if not on[i] and on[max(0, i - 3):i].any() and on[i + 1:i + 4].any():
            out[i] = True
    return out
