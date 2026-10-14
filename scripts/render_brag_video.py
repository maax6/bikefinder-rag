#!/usr/bin/env python3
"""Render a silent README demo from real, unaltered browser captures.

The manifest records the actual questions, answers and screenshot hashes. The
montage shortens waiting time and does not represent a latency benchmark.
Requires Pillow and FFmpeg; it never starts or queries the chatbot.
"""

import argparse
import json
from pathlib import Path
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
SIZE = (1920, 1080)
BACKGROUND = "#15211c"
ACCENT = "#e7b348"
INK = "#f6f8fa"
MUTED = "#c0cbc4"


def font(size, bold=False):
    paths = [
        Path("/System/Library/Fonts/Supplemental") / ("Arial Bold.ttf" if bold else "Arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu") / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
    ]
    for path in paths:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    raise RuntimeError("Install Arial or DejaVu Sans before rendering.")


def fit_text(draw, text, x, y, width, size, color=INK, bold=False):
    while draw.textlength(text, font=font(size, bold)) > width and size > 18:
        size -= 1
    draw.text((x, y), text, fill=color, font=font(size, bold))


def card(scene, index, total):
    frame = Image.new("RGB", SIZE, BACKGROUND)
    draw = ImageDraw.Draw(frame)
    draw.rounded_rectangle((72, 34, 238, 70), radius=18, fill=ACCENT)
    draw.text((89, 42), "BIKEFINDER", fill=BACKGROUND, font=font(20, True))
    draw.text((260, 43), "DÉMO DU CATALOGUE TECHNIQUE · OCTOBRE 2026", fill=MUTED, font=font(20))
    fit_text(draw, scene["title"], 72, 88, 1776, 42, bold=True)

    capture = Image.open(ROOT / scene["capture"]).convert("RGB")
    if scene.get("crop"):
        capture = capture.crop(tuple(scene["crop"]))
    contained = ImageOps.contain(capture, (1776, 758), Image.Resampling.LANCZOS)
    x = (SIZE[0] - contained.width) // 2
    y = 158 + (758 - contained.height) // 2
    draw.rounded_rectangle((65, 150, 1855, 926), radius=20, fill="#1d2d24", outline="#4c6052", width=2)
    frame.paste(contained, (x, y))

    draw = ImageDraw.Draw(frame)
    draw.text((72, 947), f"{index + 1:02d} / {total:02d}", fill=ACCENT, font=font(22, True))
    fit_text(draw, scene["caption"], 212, 944, 1630, 28, bold=True)
    draw.line((72, 999, 1848, 999), fill="#4c6052", width=2)
    draw.line((72, 999, 72 + round(1776 * (index + 1) / total), 999), fill=ACCENT, width=4)
    draw.text((72, 1020), "Réponses réelles · captures d’écran montées · attentes raccourcies · sans mesure de latence", fill=MUTED, font=font(18))
    draw.text((1712, 1020), "POC LOCAL", fill=ACCENT, font=font(18, True))
    return frame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--poster", type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    output = args.output or ROOT / manifest["video"]
    poster = args.poster or ROOT / manifest["poster"]
    output.parent.mkdir(parents=True, exist_ok=True)
    poster.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bikefinder-brag-") as temporary:
        work = Path(temporary)
        clips = []
        for index, scene in enumerate(manifest["scenes"]):
            image = card(scene, index, len(manifest["scenes"]))
            image_path = work / f"scene-{index:02d}.png"
            clip_path = work / f"scene-{index:02d}.mp4"
            image.save(image_path)
            if index == manifest.get("poster_scene", 1):
                image.save(poster, quality=92, optimize=True)
            duration = float(scene["seconds"])
            filters = (
                "zoompan=z='min(zoom+0.00002,1.004)':d=1:s=1920x1080:fps=24,"
                f"fade=t=in:st=0:d=0.22,fade=t=out:st={duration - 0.22}:d=0.22,"
                "format=yuv420p"
            )
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-loop", "1", "-framerate", "24", "-i", str(image_path),
                "-t", str(duration), "-vf", filters,
                "-c:v", "libx264", "-preset", "fast", "-crf", "21",
                "-an", str(clip_path),
            ], check=True)
            clips.append(clip_path)
        concat = work / "clips.txt"
        concat.write_text("".join(f"file '{clip}'\n" for clip in clips))
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat),
            "-c", "copy", "-movflags", "+faststart", str(output),
        ], check=True)
    print(json.dumps({"video": str(output), "poster": str(poster), "duration_seconds": sum(float(s["seconds"]) for s in manifest["scenes"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
