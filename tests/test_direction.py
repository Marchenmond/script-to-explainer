import numpy as np
import pytest

from explainer import audio as A
from explainer import direction as D
from explainer.script import ScriptError, parse


class Tone:
    name = "fake"

    def synthesize(self, text, speed=None):
        n = int(0.12 * 24000 * max(1, len(text.split())))
        t = np.arange(n) / 24000
        return (0.3 * np.sin(2 * np.pi * 200 * t)).astype(np.float32), 24000


def build(data):
    sc = parse(data)
    leads = [D.lead_for(s, 0.5, D.settings(sc.direction)) for s in sc.scenes]
    track, tl = A.build_track(sc, Tone(), None, leads)
    return sc, tl, leads, D.plan(sc, tl, None, 0.5, leads)


def scene(say, **kw):
    return {"say": say, "slide": {"type": "title", "title": "x"}, **kw}


def test_cue_anchors_on_word_with_anticipation():
    sc, tl, leads, ch = build({"scenes": [scene("Hello there. Look at this result now.",
                                                cues=[{"on": "Look", "do": "point_slide"}])]})
    g = next(g for g in ch.gestures if g.source == "manual")
    row = next(r for r in ch.log if r["source"] == "manual")
    assert 150 <= row["antecipacao_ms"] <= 250                  # starts 200 ms before the word
    assert abs(row["diferenca_ms"]) <= 250                      # key pose lands on the word
    assert g.word == "Look" and abs(g.word_t - (leads[0] + tl[0][2].words[2].t0)) < 1e-6


def test_unknown_cue_text_is_an_error():
    with pytest.raises(ValueError):
        build({"scenes": [scene("Hello world.", cues=[{"on": "banana", "do": "wave"}])]})
    with pytest.raises(ScriptError):
        parse({"scenes": [scene("Hello.", cues=[{"on": "Hello", "do": "dance"}])]})


def test_auto_rules_greeting_question_and_goodbye():
    data = {"scenes": [scene("Hi, I am Bit and this is a short demo for you today. Do you want to see this done? It works great."),
                       scene("That is it. Bye now.")]}
    sc, tl, leads, ch = build(data)
    kinds = [g.action for g in ch.gestures]
    assert kinds[0] == "wave"                                   # greeting on the first sentence
    assert "think_chin" in kinds                                # question
    q0, q1 = tl[0][2].sentences[1][1] + leads[0], tl[0][2].sentences[1][2] + leads[0]
    for g in ch.gestures:                                       # nothing contradictory inside the question
        if g.scene == 0 and q0 <= g.word_t <= q1:
            assert g.action not in ("celebrate", "wave", "bow_wave")
    assert kinds[-1] in ("wave", "bow_wave")                    # goodbye at the end


def test_manual_wins_and_auto_keeps_spacing():
    data = {"scenes": [scene("Hi there. This is a long enough sentence to look at the screen and the command today.",
                             cues=[{"on": "Hi", "do": "wave"}])]}
    sc, tl, leads, ch = build(data)
    for g in (g for g in ch.gestures if g.source == "auto"):
        for o in (o for o in ch.gestures if o.source == "manual"):
            assert abs(g.onset - o.onset) >= 1.5 - 1e-6
    assert any(g.source == "manual" and g.action == "wave" for g in ch.gestures)


def test_never_long_same_pose_and_same_action_cues_merge():
    long = " ".join(["word"] * 60) + "."
    sc, tl, leads, ch = build({"scenes": [scene(long)]})
    prev_end, longest = 0.0, 0.0
    for o, e in sorted((g.onset, g.end) for g in ch.gestures):
        longest = max(longest, o - prev_end)
        prev_end = max(prev_end, e)
    assert max(longest, tl[0][1] - prev_end) <= 3.5
    ch = build({"scenes": [scene("one two three four five six.", cues=[{"on": "two", "do": "point_slide"},
                                                                       {"on": "three", "do": "point_slide"}])]})[3]
    assert sum(1 for g in ch.gestures if g.action == "point_slide") == 1
    assert any(r["status"] == "merged" for r in ch.log)


def test_scene_mood_shows_while_talking():
    ch = build({"scenes": [scene("Some words here to say out loud for a while today friend.", emotion="happy")]})[3]
    assert any(g.action in ("happy_beat", "wave", "celebrate") for g in ch.gestures)


def test_layers_weights_sum_to_one():
    data = {"scenes": [scene("Hi there friend, welcome.", cues=[{"on": "Hi", "do": "wave"}])]}
    sc, tl, leads, ch = build(data)
    for i in range(0, 120):
        assert abs(sum(w for _, _, w in ch.layers(i / 30)) - 1) < 1e-6
