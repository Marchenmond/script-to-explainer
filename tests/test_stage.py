import numpy as np
import pytest

from explainer import audio as A
from explainer import direction as D
from explainer import stage as ST
from explainer.script import parse


class Tone:
    name = "fake"

    def synthesize(self, text, speed=None):
        n = int(0.12 * 24000 * max(1, len(text.split())))
        t = np.arange(n) / 24000
        return (0.3 * np.sin(2 * np.pi * 200 * t)).astype(np.float32), 24000


def plan_for(data):
    sc = parse(data)
    leads = [D.lead_for(s, 0.5, D.settings(sc.direction)) for s in sc.scenes]
    track, tl = A.build_track(sc, Tone(), None, leads)
    return ST.StagePlan(sc, tl, leads, 0.5), tl


def scene(say, **kw):
    return {"say": say, "slide": {"type": "title", "title": "x"}, **kw}


def test_walk_profile_is_trapezoid_and_matches_formula():
    v, ta, td, total = ST.walk_profile(320, 240, 0.2, 0.25)
    assert abs(total - (320 / 240 + 0.225)) < 1e-9                  # |dx|/v + (accel+decel)/2
    m = ST.Move(0.0, 1500, 1180, 240, 0.2, 0.25)
    assert m.x(0.0) == 1500 and abs(m.x(m.t1) - 1180) < 1e-6 and m.direction == -1
    speeds = [abs(m.x(t + 0.01) - m.x(t)) / 0.01 for t in np.arange(0, m.t1 - 0.01, 0.01)]
    assert max(speeds) <= 240 * 1.01 and speeds[0] < 40             # no instant start
    assert all(b >= a - 1e-6 for a, b in zip([m.travelled(t) for t in np.arange(0, m.t1, 0.05)],
                                              [m.travelled(t) for t in np.arange(0.05, m.t1 + 0.05, 0.05)]))


def test_walking_phase_follows_distance_not_clock():
    plan, _ = plan_for({"scenes": [scene("Hello there my friend, look at this thing now.",
                                         cues=[{"on": "Hello", "do": "enter", "from": "off", "x": "R"}])]})
    m = plan.moves[0]
    steps = ST.walk_steps(plan.cfg["walk"]["stride_px"])
    for t in np.arange(m.t0 + 0.2, m.t1 - 0.2, 0.05):
        lay = plan.layers(t)
        tag, k, w = lay[0]
        assert tag == "andando_w" and k == ST.walk_frame(m.travelled(t), steps)
    assert plan.x(0.0) == 2080 and abs(plan.x(m.t1 + 1) - plan.cfg['stations']['R']) < 1e-6


def test_walk_to_starts_in_time_for_the_next_gesture():
    data = {"scenes": [scene("Look here now. We walk to the slide and then we point at this result right away.",
                             cues=[{"on": "walk", "do": "walk_to", "x": "N", "face": "slide"},
                                   {"on": "point", "do": "point_slide", "target": "title"}])]}
    plan, tl = plan_for(data)
    m = next(m for m in plan.moves if m.kind == "walk")
    g = next(g for g in plan.choreo.gestures if g.action == "point_slide")
    assert m.t1 <= g.onset - 0.1 + 1e-6                            # arrived before the arm goes up
    assert not plan.errors


def test_walk_that_cannot_fit_is_an_error_not_a_late_gesture():
    sc = parse({"scenes": [scene("Go now point. Then more words follow afterwards.",
                                 cues=[{"on": "Go", "do": "walk_to", "x": 1100}, {"on": "point", "do": "point_slide"}])]})
    leads = [0.5]
    track, tl = A.build_track(sc, Tone(), None, leads)
    p = ST.StagePlan(sc, tl, leads, 0.5)
    assert p.errors and "does not fit" in p.errors[0]


