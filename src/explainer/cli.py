"""Command line: python -m explainer render script.json -o out/video.mp4"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import script as S


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="explainer", description="Turn a JSON script into a narrated explainer video.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render", help="render a script to MP4")
    r.add_argument("script")
    r.add_argument("-o", "--out", default="out/video.mp4")
    r.add_argument("--engine", help="speech engine: kokoro (default) or azure; overrides the script")
    r.add_argument("--voice", help="voice name or a mix such as am_puck:0.7,am_fenrir:0.3 (overrides the script)")
    r.add_argument("--speed", type=float, help="base speech speed (overrides the script)")
    r.add_argument("--pause-comma", type=float, help="seconds of silence after a comma (overrides the script)")
    r.add_argument("--pause-period", type=float, help="seconds of silence after a sentence end (overrides the script)")
    r.add_argument("--cue-frames", help="folder where one PNG per cue is written (frame at the cue's word)")
    r.add_argument("--renderer", choices=("hf", "pillow"), default="hf",
                   help="hf (default): HyperFrames draws the motion layer; pillow: simple built-in renderer, no motion layer")
    r.add_argument("--align", choices=("auto", "proportional", "whisper"), help="word timing (overrides the script)")
    r.add_argument("--fps", type=int, default=30)
    r.add_argument("--preview", action="store_true", help="only write one PNG per scene (no video)")
    c = sub.add_parser("check", help="check a rendered video against the acceptance criteria")
    c.add_argument("stem", help="output stem, for example out/demo")
    c.add_argument("--table", help="write the cue table (markdown) to this file")
    v = sub.add_parser("validate", help="check a script without rendering")
    v.add_argument("script")
    a = ap.parse_args(argv)

    if a.cmd == "check":
        from .checks import main as check_main

        return check_main([a.stem] + (["--table", a.table] if a.table else []))
    try:
        sc = S.load(a.script)
    except (S.ScriptError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if a.cmd == "validate":
        print(f"ok: {len(sc.scenes)} scenes")
        return 0

    from .hfrender import render_hf
    from .render import render
    from .tts import get_engine

    if a.align:
        sc.align = a.align
    opts = dict(sc.voice)
    if a.voice:
        opts["voice"] = a.voice
    if a.speed:
        opts["speed"] = a.speed
    if a.pause_comma is not None:
        sc.pauses["comma"] = a.pause_comma
    if a.pause_period is not None:
        sc.pauses["period"] = a.pause_period
    opts.pop("style", None)
    name = a.engine or opts.pop("engine", "kokoro")
    opts.pop("engine", None)
    try:
        engine = get_engine(name, **opts)
        fn = render_hf if a.renderer == "hf" else render
        info = fn(sc, engine, Path(a.out), fps=a.fps, preview=a.preview,
                      snapshots=Path(a.cue_frames) if a.cue_frames else None)
    except (RuntimeError, ValueError) as e:  # includes StageError
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(info))
    return 0
