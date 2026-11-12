"""Render a Script to MP4 (Pillow frames piped into ffmpeg)."""
from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np
from PIL import Image

from . import audio as A
from .script import Script
from .slides import H, W, background, caption_chunks, draw_caption, draw_slide
from .sprites import EMOTION_TAG, TALK_TAG, Bit

LEAD = 0.5


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


def write_srt(path: Path, timeline) -> None:
    def ts(t):
        ms = int(round(t * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"

    n, rows = 0, []
    for start, _total, a in timeline:
        for s, e, lines in caption_chunks(a.sentences, LEAD):
            n += 1
            rows.append(f"{n}\n{ts(start + s)} --> {ts(start + e)}\n" + "\n".join(lines) + "\n")
    path.write_text("\n".join(rows), encoding="utf-8")


def render(script: Script, engine, out: Path, fps: int = 30, work: Path | None = None, preview: bool = False) -> dict:
    ffmpeg = check_ffmpeg()
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    work = work or out.parent / ".cache"
    work.mkdir(parents=True, exist_ok=True)

    track, timeline = A.build_track(script, engine, work, LEAD)
    total_s = len(track) / A.SR + 0.3
    wav = work / "narration.wav"
    write_wav(wav, track)
    write_srt(out.with_suffix(".srt"), timeline)

    cmd = [ffmpeg, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
           "-i", str(wav), "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-af", "apad", "-t", f"{total_s:.2f}", str(out)]
    proc = None if preview else subprocess.Popen(cmd, stdin=subprocess.PIPE)

    bg, bit = background(), Bit(8)
    env = A.speech_envelope(track, fps)
    n_frames = int(round(total_s * fps))
    scene_idx = 0
    cache: dict = {}
    slides: dict = {}
    for q in range(n_frames):
        t = q / fps
        while scene_idx < len(timeline) - 1 and t >= timeline[scene_idx][0] + timeline[scene_idx][1]:
            scene_idx += 1
        start, total, a = timeline[scene_idx]
        sc = script.scenes[scene_idx]
        ts = t - start
        items = sc.slide.get("items", [])
        shown = 0
        if items and ts >= LEAD:
            shown = min(len(items), 1 + int((ts - LEAD) / max(a.duration, 0.1) * len(items)))
        talking = q < len(env) and bool(env[q])
        tag = TALK_TAG if talking else EMOTION_TAG[sc.emotion]
        sprite = bit.frame(tag, int(t * 1000))
        chunk = next((c for c in caption_chunks(a.sentences, LEAD) if c[0] - 0.05 <= ts < c[1] + 0.1), None)
        lines = tuple(chunk[2]) if chunk else None
        fade = max(0.0, min(1.0, ts / 0.25, (total - ts) / 0.25))
        key = (scene_idx, shown, id(sprite), lines, round(fade, 2))
        if key not in cache:
            cache.clear() if len(cache) > 64 else None
            if (scene_idx, shown) not in slides:
                slides[(scene_idx, shown)] = draw_slide(sc.slide, shown, bg).convert("RGBA")
            im = slides[(scene_idx, shown)].copy()
            im.alpha_composite(sprite, (1090 + (810 - sprite.width) // 2, 850 - sprite.height))
            if lines:
                im.alpha_composite(draw_caption(list(lines)), (0, 880))
            fb = im.convert("RGB")
            if fade < 1:
                fb = Image.blend(Image.new("RGB", (W, H), (17, 17, 27)), fb, fade)
            cache[key] = fb.tobytes()
        if preview:
            if q == int(start * fps + 1.6 * fps):
                Image.frombytes("RGB", (W, H), cache[key]).save(out.parent / f"preview_scene{scene_idx + 1}.png")
        else:
            proc.stdin.write(cache[key])
    if proc:
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg failed")
    return {"duration_s": round(total_s, 2), "scenes": len(script.scenes), "out": str(out)}
