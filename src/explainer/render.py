"""Render a Script to MP4 (Pillow frames piped into ffmpeg)."""
from __future__ import annotations

import json
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np
from PIL import Image

from . import audio as A
from . import direction as D
from .script import Script
from .slides import H, W, background, caption_chunks, draw_caption, draw_slide
from .sprites import Bit
from .timeline import Camera, FrameState, Stage

LEAD = 0.5
LOUDNESS = "loudnorm=I=-16:TP=-1.5:LRA=11"


def check_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg not found on PATH (install it first: https://ffmpeg.org/download.html)")
    return exe


def write_wav(path: Path, x: np.ndarray) -> None:
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(A.SR)
        w.writeframes(pcm.tobytes())


def write_srt(path: Path, timeline, leads) -> None:
    def ts(t):
        ms = int(round(t * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"

    n, rows = 0, []
    for (start, _total, a), lead in zip(timeline, leads):
        for s, e, lines in caption_chunks(a.sentences, lead):
            n += 1
            rows.append(f"{n}\n{ts(start + s)} --> {ts(start + e)}\n" + "\n".join(lines) + "\n")
    path.write_text("\n".join(rows), encoding="utf-8")


def apply_camera(im: Image.Image, cam: Camera) -> Image.Image:
    """Zoom/pan by cropping around (cx, cy); identity returns the image untouched."""
    if cam.identity:
        return im
    w, h = W / cam.zoom, H / cam.zoom
    x0 = min(max(cam.cx - w / 2, 0), W - w)
    y0 = min(max(cam.cy - h / 2, 0), H - h)
    return im.resize((W, H), Image.LANCZOS, box=(x0, y0, x0 + w, y0 + h))


def bit_image(bit: Bit, fs: FrameState) -> tuple[Image.Image, tuple[int, int]]:
    b = fs.bit
    ims = [(bit.frame(tag, k, b.mouth, b.blink, b.lift), w) for tag, k, w in b.layers]
    im = ims[0][0]
    if len(ims) > 1:
        im = Image.blend(ims[1][0], ims[0][0], ims[0][1])  # layers are ordered newest first
    return im, (int(round(b.x - im.width / 2)), int(round(b.y - im.height)))


def render(script: Script, engine, out: Path, fps: int = 30, work: Path | None = None, preview: bool = False,
           snapshots: Path | None = None) -> dict:
    ffmpeg = check_ffmpeg()
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    work = work or out.parent / ".cache"
    work.mkdir(parents=True, exist_ok=True)

    cfg = D.settings(script.direction)
    leads = [D.lead_for(sc, LEAD, cfg) for sc in script.scenes]
    track, timeline = A.build_track(script, engine, work, leads)
    choreo = D.plan(script, timeline, cfg, LEAD, leads)
    total_s = len(track) / A.SR + 0.3
    wav = work / "narration.wav"
    write_wav(wav, track)
    write_srt(out.with_suffix(".srt"), timeline, leads)
    out.with_suffix(".cues.json").write_text(json.dumps(choreo.log, indent=1), encoding="utf-8")

    cmd = [ffmpeg, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
           "-i", str(wav), "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-af", f"{LOUDNESS},apad", "-t", f"{total_s:.2f}", str(out)]
    proc = None if preview else subprocess.Popen(cmd, stdin=subprocess.PIPE)

    bg, bit = background(), Bit(8)
    stage = Stage(timeline, leads, track, fps, choreo)
    n_frames = int(round(total_s * fps))
    snap = {}
    if snapshots and not preview:
        Path(snapshots).mkdir(parents=True, exist_ok=True)
        for i, row in enumerate(choreo.log, 1):
            snap.setdefault(int(round(row["t_palavra_ms"] / 1000 * fps)), []).append(f"cue{i:02d}_{row['do']}")
    cache: dict = {}
    slides: dict = {}
    for q in range(n_frames):
        fs = stage.state(q)
        scene_idx, ts = fs.scene, fs.scene_t
        start, total, a = timeline[scene_idx]
        sc = script.scenes[scene_idx]
        items = sc.slide.get("items", [])
        shown = 0
        if items and ts >= fs.lead:
            shown = min(len(items), 1 + int((ts - fs.lead) / max(a.duration, 0.1) * len(items)))
        chunk = next((c for c in caption_chunks(a.sentences, fs.lead) if c[0] - 0.05 <= ts < c[1] + 0.1), None)
        lines = tuple(chunk[2]) if chunk else None
        b = fs.bit
        key = (scene_idx, shown, tuple((t, k, round(w, 2)) for t, k, w in b.layers), b.mouth, b.blink, b.lift,
               round(b.x), round(b.y), lines, round(fs.fade, 2), (fs.camera.zoom, fs.camera.cx, fs.camera.cy))
        if key not in cache:
            cache.clear() if len(cache) > 64 else None
            if (scene_idx, shown) not in slides:
                slides[(scene_idx, shown)] = draw_slide(sc.slide, shown, bg).convert("RGBA")
            im = slides[(scene_idx, shown)].copy()
            sprite, pos = bit_image(bit, fs)
            im.alpha_composite(sprite, pos) if pos[0] >= 0 else im.paste(sprite, pos, sprite)
            if lines:
                im.alpha_composite(draw_caption(list(lines)), (0, 880))
            fb = apply_camera(im.convert("RGB"), fs.camera)
            if fs.fade < 1:
                fb = Image.blend(Image.new("RGB", (W, H), (17, 17, 27)), fb, fs.fade)
            cache[key] = fb.tobytes()
        if preview:
            if q == int(start * fps + 1.6 * fps):
                Image.frombytes("RGB", (W, H), cache[key]).save(out.parent / f"preview_scene{scene_idx + 1}.png")
        else:
            proc.stdin.write(cache[key])
            for name in snap.get(q, []):
                Image.frombytes("RGB", (W, H), cache[key]).save(Path(snapshots) / f"{name}.png")
    if proc:
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg failed")
    return {"duration_s": round(total_s, 2), "scenes": len(script.scenes), "cues": len(choreo.log), "out": str(out)}
