"""Render with HyperFrames: Python directs (voice, word timing, stage plan), the HTML composition draws.

Steps: synthesize the narration, plan the stage, write a small HyperFrames project (HTML + GSAP + sprites +
`stage-data.js`), let HyperFrames render the picture to MP4, then mix the narration in with ffmpeg (-16 LUFS).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from . import audio as A
from . import direction as D
from . import sprites as SP
from . import stage as ST
from .render import LEAD, LOUDNESS, check_ffmpeg, write_srt, write_wav
from .timeline import Stage

PKG = Path(__file__).resolve().parent
HF_VERSION = "0.8.174"


def repo_root() -> Path:
    return PKG.parents[1]


def hyperframes_cmd() -> list[str]:
    """Command that runs the pinned, locally installed HyperFrames (npm install in the repo root)."""
    root = repo_root()
    mjs = root / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs"
    node = shutil.which("node")
    if not mjs.exists() or not node:
        raise RuntimeError("HyperFrames is not installed: run `npm install` in the project folder (needs Node.js 22 or newer)")
    return [node, str(mjs)]


def chrome_path() -> str:
    """Chrome used by HyperFrames (downloaded on first use)."""
    r = subprocess.run([*hyperframes_cmd(), "browser", "path"], capture_output=True, text=True,
                       env={**os.environ, "HYPERFRAMES_NO_TELEMETRY": "1"})
    return r.stdout.strip().splitlines()[-1]


def measure_text(proj: Path, step: float = 0.2) -> list[dict]:
    """Real text boxes (slide text and captions) over time, measured in Chrome on the composition."""
    node = shutil.which("node")
    script = PKG / "hf" / "measure.mjs"
    tmp = repo_root() / "node_modules" / ".measure.mjs"      # must live where `puppeteer-core` resolves
    shutil.copy(script, tmp)
    try:
        r = subprocess.run([node, str(tmp), str(proj), chrome_path(), str(step)], capture_output=True, text=True)
    finally:
        tmp.unlink(missing_ok=True)
    if r.returncode != 0:
        raise RuntimeError("text measurement failed: " + r.stderr[-400:])
    return json.loads(r.stdout)


def blink_sheet(src: Path, dst: Path) -> None:
    """Same layout as the pose sheet, with the eyes closed on every frame that has open eyes."""
    sheet = Image.open(src).convert("RGBA")
    out = sheet.copy()
    cols = sheet.width // SP.CELL
    for i in range(cols * (sheet.height // SP.CELL)):
        x, y = (i % cols) * SP.CELL, (i // cols) * SP.CELL
        cell = sheet.crop((x, y, x + SP.CELL, y + SP.CELL))
        closed = SP._closed_eyes(cell, 25)
        if closed is not None:
            out.paste(closed, (x, y))
    out.save(dst)


def write_project(proj: Path, stage: dict) -> None:
    root = repo_root()
    gsap = root / "node_modules" / "gsap" / "dist" / "gsap.min.js"
    if not gsap.exists():
        raise RuntimeError("GSAP is not installed: run `npm install` in the project folder")
    for sub in ("assets/vendor", "assets/fonts", "assets/bit"):
        (proj / sub).mkdir(parents=True, exist_ok=True)
    shutil.copy(gsap, proj / "assets/vendor/gsap.min.js")
    for f in (PKG / "assets" / "fonts").glob("*.ttf"):
        shutil.copy(f, proj / "assets/fonts" / f.name)
    for name in ("poses.png", "mouth_fechada.png", "mouth_meio.png", "mouth_aberta.png"):
        shutil.copy(PKG / "assets" / "bit" / name, proj / "assets/bit" / name)
    blink_sheet(PKG / "assets" / "bit" / "poses.png", proj / "assets/bit/poses_blink.png")
    html = (PKG / "hf" / "index.html").read_text(encoding="utf-8").replace("__DURATION__", f"{stage['duration']:.3f}")
    html = html.replace("/*__STAGE_JS__*/", (PKG / "hf" / "stage.js").read_text(encoding="utf-8"))  # inline: the timeline registry is read statically
    (proj / "index.html").write_text(html, encoding="utf-8")
    (proj / "assets" / "stage-data.js").write_text("window.STAGE = " + json.dumps(stage, separators=(",", ":")) + ";\n", encoding="utf-8")
    (proj / "hyperframes.json").write_text(json.dumps({"paths": {"blocks": "compositions", "components": "compositions/components", "assets": "assets"},
                                                       "media": {"autoProxy": True}}), encoding="utf-8")
    (proj / "meta.json").write_text(json.dumps({"id": "explainer", "name": "explainer"}), encoding="utf-8")


def plan_all(script, engine, work: Path, fps: int):
    cfg = D.settings(script.direction)
    leads = [D.lead_for(sc, LEAD, cfg) for sc in script.scenes]
    track, timeline = A.build_track(script, engine, work, leads)
    plan = ST.StagePlan(script, timeline, leads, LEAD)
    total_s = len(track) / A.SR + 0.3
    stage = Stage(timeline, leads, track, fps, plan)
    return track, timeline, leads, plan, stage, total_s


def render_hf(script, engine, out: Path, fps: int = 30, work: Path | None = None, preview: bool = False,
              snapshots: Path | None = None, keep_project: bool = True) -> dict:
    ffmpeg = check_ffmpeg()
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    work = work or out.parent / ".cache"
    work.mkdir(parents=True, exist_ok=True)

    track, timeline, leads, plan, stage, total_s = plan_all(script, engine, work, fps)
    n_frames = int(round(total_s * fps))
    data = ST.build_stage(plan, ST.bit_frames(stage, fps, n_frames), fps, total_s)
    rep = ST.report(plan)
    out.with_suffix(".stage.json").write_text(json.dumps({k: v for k, v in data.items() if k != "bit"}, indent=1), encoding="utf-8")
    Path(str(out.with_suffix("")) + ".stage.report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    out.with_suffix(".cues.json").write_text(json.dumps(plan.choreo.log, indent=1), encoding="utf-8")
    if plan.errors:
        raise ST.StageError("stage plan has errors (see stage.report.json):\n  " + "\n  ".join(plan.errors))
    wav = work / "narration.wav"
    write_wav(wav, track)
    write_srt(out.with_suffix(".srt"), timeline, leads)

    proj = out.parent / "hf"
    if proj.exists():
        shutil.rmtree(proj)
    write_project(proj, data)
    if preview:
        return {"duration_s": round(total_s, 2), "project": str(proj), "cues": len(rep["cues"])}

    silent = out.with_name(out.stem + ".video.mp4")
    env = {**os.environ, "HYPERFRAMES_NO_TELEMETRY": "1", "DO_NOT_TRACK": "1"}
    cmd = [*hyperframes_cmd(), "render", str(proj), "-o", str(silent.resolve()), "--fps", str(fps), "--quality", "high", "--quiet"]
    r = subprocess.run(cmd, env=env)
    if r.returncode != 0 or not silent.exists():
        raise RuntimeError("HyperFrames render failed (run `npx` check with: node node_modules/hyperframes/bin/hyperframes.mjs check out/hf)")
    mux = [ffmpeg, "-y", "-v", "error", "-i", str(silent), "-i", str(wav), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-af", f"{LOUDNESS},apad", "-t", f"{total_s:.2f}", str(out)]
    if subprocess.run(mux).returncode != 0:
        raise RuntimeError("ffmpeg mux failed")
    if snapshots:
        save_cue_frames(out, rep, Path(snapshots), fps, ffmpeg)
    silent.unlink(missing_ok=True)
    if not keep_project:
        shutil.rmtree(proj, ignore_errors=True)
    return {"duration_s": round(total_s, 2), "scenes": len(script.scenes), "cues": len(rep["cues"]), "out": str(out)}


def save_cue_frames(video: Path, rep: dict, folder: Path, fps: int, ffmpeg: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for i, row in enumerate(rep["cues"], 1):
        t = row.get("t_palavra_ms", row.get("t_inicio_ms", 0)) / 1000
        name = f"{i:02d}_{row['do']}.png"
        subprocess.run([ffmpeg, "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", str(folder / name)])
