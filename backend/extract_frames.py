#!/usr/bin/env python3
"""extract_frames.py <clip> — ffmpeg: 1 frame every 2s (0.5 fps), 768px wide.

    python backend/extract_frames.py fight1.mp4

Writes frames/<clipname>/0001.jpg ... Frame N is at t = (N-1) * 2.0 seconds.
Idempotent: does nothing if frames already exist (use --force to redo).
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FPS = 0.5          # one frame every 2 seconds
WIDTH = 768
SECONDS_PER_FRAME = 1.0 / FPS


def extract(clip: str, force: bool = False) -> Path:
    name = Path(clip).stem
    src = ROOT / "clips" / (clip if clip.endswith(".mp4") else clip + ".mp4")
    if not src.exists():
        sys.exit(f"no such clip: {src}")

    out = ROOT / "frames" / name
    existing = sorted(out.glob("*.jpg")) if out.exists() else []
    if existing and not force:
        print(f"{len(existing)} frames already in {out} (use --force to redo)")
        return out

    out.mkdir(parents=True, exist_ok=True)
    for f in existing:
        f.unlink()

    cmd = ["ffmpeg", "-y", "-i", str(src),
           "-vf", f"fps={FPS},scale={WIDTH}:-2",
           "-q:v", "4", str(out / "%04d.jpg")]
    subprocess.run(cmd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    n = len(list(out.glob("*.jpg")))
    print(f"extracted {n} frames -> {out}")
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        sys.exit(__doc__)
    extract(args[0], force="--force" in sys.argv)
