"""Gesture vocabulary: script action name -> body pose family in the sprite sheet.

Each family `<base>` has three tags: `<base>_entra_s` (enter), `<base>_s` (loop) and `<base>_sai_s` (leave).
"""
from __future__ import annotations

# action: (pose family or None, default hold in seconds)
ACTIONS: dict[str, tuple[str | None, float]] = {
    "wave": ("acenar", 1.3),
    "bow_wave": ("acenar", 1.0),
    "point_slide": ("apontar_slide", 1.0),
    "point_down": ("apontar_baixo", 1.0),
    "point_self": ("explicar_abertas", 0.8),   # no dedicated pose: open hands
    "think_chin": ("pensar_queixo", 1.6),
    "think": ("pensar_queixo", 1.6),
    "think_simple": ("pensando", 1.2),
    "celebrate": ("comemorar", 1.1),
    "explain_open": ("explicar_abertas", 1.0),
    "shrug": ("ombros", 0.9),
    "turn_slide": ("olhar_slide", 0.5),
    "happy": ("feliz", 1.0),
    "happy_beat": ("feliz", 0.9),
    "surprise": ("surpresa", 1.0),
    "explain_beat": (None, 0.3),               # body bounce in code, no pose change
    "look_slide": ("olhar_slide", 1.0),
}

# stage actions: where Bit is and which way he faces (handled by explainer.stage, not by gestures)
STAGE_ACTIONS = ("enter", "walk_to", "exit", "turn")
