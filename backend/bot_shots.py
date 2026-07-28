#!/usr/bin/env python3
"""bot_shots.py <clip> [--bots "Left,Right"] [--frame N] — cut each bot out of the
footage into bots/<clip>-left.png and bots/<clip>-right.png.

    python backend/bot_shots.py madcatter-tombstone --bots "MaDCaTTer,Tombstone"

The HUD shows these beside each bot's name so a viewer can match the readout to
the machine in the arena. They are crops of OUR OWN clip rather than press
photos: no third-party image rights ride along into a public deploy, and the
picture is guaranteed to look like what is actually on screen.

The vision model only returns bounding boxes. Cropping, padding, scaling and
file naming are deterministic ffmpeg/Python, same split as the rest of the repo.

Downscaled to SHOT_W and rendered with image-rendering:pixelated in the page, so
a soft action still reads as deliberate pixel art rather than a blurry JPEG.
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze  # noqa: E402  (reuses the model clients and parse_json)

ROOT = Path(__file__).resolve().parent.parent
SHOT_W = 96                  # px wide before the page scales it — keeps it chunky
PAD = 0.06                   # fraction of the box added on each side


BOX_PROMPT = """You are looking at one frame of a robot combat match.

Find the TWO competing robots. Ignore everything else: the referee and crew,
people behind the arena glass, driver booths, arena hazards (killsaws, screws,
pulverisers) and any clean-up robot.

Return STRICT JSON only, no prose:
{"left": {"box": [x0, y0, x1, y1]}, "right": {"box": [x0, y0, x1, y1]}}

- Coordinates are fractions of the frame, 0.0-1.0, origin top-left.
- "left" is the robot further to the LEFT in THIS frame, "right" the other one.
- Box the robot body tightly, excluding its shadow.
- If you can only confidently find one robot, omit the other key entirely.
"""


def ask_boxes(src: Path, backend: str) -> dict:
    """One image in, two boxes out.

    Deliberately NOT analyze.ask_* — those append "return one entry per frame at
    exactly these timestamps", which fights the box schema and comes back {}.
    """
    import base64
    data = base64.b64encode(src.read_bytes()).decode()

    if backend == "openai":
        api = analyze.openai_client()
        msg = api.chat.completions.create(
            model=analyze.OPENAI_MODEL,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": BOX_PROMPT},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{data}"}}]}],
            response_format={"type": "json_object"})
        raw = msg.choices[0].message.content or "{}"
    else:
        api = analyze.client()
        msg = api.messages.create(
            model=analyze.MODEL, max_tokens=512,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                 "media_type": "image/jpeg", "data": data}},
                {"type": "text", "text": BOX_PROMPT}]}])
        raw = msg.content[0].text
    try:
        return analyze.parse_json(raw)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"  ! could not parse boxes: {e}", file=sys.stderr)
        return {}


def frame_size(path: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(path)],
        capture_output=True, text=True, check=True).stdout.strip()
    w, h = out.split("x")[:2]
    return int(w), int(h)


def crop(src: Path, dst: Path, box: list, size: tuple[int, int]) -> bool:
    """Crop `box` (normalised) out of `src` into `dst`. Returns False if the box
    is unusable — a model can hand back a degenerate or inverted rectangle."""
    w, h = size
    try:
        x0, y0, x1, y1 = (float(v) for v in box)
    except (TypeError, ValueError):
        return False
    x0, x1 = sorted((max(0.0, x0), min(1.0, x1)))
    y0, y1 = sorted((max(0.0, y0), min(1.0, y1)))
    x0, y0 = max(0.0, x0 - PAD), max(0.0, y0 - PAD)
    x1, y1 = min(1.0, x1 + PAD), min(1.0, y1 + PAD)
    cw, ch = int((x1 - x0) * w), int((y1 - y0) * h)
    if cw < 24 or ch < 24:                    # too small to be a robot
        return False

    # Square it around the box centre. A robot box is usually wide and flat, and
    # an unsquared crop becomes a letterboxed strip that reads as nothing at icon
    # size. Clamped so the square stays inside the frame.
    side_px = min(max(cw, ch), w, h)
    cx, cy = int((x0 + x1) / 2 * w), int((y0 + y1) / 2 * h)
    left = max(0, min(cx - side_px // 2, w - side_px))
    top = max(0, min(cy - side_px // 2, h - side_px))

    dst.parent.mkdir(exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
         "-vf", f"crop={side_px}:{side_px}:{left}:{top},"
                f"scale={SHOT_W}:{SHOT_W}:flags=lanczos",
         str(dst)], check=True)
    return True


def shots(clip: str, bots: dict | None = None, frame_no: int = 1,
          backend: str = "openai") -> None:
    name = Path(clip).stem
    frames = sorted((ROOT / "frames" / name).glob("*.jpg"))
    if not frames:
        sys.exit(f"no frames for {name} — run extract_frames.py first")
    src = frames[min(frame_no - 1, len(frames) - 1)]
    size = frame_size(src)
    print(f"boxing bots on {src.name} ({size[0]}x{size[1]})")

    out = ask_boxes(src, backend)

    made = []
    for side in ("left", "right"):
        box = (out.get(side) or {}).get("box")
        if not box:
            print(f"  ! no box for {side}", file=sys.stderr)
            continue
        dst = ROOT / "bots" / f"{name}-{side}.png"
        if crop(src, dst, box, size):
            made.append(dst)
            who = (bots or {}).get(side, side)
            print(f"  {side:>5} ({who}) -> {dst.relative_to(ROOT)}")
        else:
            print(f"  ! unusable box for {side}: {box}", file=sys.stderr)
    if not made:
        sys.exit("no shots produced — try a different --frame")


if __name__ == "__main__":
    argv = sys.argv[1:]
    if not argv:
        sys.exit(__doc__)

    def take(flag, default=None):
        if flag in argv:
            i = argv.index(flag)
            val = argv[i + 1] if i + 1 < len(argv) else default
            del argv[i:i + 2]
            return val
        return default

    backend = take("--backend", "openai")
    frame_no = int(take("--frame", "1"))
    pair = take("--bots")
    bots = None
    if pair:
        left, _, right = pair.partition(",")
        bots = {"left": left.strip(), "right": right.strip()}
    positional = [a for a in argv if not a.startswith("-")]
    if not positional:
        sys.exit(__doc__)
    shots(positional[0], bots=bots, frame_no=frame_no, backend=backend)
