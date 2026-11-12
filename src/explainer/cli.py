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
    r.add_argument("--fps", type=int, default=30)
    r.add_argument("--preview", action="store_true", help="only write one PNG per scene (no video)")
    v = sub.add_parser("validate", help="check a script without rendering")
    v.add_argument("script")
    a = ap.parse_args(argv)

    try:
        sc = S.load(a.script)
    except (S.ScriptError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if a.cmd == "validate":
        print(f"ok: {len(sc.scenes)} scenes")
        return 0

    from .render import render
    from .tts import get_engine

    opts = dict(sc.voice)
    name = a.engine or opts.pop("engine", "kokoro")
    opts.pop("engine", None)
    try:
        engine = get_engine(name, **opts)
        info = render(sc, engine, Path(a.out), fps=a.fps, preview=a.preview)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(info))
    return 0
