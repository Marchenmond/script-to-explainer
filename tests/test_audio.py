import numpy as np

from explainer import audio as A
from explainer.script import parse


class FakeEngine:
    """Engine stand-in: 0.5 s of tone per sentence, so timing is predictable."""
    name = "fake"

    def synthesize(self, text, speed=None):
        t = np.arange(12000) / 24000
        return (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), 24000


def test_track_timing_and_captions():
    sc = parse({"scenes": [
        {"say": "One. Two.", "pause_after": 0.5},
        {"say": "Three.", "pause_after": 1.0},
    ]})
    track, tl = A.build_track(sc, FakeEngine(), None, lead=0.5)
    (s0, tot0, a0), (s1, tot1, a1) = tl
    assert abs(a0.duration - (0.5 + A.DEFAULT_PAUSES['period'] + 0.5)) < 0.02
    assert abs(tot0 - (0.5 + a0.duration + 0.5)) < 0.02
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


def test_clauses_pauses_and_words():
    pieces = A.split_clauses("Hi, I am Bit - not a human, really!")
    assert [p[0] for p in pieces] == ["Hi,", "I am Bit", "not a human,", "really!"]
    assert [p[1] for p in pieces] == ["comma", "dash", "comma", "exclaim"]
    sc = parse({"scenes": [{"say": "One, two three."}]})
    track, tl = A.build_track(sc, FakeEngine(), None, lead=0.5)
    a = tl[0][2]
    assert abs(a.duration - (1.0 + A.DEFAULT_PAUSES["comma"])) < 0.02
    assert [w.text for w in a.words] == ["One", "two", "three"]
    assert all(w1.t1 <= w2.t0 + 1e-6 for w1, w2 in zip(a.words, a.words[1:]))


def test_custom_pauses_and_speed_override():
    calls = []

    class E(FakeEngine):
        speed = 1.0

        def synthesize(self, text, speed=None):
            calls.append((text, speed))
            return super().synthesize(text)

    sc = parse({"pauses": {"comma": 1.0}, "scenes": [{"say": "A, b. LOUD thing.", "speed": 0.8}]})
    track, tl = A.build_track(sc, E(), None, lead=0.5)
    assert tl[0][2].duration > 1.0 + 0.45 + 1.5 - 0.1
    speeds = [s for _, s in calls if s]
    assert any(abs(s - 0.8) < 1e-6 for s in speeds) and any(abs(s - 0.72) < 1e-6 for s in speeds)


def test_mouth_closes_in_silence_and_follows_volume():
    t = np.arange(24000) / 24000
    x = np.concatenate([np.zeros(12000), (0.3 * np.sin(2 * np.pi * 200 * t)).astype(np.float32), np.zeros(12000)])
    lv = A.mouth_levels(x, 30)
    assert lv[3] == 0 and lv[-3] == 0 and lv[30] == 2


def test_whisper_refine_replaces_matched_words_and_interpolates_the_rest():
    from explainer import align as AL

    ws = A.distribute_words("one two three four five", 0.0, 2.5, 0)
    heard = [("one", 0.10, 0.4), ("two", 0.55, 0.9), ("four", 1.6, 1.9), ("five", 2.0, 2.4)]
    out = AL.refine(ws, heard)
    assert [w.text for w in out] == ["one", "two", "three", "four", "five"]
    assert abs(out[0].t0 - 0.10) < 1e-9 and abs(out[3].t0 - 1.6) < 1e-9
    assert 0.9 <= out[2].t0 <= 1.6                       # "three" was not heard: placed between its neighbours
    assert all(a.t0 <= b.t0 for a, b in zip(out, out[1:]))


def test_proportional_words_stay_in_order_and_inside_the_clause():
    ws = A.distribute_words("Hello there my friend", 1.0, 3.0, 0)
    assert abs(ws[0].t0 - 1.0) < 1e-9 and abs(ws[-1].t1 - 3.0) < 1e-9
    assert all(a.t1 <= b.t0 + 1e-9 for a, b in zip(ws, ws[1:]))
