#!/usr/bin/env python3
"""probe_at.py <clip> --at 2.0 15.5 23.0 [--backend openai] [--repeat 2]

Ask the model where a blow landed, and print the answer next to the frame so it
can be checked by eye. This WRITES NOTHING — no timeline, no frames, no cache.

It exists because `hit.at` is the one field in the contract that cannot be checked
after the fact. A wrong `by` contradicts the hp deltas and a wrong `weapon` reads
oddly, but a wrong coordinate just puts the crosshair somewhere plausible-looking
and nobody notices. So the coordinate gets tested on frames whose answer is
already known, BEFORE a re-judge is paid for.

The negative control is the point of this script. Probe a frame with no impact in
it — on manta-skorpios t=23.0 is a driver booth with no robot on screen — and the
model must answer null. A model that invents a point there will put a crosshair on
a spectator, which is worse than the fixed 36%/64% position it would replace.

Deliberately NOT using prompt.txt or footer(): a probe that inherits the whole
judging prompt is testing the judging prompt, not the model's spatial grounding.
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyze  # noqa: E402
import extract_frames  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

ASK = ('Reply with JSON only: {"at": [x, y], "what": "<=6 words"}. '
       'x and y are the POINT OF IMPACT in this frame — where the two machines '
       'meet, the spray of sparks — as fractions of the frame width and height '
       'from the TOP-LEFT corner, 0 to 1, two decimals. Point at the contact '
       'itself, not at the middle of either robot. '
       'If this frame does not show a single point of impact between the two '
       'robots, reply {"at": null, "what": "..."} instead. Never guess a point.')


def frame_for(clip: str, t: float) -> tuple[Path, float]:
    """The frame at t, using the fps that was ACTUALLY extracted — never a
    constant here; extract_frames writes the rate it used to a sidecar."""
    spf = extract_frames.seconds_per_frame(clip)
    n = int(round(t / spf)) + 1                    # frame N (1-indexed) is at (N-1)*spf
    return ROOT / "frames" / clip / f"{n:04d}.jpg", round((n - 1) * spf, 1)


def dims(path: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(path)],
        capture_output=True, text=True)
    try:
        w, h = out.stdout.strip().split("x")[:2]
        return int(w), int(h)
    except ValueError:
        return 0, 0


def probe(api, path: Path) -> dict:
    import base64
    data = base64.b64encode(path.read_bytes()).decode()
    msg = api.chat.completions.create(
        model=analyze.OPENAI_MODEL,
        messages=[{"role": "user", "content": [
            {"type": "image_url",
             "image_url": {"url": f"data:image/jpeg;base64,{data}"}},
            {"type": "text", "text": ASK}]}],
        response_format={"type": "json_object"})
    return analyze.parse_json(msg.choices[0].message.content or "")


def main() -> None:
    argv = sys.argv[1:]
    if not argv:
        sys.exit(__doc__)
    clip = argv[0]
    times, repeat = [], 1
    if "--at" in argv:
        i = argv.index("--at")
        for a in argv[i + 1:]:
            if a.startswith("-"):
                break
            times.append(float(a))
    if "--repeat" in argv:
        i = argv.index("--repeat")
        repeat = int(argv[i + 1])
    if not times:
        sys.exit("give at least one --at SEC")

    api = analyze.openai_client()
    print(f"probing {clip} on {analyze.OPENAI_MODEL} — writes nothing\n")
    for t in times:
        path, real_t = frame_for(clip, t)
        if not path.exists():
            print(f"t={t:<6} MISSING {path}")
            continue
        w, h = dims(path)
        for r in range(repeat):
            try:
                got = probe(api, path)
            except Exception as e:
                print(f"t={t:<6} call failed: {str(e)[:160]}")
                continue
            at = analyze.clamp_at(got.get("at"))
            raw = got.get("at")
            px = f"px({at[0] * w:.0f},{at[1] * h:.0f})" if at else "—"
            note = "" if at or raw is None else f"  REJECTED raw={raw!r}"
            print(f"t={real_t:<6} {path.name} {w}x{h}  at={at}  {px:14} "
                  f"{str(got.get('what'))[:44]!r}{note}")
    print("\nCheck each against the frame. The no-impact frame MUST come back None:")
    print("a coordinate invented there would put a crosshair on a spectator.")


if __name__ == "__main__":
    main()
