"""Script (JSON) loading and validation."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .actions import ACTIONS

EMOTIONS = ("neutral", "happy", "thinking", "pointing")
SLIDE_TYPES = ("title", "bullets", "highlight")


class ScriptError(ValueError):
    """Raised when a script file is invalid."""


@dataclass
class Scene:
    say: str
    emotion: str = "neutral"
    slide: dict = field(default_factory=dict)
    pause_after: float = 0.5
    cues: list[dict] = field(default_factory=list)
    speed: float | None = None                  # speech speed override for this scene (voice speed multiplier)


@dataclass
class Script:
    title: str
    scenes: list[Scene]
    voice: dict = field(default_factory=dict)
    direction: dict = field(default_factory=dict)
    pauses: dict = field(default_factory=dict)  # silence per punctuation, seconds (see audio.DEFAULT_PAUSES)


def split_sentences(text: str) -> list[str]:
    """Split narration into sentences (used for TTS pieces and caption timing)."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p]


def _parse_cues(raw, where: str) -> list[dict]:
    if not isinstance(raw, list):
        raise ScriptError(f"{where}: 'cues' must be a list")
    out = []
    for j, c in enumerate(raw, 1):
        w = f"{where}, cue {j}"
        if not isinstance(c, dict):
            raise ScriptError(f"{w}: must be an object")
        if c.get("do") not in ACTIONS:
            raise ScriptError(f"{w}: unknown action {c.get('do')!r} (use one of {', '.join(ACTIONS)})")
        anchors = [k for k in ("on", "word", "at") if k in c]
        if len(anchors) != 1:
            raise ScriptError(f"{w}: give exactly one of 'on', 'word' or 'at'")
        if "on" in c and not (isinstance(c["on"], str) and c["on"].strip()):
            raise ScriptError(f"{w}: 'on' must be text, 'start' or 'end'")
        if "word" in c and (not isinstance(c["word"], int) or isinstance(c["word"], bool) or c["word"] < 0):
            raise ScriptError(f"{w}: 'word' must be a non-negative integer")
        if "at" in c and (not isinstance(c["at"], (int, float)) or isinstance(c["at"], bool) or c["at"] < 0):
            raise ScriptError(f"{w}: 'at' must be seconds from the scene start")
        hold = c.get("hold")
        if hold is not None and (not isinstance(hold, (int, float)) or isinstance(hold, bool) or not 0.1 <= hold <= 6):
            raise ScriptError(f"{w}: 'hold' must be between 0.1 and 6 seconds")
        out.append(dict(c))
    return out


def parse(data: dict) -> Script:
    if not isinstance(data, dict):
        raise ScriptError("script must be a JSON object")
    scenes_raw = data.get("scenes")
    if not isinstance(scenes_raw, list) or not scenes_raw:
        raise ScriptError("'scenes' must be a non-empty list")
    scenes = []
    for i, s in enumerate(scenes_raw, 1):
        where = f"scene {i}"
        if not isinstance(s, dict):
            raise ScriptError(f"{where}: must be an object")
        say = s.get("say")
        if not isinstance(say, str) or not say.strip():
            raise ScriptError(f"{where}: 'say' must be a non-empty string")
        emotion = s.get("emotion", "neutral")
        if emotion not in EMOTIONS:
            raise ScriptError(f"{where}: unknown emotion {emotion!r} (use one of {', '.join(EMOTIONS)})")
        slide = s.get("slide", {})
        if not isinstance(slide, dict):
            raise ScriptError(f"{where}: 'slide' must be an object")
        stype = slide.get("type", "title")
        if stype not in SLIDE_TYPES:
            raise ScriptError(f"{where}: unknown slide type {stype!r} (use one of {', '.join(SLIDE_TYPES)})")
        if stype == "bullets" and not (isinstance(slide.get("items"), list) and slide["items"]):
            raise ScriptError(f"{where}: 'bullets' slide needs a non-empty 'items' list")
        if stype == "highlight" and not slide.get("highlight"):
            raise ScriptError(f"{where}: 'highlight' slide needs 'highlight' text")
        pause = s.get("pause_after", 0.5)
        if not isinstance(pause, (int, float)) or isinstance(pause, bool) or not 0 <= pause <= 10:
            raise ScriptError(f"{where}: 'pause_after' must be a number between 0 and 10")
        cues = _parse_cues(s.get("cues", []), where)
        speed = s.get("speed")
        if speed is not None and (not isinstance(speed, (int, float)) or isinstance(speed, bool) or not 0.5 <= speed <= 2):
            raise ScriptError(f"{where}: 'speed' must be a number between 0.5 and 2")
        scenes.append(Scene(say=say.strip(), emotion=emotion, slide={**slide, "type": stype}, pause_after=float(pause),
                            cues=cues, speed=None if speed is None else float(speed)))
    voice = data.get("voice", {})
    if not isinstance(voice, dict):
        raise ScriptError("'voice' must be an object")
    direction = data.get("direction", {})
    pauses = data.get("pauses", {})
    if not isinstance(direction, dict) or not isinstance(pauses, dict):
        raise ScriptError("'direction' and 'pauses' must be objects")
    for k, v in pauses.items():
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not 0 <= v <= 5:
            raise ScriptError(f"'pauses.{k}' must be a number of seconds between 0 and 5")
    return Script(title=str(data.get("title", "Untitled")), scenes=scenes, voice=voice, direction=direction, pauses=pauses)


def load(path: str | Path) -> Script:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ScriptError(f"invalid JSON: {e}") from e
    return parse(data)
