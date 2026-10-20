"""Stitch a directory of rendered frame PNGs into an animated GIF.

Generic across any animation pattern: kinematic sweeps and build-up reveals both
land as a directory of ``frame_*.png`` files, which this script sorts, resizes to
a common width, and combines into one looping GIF.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from PIL import Image

_NUMERIC_SUFFIX = re.compile(r"(\d+)")


def _sort_key(path: Path) -> list:
    """Sort by the numeric run(s) in the filename, so frame_10 sorts after frame_9."""
    parts = _NUMERIC_SUFFIX.split(path.name)
    return [int(part) if part.isdigit() else part for part in parts]


def collect_frames(frames_dir: Path, glob: str) -> list[Path]:
    frames = sorted(frames_dir.glob(glob), key=_sort_key)
    if not frames:
        raise SystemExit(f"no PNGs matched {frames_dir / glob!s}")
    return frames


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Stitch rendered frame PNGs into an animated GIF."
    )
    parser.add_argument("frames_dir", type=Path, help="directory holding frame_*.png")
    parser.add_argument("output", type=Path, nargs="?", help="output GIF path")
    parser.add_argument("--glob", default="frame_*.png", help="frame PNG glob (default: frame_*.png)")
    parser.add_argument("--width", type=int, default=640, help="output width in px (default: 640)")
    parser.add_argument("--duration", type=int, default=90, help="per-frame ms (default: 90)")
    args = parser.parse_args(argv)

    frames_dir = args.frames_dir
    out_path = args.output or frames_dir.parent / "animation.gif"

    frames: list[Image.Image] = []
    for png in collect_frames(frames_dir, args.glob):
        img = Image.open(png).convert("RGB")
        if img.width != args.width:
            height = round(img.height * args.width / img.width)
            img = img.resize((args.width, height), Image.LANCZOS)
        frames.append(img)

    frames[0].save(
        out_path,
        save_all=True,
        append_images=frames[1:],
        duration=args.duration,
        loop=0,
        optimize=True,
    )
    print(f"wrote {out_path} ({len(frames)} frames, {frames[0].size[0]}x{frames[0].size[1]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
