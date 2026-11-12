"""Script (JSON) loading and validation."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

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


@dataclass
class Script:
    title: str
    scenes: list[Scene]
    voice: dict = field(default_factory=dict)


def split_sentences(text: str) -> list[str]:
    """Split narration into sentences (used for TTS pieces and caption timing)."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p]


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
        scenes.append(Scene(say=say.strip(), emotion=emotion, slide={**slide, "type": stype}, pause_after=float(pause)))
    voice = data.get("voice", {})
    if not isinstance(voice, dict):
        raise ScriptError("'voice' must be an object")
    return Script(title=str(data.get("title", "Untitled")), scenes=scenes, voice=voice)


def load(path: str | Path) -> Script:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ScriptError(f"invalid JSON: {e}") from e
    return parse(data)
