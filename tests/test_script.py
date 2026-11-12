import copy

import pytest

from explainer import script as S

GOOD = {"scenes": [{"say": "Hello. World!", "emotion": "happy", "slide": {"type": "bullets", "items": ["a"]}}]}


def test_valid_script_parses():
    sc = S.parse(GOOD)
    assert len(sc.scenes) == 1 and sc.scenes[0].emotion == "happy"
    assert S.split_sentences("Hello. World! Ok?") == ["Hello.", "World!", "Ok?"]


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(scenes=[]),
    lambda d: d["scenes"][0].update(say="  "),
    lambda d: d["scenes"][0].update(emotion="angry"),
    lambda d: d["scenes"][0]["slide"].update(type="video"),
    lambda d: d["scenes"][0]["slide"].update(items=[]),
    lambda d: d["scenes"][0].update(pause_after=-1),
])
def test_invalid_scripts_rejected(mutate):
    bad = copy.deepcopy(GOOD)
    mutate(bad)
    with pytest.raises(S.ScriptError):
        S.parse(bad)


def test_demo_script_is_valid():
    from pathlib import Path

    sc = S.load(Path(__file__).parent.parent / "examples" / "demo.json")
    assert len(sc.scenes) >= 5


def test_cues_and_pauses_validated():
    good = {"pauses": {"comma": 0.3}, "scenes": [{"say": "Hi there.", "cues": [{"on": "Hi", "do": "wave", "hold": 1}]}]}
    assert S.parse(good).scenes[0].cues[0]["do"] == "wave"
    for bad in (
        {"scenes": [{"say": "Hi.", "cues": [{"do": "wave"}]}]},
        {"scenes": [{"say": "Hi.", "cues": [{"on": "Hi", "at": 1, "do": "wave"}]}]},
        {"scenes": [{"say": "Hi.", "cues": [{"on": "Hi", "do": "wave", "hold": 99}]}]},
        {"pauses": {"comma": -1}, "scenes": [{"say": "Hi."}]},
        {"scenes": [{"say": "Hi.", "speed": 5}]},
    ):
        with pytest.raises(S.ScriptError):
            S.parse(bad)
