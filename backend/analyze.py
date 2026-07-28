#!/usr/bin/env python3
"""analyze.py <clip> — frames -> Claude vision -> timelines/<clip>.json

    python backend/analyze.py fight1.mp4

Sends frames in order, 2-3 per API call, with their timestamps and the running
hp state (the model is stateless between calls, so it must be told where the
fight stands). Everything else -- clamping, thinning, KO detection and the fan
comment join -- is deterministic Python, not model output.

Idempotent: same frames + same comments file produce the same timeline.
"""
import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MODEL = "claude-sonnet-5"
BATCH = 3                    # frames per API call
SECONDS_PER_FRAME = 2.0      # extract_frames.py runs at 0.5 fps
BIG_DROP = 15                # hp drop that earns a fan comment (and a screen shake)
MAX_CAPTION_WORDS = 6

STOPWORDS = {
    "the", "a", "an", "is", "it", "its", "to", "of", "and", "on", "in", "at",
    "for", "with", "that", "this", "was", "are", "be", "his", "her", "their",
    "bot", "again", "just", "now", "not", "no", "so", "but", "he", "she", "they",
}


# ---------------------------------------------------------------- model calls
def client():
    try:
        from anthropic import Anthropic
    except ImportError:
        sys.exit("pip install -r backend/requirements.txt")
    key = config.anthropic_key()
    if not key:
        sys.exit("no ANTHROPIC_API_KEY in .env or the environment "
                 "(or run with --backend cli to use your Claude subscription)")
    return Anthropic(api_key=key)


