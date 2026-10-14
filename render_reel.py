#!/usr/bin/env python3
"""Render a single-slide, text-only Instagram Reel (1080x1920, ~6.5s) with
background image + audio. Needs: Python 3, Pillow, ffmpeg on PATH."""
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).parent
BG = ROOT / "assets" / "background.png"
AUDIO = ROOT / "assets" / "audio.mp3"
FONT_BOLD = ROOT / "assets" / "fonts" / "Poppins-Bold.ttf"
FONT_MED = ROOT / "assets" / "fonts" / "Poppins-Medium.ttf"

W, H = 1080, 1920
DURATION = 6.5          # seconds (Instagram-friendly 6-7s)
FPS = 30
MARGIN_X = 90           # side padding
HEAD_CENTER_Y = 740
PAYOFF_Y = 1340

EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍←-⇿]+"
)


def split_text(raw: str):
    """'Headline...\n\nPayoff: line 👇' -> (headline, payoff)."""
    raw = raw.strip()
    parts = re.split(r"\n\s*\n\s*Payoff:\s*", raw, maxsplit=1, flags=re.I)
    head = parts[0].strip()
    payoff = parts[1].strip() if len(parts) > 1 else ""
    clean = lambda s: re.sub(r"\s+", " ", EMOJI_RE.sub("", s)).strip()
    return clean(head), clean(payoff)


def wrap(draw, text, font, max_w):
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def fit(draw, text, font_path, max_w, max_h, start, minimum, spacing=1.22):
    for size in range(start, minimum - 1, -2):
        font = ImageFont.truetype(str(font_path), size)
        lines = wrap(draw, text, font, max_w)
        if len(lines) * size * spacing <= max_h:
            return font, lines, size
    font = ImageFont.truetype(str(font_path), minimum)
    return font, wrap(draw, text, font, max_w), minimum


def draw_centered(layer, lines, font, size, center_y, fill, spacing=1.22, shadow=True):
    d = ImageDraw.Draw(layer)
    line_h = size * spacing
    y = center_y - (len(lines) * line_h) / 2
    for line in lines:
        w = d.textlength(line, font=font)
        x = (W - w) / 2
        if shadow:
            for off, a in ((6, 110), (3, 170)):
                d.text((x, y + off), line, font=font, fill=(0, 0, 0, a))
        d.text((x, y), line, font=font, fill=fill)
        y += line_h


def make_layers(headline, payoff, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    max_w = W - 2 * MARGIN_X
    probe = ImageDraw.Draw(Image.new("RGBA", (W, H)))

    # Headline layer (with a soft dark band behind it for legibility)
    head = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    font, lines, size = fit(probe, headline, FONT_BOLD, max_w, 600, 88, 44)
    block_h = len(lines) * size * 1.22
    band = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(band).rounded_rectangle(
        (40, HEAD_CENTER_Y - block_h / 2 - 70, W - 40, HEAD_CENTER_Y + block_h / 2 + 70),
        radius=48, fill=(15, 0, 0, 120),
    )
    head = Image.alpha_composite(head, band)
    draw_centered(head, lines, font, size, HEAD_CENTER_Y, (255, 255, 255, 255))
    head_path = out_dir / "headline.png"
    head.save(head_path)

    # Payoff layer (crimson pill)
    pay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if payoff:
        pfont, plines, psize = fit(probe, payoff, FONT_MED, max_w - 120, 260, 44, 32, 1.3)
        ph = len(plines) * psize * 1.3
        pw = max(probe.textlength(l, font=pfont) for l in plines)
        pill = ImageDraw.Draw(pay)
        pill.rounded_rectangle(
            ((W - pw) / 2 - 56, PAYOFF_Y - ph / 2 - 36, (W + pw) / 2 + 56, PAYOFF_Y + ph / 2 + 36),
            radius=60, fill=(150, 18, 32, 235),
        )
        draw_centered(pay, plines, pfont, psize, PAYOFF_Y, (255, 240, 235, 255),
                      spacing=1.3, shadow=False)
    pay_path = out_dir / "payoff.png"
    pay.save(pay_path)
    return head_path, pay_path


def render(text: str, out_path: Path, work_dir: Path = ROOT / "build"):
    headline, payoff = split_text(text)
    head_png, pay_png = make_layers(headline, payoff, work_dir)
    d = DURATION
    fc = (
        # slow vertical pan over the background, slightly darkened
        f"[0:v]scale=1200:2134:force_original_aspect_ratio=increase,"
        f"crop={W}:{H}:'(iw-ow)/2':'(ih-oh)*t/{d}',eq=brightness=-0.10:saturation=1.05,"
        f"format=rgba[bg];"
        f"[1:v]format=rgba,fade=t=in:st=0.35:d=0.8:alpha=1,"
        f"fade=t=out:st={d-0.45}:d=0.4:alpha=1[h];"
        f"[2:v]format=rgba,fade=t=in:st=2.4:d=0.7:alpha=1,"
        f"fade=t=out:st={d-0.45}:d=0.4:alpha=1[p];"
        f"[bg][h]overlay=0:0:format=auto[a];[a][p]overlay=0:0:format=auto,format=yuv420p[v];"
        f"[3:a]afade=t=out:st={d-1.2}:d=1.1,apad=whole_dur={d}[a]"
    )
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-loop", "1", "-framerate", str(FPS), "-t", str(d), "-i", str(BG),
        "-loop", "1", "-framerate", str(FPS), "-t", str(d), "-i", str(head_png),
        "-loop", "1", "-framerate", str(FPS), "-t", str(d), "-i", str(pay_png),
        "-i", str(AUDIO),
        "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
        "-t", str(d), "-r", str(FPS),
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-profile:v", "high",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        "-movflags", "+faststart", str(out_path),
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(cmd, check=True)
    return out_path


if __name__ == "__main__":
    txt = sys.argv[1] if len(sys.argv) > 1 else "Stop treating Halal intimacy like a chore.\n\nPayoff: Read the caption 👇"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "videos" / "test.mp4"
    print(render(txt, out))