def test_short_move_is_a_weight_shift_and_area_is_enforced():
    plan, _ = plan_for({"scenes": [scene("Hello there my friend, welcome home.", cues=[{"on": "Hello", "do": "enter", "x": "H"},
                                                                                      {"on": "friend", "do": "walk_to", "x": 1550}])]})
    assert any(m.kind == "shift" for m in plan.moves)
    with pytest.raises(ST.StageError):
        plan_for({"scenes": [scene("Hello there.", cues=[{"on": "Hello", "do": "walk_to", "x": 900}])]})


def test_camera_views_are_clamped_inside_the_world():
    plan, _ = plan_for({"scenes": [scene("Hello there my friend, welcome home to the show.",
                                         camera=[{"on": "start", "view": "wide"}, {"on": "friend", "view": "bit"}])]})
    for c in plan.camera:
        z = c["zoom"]
        assert 960 / z - 0.06 <= c["cx"] <= 1920 - 960 / z + 0.06 and 540 / z - 0.06 <= c["cy"] <= 1080 - 540 / z + 0.06
        assert 1.0 <= z <= 1.15


def test_elements_marks_reveals_counts_and_rings():
    data = {"scenes": [{"say": "First item one thousand. Second thing here today.",
                        "slide": {"type": "bullets", "title": "T", "items": ["Slides at 1080p", "Other"]},
                        "emph": [{"on": "Second", "target": "item:1", "style": "mark"}],
                        "reveal": [{"item": 0, "on": "First"}, {"item": 1, "on": "Second"}],
                        "count": [{"item": 0, "from": 0, "to": 1080, "on": "thousand"}],
                        "cues": [{"on": "Second", "do": "point_slide", "target": "item:1"}]}]}
    plan, tl = plan_for(data)
    el = plan.elements()
    assert el["marks"][0]["target"] == "item:1" and abs(el["marks"][0]["t_word"] - el["marks"][0]["t"] - 0.12) < 1e-6
    assert [r["item"] for r in el["reveals"]] == [0, 1]
    assert el["counts"][0]["to"] == 1080 and el["counts"][0]["ms"] == 750
    assert el["rings"][0]["target"] == "item:1" and el["rings"][0]["t_in"] < el["rings"][0]["t_click"]


def test_walk_steps_are_calibrated_on_the_sprite_and_cover_every_frame():
    steps = ST.walk_steps(None)
    assert len(steps) == 6 and all(4 <= s <= 24 for s in steps)
    assert ST.walk_steps(120) == [20.0] * 6
    seen = {ST.walk_frame(d, steps) for d in np.arange(0, sum(steps), 1.0)}
    assert seen == {0, 1, 2, 3, 4, 5}
    assert ST.walk_frame(sum(steps) + 1, steps) == ST.walk_frame(1, steps)    # cycles


def test_snap_moves_the_body_by_exactly_the_sole_movement_of_each_frame():
    plan, _ = plan_for({"scenes": [scene("Hello there my friend, welcome home to the show today.",
                                         cues=[{"on": "Hello", "do": "enter", "from": "off", "x": "R"}])]})
    m = plan.moves[0]
    steps = ST.walk_steps(None, "andando_w")
    xs = [plan.x(t) for t in np.arange(m.t0 + 0.3, m.t1 - 0.3, 1 / 30)]
    jumps = [abs(b - a) for a, b in zip(xs, xs[1:]) if abs(b - a) > 1e-9]
    assert jumps and all(any(abs(j - s) < 1e-6 for s in steps) for j in jumps)      # each jump = one frame's distance
    assert min(steps) >= 8                                                          # no frame shorter than a video frame at 240 px/s
    assert abs(plan.x(m.t1 + 0.01) - plan.cfg["stations"]["R"]) < 1e-6


def test_camera_keeps_slide_text_inside_the_margin():
    plan, _ = plan_for({"scenes": [scene("Hello there my friend, welcome home to the show.",
                                         camera=[{"on": "friend", "view": "bit", "zoom": 1.1}])]})
    ic = plan.cfg["idle_camera"]
    for c in plan.camera:
        zmax = c["zoom"] * ic["zoom_to"]
        left = (130 - c["cx"]) * zmax + 960 - ic["pan_px"] * zmax     # slide text starts at x=130
        assert left >= 60 - 0.5