def parse_json(text: str) -> dict:
    """Strict-ish JSON out of a model reply (tolerates ``` fences)."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in reply")
    return json.loads(text[start:end + 1])


def ask(api, prompt: str, frames: list[tuple[float, Path]], state: dict) -> dict:
    content: list[dict] = []
    for t, path in frames:
        content.append({"type": "text", "text": f"Frame at t={t:.1f}s"})
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg",
                       "data": base64.b64encode(path.read_bytes()).decode()},
        })
    content.append({"type": "text", "text":
        f"Running state — left_hp {state['left']}, right_hp {state['right']}. "
        f"hp may only stay the same or decrease. "
        f"Return one entry per frame above, at exactly these timestamps: "
        f"{[round(t, 1) for t, _ in frames]}"})

    last_err = None
    for attempt in range(2):                       # one retry on bad JSON
        msg = api.messages.create(
            model=MODEL, max_tokens=1024, system=prompt,
            messages=[{"role": "user", "content": content}],
        )
        try:
            return parse_json(msg.content[0].text)
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e
            content = content + [{"type": "text", "text":
                "Your last reply was not valid JSON. Reply with the JSON object only."}]
    print(f"  ! giving up on this batch: {last_err}", file=sys.stderr)
    return {"frames": []}


def ask_cli(prompt: str, frames: list[tuple[float, Path]], state: dict) -> dict:
    """Same judging call, but through `claude -p` so it bills your Claude
    subscription instead of an API key. Claude Code reads the frames with its
    Read tool. Slower and far heavier per call than the API (every call re-sends
    Claude Code's own system prompt and tool definitions) -- fine for a demo run,
    wasteful for a long clip. See --backend in the docstring."""
    listing = "\n".join(f"- {p.resolve()}  (t={t:.1f}s)" for t, p in frames)
    ask_text = (
        f"{prompt}\n\n"
        f"Read these frame images in order:\n{listing}\n\n"
        f"Running state — left_hp {state['left']}, right_hp {state['right']}. "
        f"hp may only stay the same or decrease.\n"
        f"Return one entry per frame at exactly these timestamps: "
        f"{[round(t, 1) for t, _ in frames]}\n"
        f"Reply with the JSON object only."
    )
    cmd = ["claude", "-p", "--model", MODEL, "--output-format", "json",
           "--allowedTools", "Read", "--permission-mode", "dontAsk"]
    try:
        done = subprocess.run(cmd, input=ask_text, capture_output=True,
                              text=True, timeout=300)
    except FileNotFoundError:
        sys.exit("`claude` CLI not found on PATH — install Claude Code or drop --backend cli")
    except subprocess.TimeoutExpired:
        print("  ! claude -p timed out on this batch", file=sys.stderr)
        return {"frames": []}
    if done.returncode != 0:
        print(f"  ! claude -p failed: {done.stderr.strip()[:200]}", file=sys.stderr)
        return {"frames": []}
    try:
        # -p --output-format json wraps the reply; the reply itself may have prose
        # and ``` fences around the JSON, which parse_json() tolerates.
        return parse_json(json.loads(done.stdout)["result"])
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        print(f"  ! could not parse claude -p reply: {e}", file=sys.stderr)
        return {"frames": []}


# ------------------------------------------------------------ deterministic bits
def words(text: str) -> set[str]:
    return {w for w in re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split()
            if w and w not in STOPWORDS and len(w) > 2}


def trim_caption(text: str) -> str:
    return " ".join((text or "").split()[:MAX_CAPTION_WORDS])


def thin(observations: list[dict]) -> list[dict]:
    """~60 frame observations -> ~10 events: keep only visible change."""
    events, prev = [], None
    for o in observations:
        changed = prev is None or o["left_hp"] != prev["left_hp"] or o["right_hp"] != prev["right_hp"]
        if changed or o["caption"]:
            events.append(o)
            prev = o
    return events


def join_comments(events: list[dict], comments: list[dict]) -> None:
    """Attach fan comments to big drops by keyword overlap. Each comment used once."""
    used: set[int] = set()
    for i, ev in enumerate(events):
        if i == 0:
            continue
        drop = max(events[i - 1]["left_hp"] - ev["left_hp"],
                   events[i - 1]["right_hp"] - ev["right_hp"])
        if drop < BIG_DROP:
            continue
        cap = words(ev["caption"])
        best, best_score = None, 0
        for j, c in enumerate(comments):
            if j in used:
                continue
            score = len(cap & words(c.get("text", "")))
            if score > best_score:                 # ties keep the earlier comment
                best, best_score = j, score
        if best is not None and best_score >= 1:
            used.add(best)
            ev["fan_comment"] = comments[best]["text"]


def validate(timeline: dict) -> None:
    evs = timeline["events"]
    assert evs and evs[0]["t"] == 0.0, "missing baseline event"
    for i, e in enumerate(evs):
        assert 0 <= e["left_hp"] <= 100 and 0 <= e["right_hp"] <= 100, f"hp range at {e['t']}"
        assert len(e["caption"].split()) <= MAX_CAPTION_WORDS, f"caption too long at {e['t']}"
        if i:
            assert e["t"] >= evs[i - 1]["t"], "events out of order"
            assert e["left_hp"] <= evs[i - 1]["left_hp"], f"left hp increased at {e['t']}"
            assert e["right_hp"] <= evs[i - 1]["right_hp"], f"right hp increased at {e['t']}"


# ------------------------------------------------------------------------ main
def analyze(clip: str, backend: str = "api") -> Path:
    name = Path(clip).stem
    frame_dir = ROOT / "frames" / name
    paths = sorted(frame_dir.glob("*.jpg"))
    if not paths:
        sys.exit(f"no frames in {frame_dir} — run extract_frames.py first")

    prompt = (ROOT / "backend" / "prompt.txt").read_text()
    api = None if backend == "cli" else client()
    print(f"backend: {backend}" + (" (claude -p, uses your subscription)"
                                   if backend == "cli" else " (Anthropic API key)"))

    stamped = [((i) * SECONDS_PER_FRAME, p) for i, p in enumerate(paths)]
    state = {"left": 100, "right": 100}
    names = {"left": None, "right": None}
    observations: list[dict] = []

    for k in range(0, len(stamped), BATCH):
        batch = stamped[k:k + BATCH]
        print(f"judging t={batch[0][0]:.0f}s..{batch[-1][0]:.0f}s "
              f"({k // BATCH + 1}/{-(-len(stamped) // BATCH)})")
        out = (ask_cli(prompt, batch, state) if backend == "cli"
               else ask(api, prompt, batch, state))

        for side in ("left", "right"):
            got = (out.get("bots") or {}).get(side)
            if got and not names[side]:
                names[side] = str(got)[:24]

        by_t = {round(float(f.get("t", -1)), 1): f for f in out.get("frames", [])}
        for t, _ in batch:
            f = by_t.get(round(t, 1))
            if not f:
                continue
            left = min(state["left"], max(0, int(f.get("left_hp", state["left"]))))
            right = min(state["right"], max(0, int(f.get("right_hp", state["right"]))))
            state["left"], state["right"] = left, right
            observations.append({"t": round(t, 1), "left_hp": left, "right_hp": right,
                                 "caption": trim_caption(f.get("caption", ""))})

    events = thin(observations)
    if not events or events[0]["t"] != 0.0:
        events.insert(0, {"t": 0.0, "left_hp": 100, "right_hp": 100, "caption": ""})
    events[0]["caption"] = ""

    for i, ev in enumerate(events):                # KO = first time an hp hits 0
        if ev["left_hp"] == 0 or ev["right_hp"] == 0:
            ev["ko"] = "left" if ev["left_hp"] == 0 else "right"
            events = events[:i + 1]
            break

    comments_file = ROOT / "comments" / f"{name}.json"
    comments = json.loads(comments_file.read_text()) if comments_file.exists() else []
    if comments:
        join_comments(events, comments)
    else:
        print(f"(no {comments_file.name} — skipping fan comments)")

    timeline = {
        "clip": f"{name}.mp4",
        "bots": {"left": names["left"] or "Bot A", "right": names["right"] or "Bot B"},
        "events": events,
    }
    validate(timeline)

    out_path = ROOT / "timelines" / f"{name}.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(timeline, indent=2) + "\n")
    print(f"wrote {out_path} — {len(events)} events, "
          f"{timeline['bots']['left']} vs {timeline['bots']['right']}")
    return out_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    analyze(sys.argv[1])
