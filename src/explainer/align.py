"""Word timing. Default: proportional to a syllable estimate (audio.distribute_words), good to about +-250 ms.
Optional: faster-whisper (local, offline once the model is cached) re-times each word from the audio itself.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
from pathlib import Path

import numpy as np

from .audio import SR, SceneAudio, Word

MODEL = "small"


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def norm(w: str) -> str:
    return re.sub(r"[^a-z0-9']", "", w.lower())


_model = None


def _whisper():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(MODEL, device="cpu", compute_type="int8")
    return _model


def transcribe_words(samples: np.ndarray, cache: Path | None = None) -> list[tuple[str, float, float]]:
    key = hashlib.sha1(samples.tobytes()).hexdigest()[:20]
    f = cache / f"whisper_{MODEL}_{key}.json" if cache else None
    if f and f.exists():
        return [tuple(x) for x in json.loads(f.read_text(encoding="utf-8"))]
    pcm = np.interp(np.arange(0, len(samples), SR / 16000), np.arange(len(samples)), samples).astype(np.float32)
    segs, _ = _whisper().transcribe(pcm, language="en", word_timestamps=True, vad_filter=False)
    out = [(norm(w.word), float(w.start), float(w.end)) for s in segs for w in (s.words or [])]
    if f:
        f.write_text(json.dumps(out), encoding="utf-8")
    return out


def refine(words: list[Word], heard: list[tuple[str, float, float]]) -> list[Word]:
    """Replace the estimated times of every word that Whisper also heard; interpolate the rest between neighbours."""
    ours = [norm(w.text) for w in words]
    theirs = [h[0] for h in heard]
    start = [None] * len(words)
    end = [None] * len(words)
    for blk in difflib.SequenceMatcher(None, ours, theirs, autojunk=False).get_matching_blocks():
        for k in range(blk.size):
            start[blk.a + k], end[blk.a + k] = heard[blk.b + k][1], heard[blk.b + k][2]
    # unmatched words: spread evenly in the gap between the nearest matched neighbours
    i = 0
    while i < len(words):
        if start[i] is not None:
            i += 1
            continue
        j = i
        while j < len(words) and start[j] is None:
            j += 1
        a = end[i - 1] if i > 0 else words[i].t0
        b = start[j] if j < len(words) else words[j - 1].t1
        n = j - i
        for k in range(n):
            start[i + k] = a + (b - a) * k / n
            end[i + k] = a + (b - a) * (k + 1) / n
        i = j
    out = []
    for k, w in enumerate(words):
        t0 = start[k]
        t1 = max(end[k], t0 + 0.04)
        if k + 1 < len(words):
            t1 = min(t1, max(start[k + 1], t0 + 0.04))
        out.append(Word(w.text, float(t0), float(t1), w.sentence))
    return out


def refine_scene(a: SceneAudio, cache: Path | None = None) -> SceneAudio:
    a.words = refine(a.words, transcribe_words(a.samples, cache))
    return a
