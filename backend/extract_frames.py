#!/usr/bin/env python3
"""extract_frames.py <clip> — ffmpeg: frames at FPS, 768px wide.

    python backend/extract_frames.py fight1.mp4
    python backend/extract_frames.py fight1.mp4 --fps 0.5   # the old sampling

Writes frames/<clipname>/0001.jpg ... Frame N is at t = (N-1) / fps seconds, and
the fps actually used is recorded in frames/<clipname>/meta.json so analyze.py
never has to assume it. A robot-combat impact lasts ~0.2s, so at the original
0.5 fps you only ever saw a before and an after, never the blow — which is how
two of the three demo timelines ended up with a winner who takes no damage at all.

Idempotent, but fps-aware: re-extracts when the requested fps differs from what
meta.json records, so bumping the rate can't silently reuse the old frames.
Use --force to redo at the same fps.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FPS = 2.0          # one frame every 0.5s
WIDTH = 768
META = "meta.json"


def meta_path(name: str) -> Path:
    return ROOT / "frames" / name / META


def read_meta(name: str) -> dict:
    """What was actually extracted, or {} for a frame dir from before the sidecar."""
    try:
        return json.loads(meta_path(name).read_text())
    except (OSError, ValueError):
        return {}


def seconds_per_frame(name: str) -> float:
    """The single source of truth for frame N -> timestamp, read back from disk.

    Falls back to the original 2.0s for a frame dir extracted before meta.json
    existed. Getting this wrong does not fail loudly — it scales every timestamp
    in the timeline by a constant, and the HUD drifts away from the video.
    """
    fps = read_meta(name).get("fps")
    if not fps:
        print(f"  ! no {META} in frames/{name} — assuming the old 0.5 fps",
              file=sys.stderr)
        return 2.0
    return 1.0 / float(fps)


def extract(clip: str, fps: float = FPS, force: bool = False) -> Path:
    name = Path(clip).stem
    src = ROOT / "clips" / (clip if clip.endswith(".mp4") else clip + ".mp4")
    if not src.exists():
        sys.exit(f"no such clip: {src}")

    out = ROOT / "frames" / name
    existing = sorted(out.glob("*.jpg")) if out.exists() else []
    stale = read_meta(name).get("fps") != fps      # a bare dir counts as stale
    if existing and not force and not stale:
        print(f"{len(existing)} frames already in {out} at {fps} fps "
              f"(use --force to redo)")
        return out
    if existing and stale:
        print(f"re-extracting {out}: was {read_meta(name).get('fps') or 'unknown'} fps, "
              f"want {fps}")

    out.mkdir(parents=True, exist_ok=True)
    for f in existing:
        f.unlink()

    cmd = ["ffmpeg", "-y", "-i", str(src),
           "-vf", f"fps={fps},scale={WIDTH}:-2",
           "-q:v", "4", str(out / "%04d.jpg")]
    subprocess.run(cmd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    n = len(list(out.glob("*.jpg")))
    # Written last, so a crashed ffmpeg leaves no meta and the next run redoes it.
    meta_path(name).write_text(json.dumps(
        {"fps": fps, "width": WIDTH, "count": n}, indent=2) + "\n")
    print(f"extracted {n} frames at {fps} fps -> {out}")
    return out


def parse_fps(argv: list[str], default: float = FPS) -> float:
    if "--fps" not in argv:
        return default
    i = argv.index("--fps")
    try:
        fps = float(argv[i + 1])
    except (IndexError, ValueError):
        sys.exit("--fps needs a number, e.g. --fps 2")
    if not 0 < fps <= 5:
        # Above ~5 fps the t={:.1f}s labels analyze.py round-trips through the
        # model stop being distinct, and frames silently collide on lookup.
        sys.exit("--fps must be between 0 and 5")
    return fps


if __name__ == "__main__":
    argv = sys.argv[1:]
    skip = {argv.index("--fps") + 1} if "--fps" in argv else set()
    args = [a for i, a in enumerate(argv) if not a.startswith("-") and i not in skip]
    if not args:
        sys.exit(__doc__)
    extract(args[0], fps=parse_fps(argv), force="--force" in argv)
