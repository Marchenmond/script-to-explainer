"""Slide and caption drawing (Pillow)."""
from __future__ import annotations

import textwrap
from importlib import resources
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
COLORS = dict(base="#1e1e2e", mantle="#181825", crust="#11111b", line="#45475a", text="#cdd6f4", sub="#a6adc8",
              accent="#cba6f7", warm="#fab387", gold="#f9e2af")
_fonts: dict = {}


def rgb(h: str):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def font(bold: bool, size: int):
    if (bold, size) not in _fonts:
        d = Path(str(resources.files("explainer") / "assets" / "fonts"))
        _fonts[(bold, size)] = ImageFont.truetype(str(d / ("JetBrainsMono-Bold.ttf" if bold else "JetBrainsMono-Regular.ttf")), size)
    return _fonts[(bold, size)]


def background() -> Image.Image:
    im = Image.new("RGB", (W, H), rgb(COLORS["base"]))
    d = ImageDraw.Draw(im)
    for x in range(0, W, 60):
        d.line([(x, 0), (x, H)], fill=(36, 36, 52), width=1)
    for y in range(0, H, 60):
        d.line([(0, y), (W, y)], fill=(36, 36, 52), width=1)
    d.rectangle([0, 0, W, 8], fill=rgb(COLORS["accent"]))
    d.rectangle([0, 880, W, H], fill=rgb(COLORS["mantle"]))
    d.line([(0, 880), (W, 880)], fill=rgb(COLORS["line"]), width=3)
    return im


def draw_slide(slide: dict, n_items: int, base: Image.Image) -> Image.Image:
    im = base.copy()
    d = ImageDraw.Draw(im)
    x0, y0, x1, y1 = 70, 90, 1050, 840
    d.rounded_rectangle([x0 + 8, y0 + 10, x1 + 8, y1 + 10], 28, fill=rgb(COLORS["crust"]))
    d.rounded_rectangle([x0, y0, x1, y1], 28, fill=rgb(COLORS["mantle"]), outline=rgb(COLORS["accent"]), width=4)
    if slide.get("kicker"):
        d.text((x0 + 60, y0 + 50), slide["kicker"].upper(), font=font(True, 30), fill=rgb(COLORS["warm"]))

    def block(txt, size, color, y, chars, bold=True):
        for line in txt.split("\n"):
            for sub in textwrap.wrap(line, chars) or [""]:
                d.text((x0 + 60, y), sub, font=font(bold, size), fill=rgb(COLORS[color]))
                y += int(size * 1.25)
        return y

    title = slide.get("title", "")
    kind = slide["type"]
    if kind == "title":
        y = block(title, 84, "text", y0 + 190, 19)
        if slide.get("subtitle"):
            block(slide["subtitle"], 38, "sub", y + 30, 38, False)
    elif kind == "bullets":
        y = block(title, 56, "text", y0 + 110, 28) + 40
        for item in slide.get("items", [])[:n_items]:
            d.ellipse([x0 + 60, y + 14, x0 + 84, y + 38], fill=rgb(COLORS["accent"]))
            yy = y
            for line in textwrap.wrap(item, 38):
                d.text((x0 + 110, yy), line, font=font(False, 38), fill=rgb(COLORS["text"]))
                yy += 50
            y = yy + 26
    elif kind == "highlight":
        y = block(title, 44, "sub", y0 + 130, 32) + 30
        block(slide.get("highlight", ""), 78, "gold", y, 16)
        if slide.get("subtitle"):
            block(slide["subtitle"], 34, "sub", y1 - 130, 40, False)
    return im


def draw_caption(lines: list[str]) -> Image.Image:
    im = Image.new("RGBA", (W, 200), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    f = font(True, 42)
    y = 100 - len(lines) * 30
    for line in lines:
        d.text((W // 2 + 2, y + 3), line, font=f, fill=(0, 0, 0, 255), anchor="ma")
        d.text((W // 2, y), line, font=f, fill=rgb(COLORS["text"]), anchor="ma")
        y += 60
    return im


def caption_chunks(sentences, lead: float, width: int = 46):
    """[(start, end, lines<=2)] in scene time; long sentences are split in time proportionally."""
    out = []
    for text, a, b in sentences:
        lines = textwrap.wrap(text.strip(), width)
        groups = [lines[i:i + 2] for i in range(0, len(lines), 2)]
        total = sum(len(" ".join(g)) for g in groups) or 1
        t = a + lead
        for g in groups:
            dd = (b - a) * len(" ".join(g)) / total
            out.append((t, t + dd, g))
            t += dd
    return out
