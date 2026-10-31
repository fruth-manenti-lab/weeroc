"""Build a double-clickable macOS RADIOROC.app (with icon) that starts the desktop app.

usage: python tools/make_desktop_launcher.py [--dest ~/Desktop]

Run this from the conda environment or virtual environment where RADIOROC is
installed. The app only wraps `python -m radioroc.gui`; it contains no device
logic. Re-run it after moving the checkout or Python environment.
"""

from __future__ import annotations

import argparse
import io
import math
import plistlib
import shlex
import shutil
import struct
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SIZE = 1024


def _pulse(x: float) -> float:
    """Shaper-like pulse: fast rise, slower fall, small undershoot (0..1 in x)."""
    if x < 0.0:
        return 0.0
    rise = 1.0 - math.exp(-x * 18.0)
    fall = math.exp(-x * 5.5)
    under = -0.22 * math.exp(-((x - 0.55) ** 2) / 0.02)
    return rise * fall * 1.9 + under


def draw_icon() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    # Rounded dark-blue tile with a vertical gradient.
    tile = Image.new("RGBA", (SIZE, SIZE))
    px = ImageDraw.Draw(tile)
    for y in range(SIZE):
        t = y / SIZE
        px.line([(0, y), (SIZE, y)], fill=(int(14 + 18 * t), int(30 + 28 * t), int(66 + 40 * t), 255))
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle([40, 40, SIZE - 40, SIZE - 40], radius=210, fill=255)
    img.paste(tile, (0, 0), mask)
    d = ImageDraw.Draw(img)

    # Oscilloscope grid.
    gx0, gy0, gx1, gy1 = 130, 170, SIZE - 130, 640
    for i in range(9):
        x = gx0 + (gx1 - gx0) * i / 8
        d.line([(x, gy0), (x, gy1)], fill=(80, 120, 170, 70), width=3)
    for j in range(6):
        y = gy0 + (gy1 - gy0) * j / 5
        d.line([(gx0, y), (gx1, y)], fill=(80, 120, 170, 70), width=3)

    # Glowing detector pulse.
    base_y = gy1 - 110
    pts = []
    for k in range(401):
        x = k / 400.0
        pts.append((gx0 + 30 + x * (gx1 - gx0 - 60), base_y - _pulse((x - 0.18) * 1.55) * 330))
    glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(glow).line(pts, fill=(60, 255, 190, 255), width=34, joint="curve")
    glow = glow.filter(ImageFilter.GaussianBlur(22))
    img = Image.alpha_composite(img, glow)
    d = ImageDraw.Draw(img)
    d.line(pts, fill=(150, 255, 225, 255), width=16, joint="curve")

    # Scintillator plate with three SiPMs and an LED flash.
    px0, py0, px1, py1 = 190, 700, SIZE - 190, 820
    d.rounded_rectangle([px0, py0, px1, py1], radius=26, fill=(120, 190, 255, 255),
                        outline=(220, 240, 255, 255), width=6)
    for cx in (px0 + 130, (px0 + px1) // 2, px1 - 130):
        d.rounded_rectangle([cx - 38, py0 - 34, cx + 38, py0 + 8], radius=8, fill=(250, 200, 70, 255))
        d.line([(cx, py0 - 34), (cx, py0 - 70)], fill=(250, 200, 70, 255), width=8)
    fx = (px0 + px1) // 2
    flash = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(flash).ellipse([fx - 70, py1 - 50, fx + 70, py1 + 90], fill=(255, 255, 255, 255))
    flash = flash.filter(ImageFilter.GaussianBlur(26))
    img = Image.alpha_composite(img, flash)
    d = ImageDraw.Draw(img)
    d.ellipse([fx - 22, py1 - 8, fx + 22, py1 + 36], fill=(255, 255, 255, 255))

    # Name.
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 92, index=1)
    except OSError:  # pragma: no cover - non-macOS fallback
        font = ImageFont.load_default()
    text = "RADIOROC"
    w = d.textlength(text, font=font)
    d.text(((SIZE - w) / 2, 860), text, font=font, fill=(235, 245, 255, 255))
    return img


def build_icns(img: Image.Image, target: Path) -> None:
    """Write a modern ICNS container whose image entries are PNG encoded."""
    entries = bytearray()
    for icon_type, size in (
        (b"icp4", 16), (b"icp5", 32), (b"icp6", 64),
        (b"ic07", 128), (b"ic08", 256), (b"ic09", 512), (b"ic10", 1024),
    ):
        stream = io.BytesIO()
        img.resize((size, size), Image.LANCZOS).save(stream, format="PNG")
        data = stream.getvalue()
        entries.extend(icon_type + struct.pack(">I", len(data) + 8) + data)
    target.write_bytes(b"icns" + struct.pack(">I", len(entries) + 8) + entries)


LAUNCHER = """#!/bin/bash
# Starts the RADIOROC desktop from the checkout; logs to ~/Library/Logs/RADIOROC.log
ROOT={root}
LOG="$HOME/Library/Logs/RADIOROC.log"
PY={python}
if [ ! -x "$PY" ]; then
  osascript -e 'display alert "RADIOROC" message "Python environment not found:\\n'"$PY"'\\nRecreate the environment, then run tools/make_desktop_launcher.py again."'
  exit 1
fi
cd "$ROOT" || exit 1
export PYTHONPATH="$ROOT/src${{PYTHONPATH:+:$PYTHONPATH}}"
exec "$PY" -m radioroc.gui >> "$LOG" 2>&1
"""


def build_app(dest: Path, python: Path | None = None) -> Path:
    python = python or Path(sys.executable).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    app = dest / "RADIOROC.app"
    if app.exists():
        shutil.rmtree(app)
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "Resources").mkdir()
    script = app / "Contents" / "MacOS" / "RADIOROC"
    script.write_text(LAUNCHER.format(
        root=shlex.quote(str(ROOT)), python=shlex.quote(str(python)),
    ))
    script.chmod(0o755)
    build_icns(draw_icon(), app / "Contents" / "Resources" / "AppIcon.icns")
    with (app / "Contents" / "Info.plist").open("wb") as stream:
        plistlib.dump({
            "CFBundleName": "RADIOROC", "CFBundleDisplayName": "RADIOROC",
            "CFBundleIdentifier": "au.edu.sydney.radioroc.desktop",
            "CFBundleExecutable": "RADIOROC", "CFBundleIconFile": "AppIcon",
            "CFBundlePackageType": "APPL", "CFBundleShortVersionString": "0.5",
            "LSMinimumSystemVersion": "11.0", "NSHighResolutionCapable": True,
        }, stream)
    subprocess.run(["touch", str(app)], check=False)
    return app


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", type=Path, default=Path.home() / "Desktop")
    parser.add_argument("--preview", type=Path, help="also write the 1024 px icon PNG here")
    args = parser.parse_args()
    if args.preview:
        draw_icon().save(args.preview)
    print(build_app(args.dest.expanduser()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
