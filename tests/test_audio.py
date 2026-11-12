import numpy as np

from explainer import audio as A
from explainer.script import parse


class FakeEngine:
    """Engine stand-in: 0.5 s of tone per sentence, so timing is predictable."""
    name = "fake"

    def synthesize(self, text):
        t = np.arange(12000) / 24000
        return (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), 24000


def test_track_timing_and_captions():
    sc = parse({"scenes": [
        {"say": "One. Two.", "pause_after": 0.5},
        {"say": "Three.", "pause_after": 1.0},
    ]})
    track, tl = A.build_track(sc, FakeEngine(), None, lead=0.5)
    (s0, tot0, a0), (s1, tot1, a1) = tl
    assert abs(a0.duration - (0.5 + A.GAP + 0.5)) < 0.01
    assert abs(tot0 - (0.5 + a0.duration + 0.5)) < 0.01
    assert abs(s1 - tot0) < 1e-6
    assert abs(len(track) / A.SR - (tot0 + tot1)) < 0.01
    assert [s[0] for s in a0.sentences] == ["One.", "Two."]
    assert a0.sentences[1][1] > a0.sentences[0][2]          # captions do not overlap
    env = A.speech_envelope(track, 30)
    assert env[int(0.8 * 30)] and not env[int(0.2 * 30)]    # voice on during speech, off during lead-in


def test_engine_registry_rejects_unknown():
    import pytest

    from explainer.tts import get_engine

    with pytest.raises(ValueError):
        get_engine("nope")
