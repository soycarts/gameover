#!/usr/bin/env python3
"""analyze.py <clip> — frames -> Claude vision -> timelines/<clip>.json

    python backend/analyze.py fight1.mp4                    # Anthropic API key
    python backend/analyze.py fight1.mp4 --backend cli      # your Claude subscription
    python backend/analyze.py fight1.mp4 --backend openai   # OPENAI_API_KEY
    python backend/analyze.py fight1.mp4 --bots "Tombstone,Witch Doctor" --ko right

--bots pins the card instead of trusting the model's reading of the broadcast
graphics, same flag ingest.py takes. Worth using on a re-judge: name detection
depends on whether a lower-third happens to be legible in the sampled frames, so
a clip that resolved to "Manta" once can come back as "Bot A" the next time.
--ko pins the losing side for a clip someone has actually watched; the finish
frame is often a crowd shot the model has to guess from.

--backend openai swaps the vision judge to an OpenAI model (OPENAI_MODEL, default
gpt-5.5). Only the model call changes: the prompt, the hp clamp, thinning, KO
detection and the comment join are identical, so the JSON contract is unaffected.

--backend cli shells out to `claude -p` instead of the SDK, so judging runs on your
Claude Code subscription and needs no ANTHROPIC_API_KEY. It is slower and much
heavier per call (Claude Code re-sends its own system prompt and tool definitions
every time) and it consumes the same quota you need for coding. Fine for a demo
clip; use the API backend for anything long.

Sends frames in order, 2-3 per API call, each batch led by the previous batch's
last frame as unjudged context, plus a note of the last damage already reported
(the model is stateless between calls, so without it the same fire gets reported
as fresh damage on every frame). The model never emits hp: it rates each frame
with a damage word per bot, and SEVERITY turns that into points. Everything else
-- the budget, thinning, KO detection and the fan comment join -- is
deterministic Python, not model output.

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
# --backend openai only. Override with OPENAI_MODEL; this account has no gpt-4o,
# so the default is the general GPT-5 model rather than a codex variant.
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.5")
BATCH = 3                    # frames judged per API call
SECONDS_PER_FRAME = 2.0      # extract_frames.py runs at 0.5 fps
BIG_DROP = 20                # heavy+ — the floor for a last-resort fan comment
COMMENT_DROP = 10            # solid+ — a hit worth reacting to, if a comment matches
MAX_CAPTION_WORDS = 6
MAX_WEAPON_WORDS = 3
SIDES = ("left", "right")

# The model judges severity; Python owns every number. Asking it for absolute hp
# instead made it nudge the bar down 3-5 points per frame to signal "time passed",
# which the HUD renders as mush. Nothing exists here between 0 and 4, so that drip
# is not representable. The rungs are spaced against the HUD's 5 cores x 20 hp, so
# a mis-graded hit is wrong by a category rather than by an unreadable 3 points.
SEVERITY = {"none": 0, "glance": 4, "solid": 12, "heavy": 22, "catastrophic": 35}
KO_BUDGET = 70               # damage a bot may take BEFORE the finishing blow
LIVE_BUDGET = 55             # ... for a bot still fighting at the end
FINISH_WINDOW = 0.7          # a finish flag in the first 70% of a clip is a misread

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


def openai_client():
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("pip install -r backend/requirements.txt")
    key = config.openai_key()
    if not key:
        sys.exit("no OPENAI_API_KEY in .env or the environment")
    return OpenAI(api_key=key)


def identity_note(state: dict, names: dict | None = None) -> str:
    """Re-state who is who. Repeated on every call because the model has no memory
    between batches and the bots swap screen sides constantly.

    Naming the two competitors explicitly matters: left to itself the model reads
    sponsor livery off the machines and captions them as bots ("Rapid Taxis
    catches fire", which is a taxi firm's decal, not a competitor).
    """
    names = names or {}
    head = ""
    if names.get("left") and names.get("right"):
        head = (f"The ONLY two competitors are {names['left']} (left) and "
                f"{names['right']} (right). Use no other name in a caption — text on "
                f"the robots is sponsor livery, not a bot.\n")
    bits = []
    for side in ("left", "right"):
        look = state.get(f"{side}_look")
        if look:
            bits.append(f"{side} = {look}")
    if not bits:
        return head + ("Identify each bot by appearance, not screen position, and say "
                       "so in left_look / right_look.\n")
    return head + ("Identities (fixed for the whole fight, they DO change screen sides): "
                   + "; ".join(bits) + ". Re-identify by appearance in every frame.\n")


def parse_json(text: str) -> dict:
    """Strict-ish JSON out of a model reply (tolerates ``` fences)."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in reply")
    return json.loads(text[start:end + 1])


def context_note(t: float) -> str:
    """Label for the carried-over frame that leads every batch after the first.

    A batch is asked for damage "new since the previous frame", so its leading
    frame is unanswerable without a predecessor — batches used to be disjoint and
    every 3rd frame had nothing to diff against."""
    return (f"Frame at t={t:.1f}s — CONTEXT ONLY, already judged. Use it as the "
            f"'previous frame' for the first frame below. Do not return an entry for it.")


def footer(frames: list[tuple[float, Path]], recent: list[str],
           card: dict | None = None, state: dict | None = None) -> str:
    """Shared tail of every judging call. The model is stateless between calls, so
    everything it needs to stay consistent has to be re-sent every time:

    - who the two bots are and what they look like (identity_note) — the camera
      pans and cuts, so "the bot on the left of the screen" is not the same bot
      frame to frame. On madcatter-tombstone that ambiguity flipped which side got
      the KO between two runs of the same clip;
    - what it already reported, or it re-reports standing damage (a fire still
      burning, a panel already gone) as fresh damage on every frame;
    - the "hit" rule, which it otherwise honours for a batch or two and then
      quietly forgets for the rest of a long clip.

    There is deliberately no running-hp line: under the severity ladder the model
    never emits hp at all, so there is no hp state to carry.
    """
    return (identity_note(state or {}, card)
            + f"Already reported: {'; '.join(recent) or 'nothing yet'}\n"
            + 'For every frame where a bot takes damage (any word other than '
              '"none"), include "hit" ({"by": "left"|"right", "weapon": ..., '
              '"clean": true|false}) naming the bot that LANDED the blow. '
              'Omit "hit" when both bots are "none".\n'
            + f"Return one entry per frame above, at exactly these timestamps: "
              f"{[round(t, 1) for t, _ in frames]}")


def ask(api, prompt: str, frames: list[tuple[float, Path]],
        ctx: tuple[float, Path] | None, recent: list[str],
        card: dict | None = None, state: dict | None = None) -> dict:
    def image(path: Path) -> dict:
        return {"type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg",
                           "data": base64.b64encode(path.read_bytes()).decode()}}

    content: list[dict] = []
    if ctx:
        content.append({"type": "text", "text": context_note(ctx[0])})
        content.append(image(ctx[1]))
    for t, path in frames:
        content.append({"type": "text", "text": f"Frame at t={t:.1f}s"})
        content.append(image(path))
    content.append({"type": "text", "text": footer(frames, recent, card, state)})

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


def ask_openai(api, prompt: str, frames: list[tuple[float, Path]],
               ctx: tuple[float, Path] | None, recent: list[str],
               card: dict | None = None, state: dict | None = None) -> dict:
    """Same judging call against an OpenAI vision model. See --backend openai."""
    def image(path: Path) -> dict:
        data = base64.b64encode(path.read_bytes()).decode()
        return {"type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{data}"}}

    content: list[dict] = []
    if ctx:
        content.append({"type": "text", "text": context_note(ctx[0])})
        content.append(image(ctx[1]))
    for t, path in frames:
        content.append({"type": "text", "text": f"Frame at t={t:.1f}s"})
        content.append(image(path))
    content.append({"type": "text", "text": footer(frames, recent, card, state)})

    messages = [{"role": "system", "content": prompt},
                {"role": "user", "content": content}]
    last_err = None
    for attempt in range(2):                       # one retry on bad JSON
        try:
            msg = api.chat.completions.create(
                model=OPENAI_MODEL, messages=messages,
                response_format={"type": "json_object"})
        except Exception as e:                     # rate limit, refusal, transport
            print(f"  ! openai call failed: {str(e)[:200]}", file=sys.stderr)
            return {"frames": []}
        try:
            return parse_json(msg.choices[0].message.content or "")
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e
            messages = messages + [{"role": "user", "content":
                "Your last reply was not valid JSON. Reply with the JSON object only."}]
    print(f"  ! giving up on this batch: {last_err}", file=sys.stderr)
    return {"frames": []}


def ask_cli(prompt: str, frames: list[tuple[float, Path]],
            ctx: tuple[float, Path] | None, recent: list[str],
            card: dict | None = None, state: dict | None = None) -> dict:
    """Same judging call, but through `claude -p` so it bills your Claude
    subscription instead of an API key. Claude Code reads the frames with its
    Read tool. Slower and far heavier per call than the API (every call re-sends
    Claude Code's own system prompt and tool definitions) -- fine for a demo run,
    wasteful for a long clip. See --backend in the docstring."""
    lines = []
    if ctx:
        lines.append(f"- {ctx[1].resolve()}  ({context_note(ctx[0])})")
    lines += [f"- {p.resolve()}  (t={t:.1f}s)" for t, p in frames]
    ask_text = (
        f"{prompt}\n\n"
        f"Read these frame images in order:\n" + "\n".join(lines) + "\n\n"
        f"{footer(frames, recent, card, state)}\n"
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


def name_captions(events: list[dict], card: dict) -> None:
    """Rewrite "left"/"right" in captions into the actual bot names.

    The model is reliable about WHICH side took damage (every caption agrees with
    the hp that dropped) but writes "right rear on fire", which tells a viewer
    nothing. Substituting here rather than trusting the prompt means existing
    timelines get fixed without paying for a re-judge, and a model that ignores
    the naming instruction still produces a named caption.
    """
    for side, other in (("left", "right"), ("right", "left")):
        name = (card.get(side) or "").strip()
        if not name or name.lower() in (f"bot a", "bot b", side, other):
            continue
        for ev in events:
            cap = ev.get("caption") or ""
            if not cap:
                continue
            # "left bot" / "the left bot" collapse to just the name
            cap = re.sub(rf"\b(?:the\s+)?{side}\s+bot\b", name, cap, flags=re.I)
            cap = re.sub(rf"\b(?:the\s+)?{side}\b", name, cap, flags=re.I)
            ev["caption"] = trim_caption(cap[0].upper() + cap[1:] if cap else cap)


def trim_caption(text: str) -> str:
    return " ".join((text or "").split()[:MAX_CAPTION_WORDS])


def pay(obs: list[dict], side: str, budget: int) -> None:
    """Spend a fixed damage budget on the worst moments first; zero the rest.

    A busy fight overshoots badly — the model will happily call 30 hits, and 30
    hits at 12 points each is 360 damage against a 100 point bar. Scaling every
    hit down to fit would just re-create the 3-5 point drip this replaces, and a
    plain floor would flatline the bar halfway through the fight. Paying the big
    hits first keeps them full size and drops the surplus scuffing. Ties go to the
    earlier frame, so the result is stable and idempotent.

    The budget is under 100 on purpose: a bot bottoms out with hp to spare, and
    the only route to 0 is the model's finish flag."""
    spent = 0
    for i in sorted(range(len(obs)), key=lambda i: (-obs[i]["cost"][side], i)):
        c = obs[i]["cost"][side]
        if c and spent + c <= budget:
            spent += c
        else:
            obs[i]["cost"][side] = 0


def finish_at(obs: list[dict]) -> tuple[int | None, str | None]:
    """First frame flagged as the finish, ignoring flags in the first 70% of the
    clip. Events are cut at the KO, so a model that calls a knockout at t=10 of a
    144s fight would throw the whole fight away. ingest.py cuts each clip to the
    fight, so the real finish is always near the end: 140/144, 74/78, 28/32 on the
    three demo clips."""
    cut = int(len(obs) * FINISH_WINDOW)
    for i, o in enumerate(obs):
        if o["finish"] and i >= cut:
            return i, o["finish"]
    return None, None


def thin(observations: list[dict]) -> list[dict]:
    """~60 frame observations -> ~10 events: keep only visible change.

    A caption with no hp change is still kept — pay() zeroes surplus hits, and the
    caption beat gives the HUD something to type across a long fight. But a caption
    that just repeats the one before it is dropped: the model narrates a fire for
    ten frames running, and the HUD should not type "right side on fire" ten times.

    Observations are kept by reference, so a "hit" rides along untouched. That is
    safe because normalize_hit() only attaches one where hp actually dropped, so a
    caption-only observation can never carry one.
    """
    events, prev = [], None
    for o in observations:
        changed = prev is None or o["left_hp"] != prev["left_hp"] or o["right_hp"] != prev["right_hp"]
        if changed or (o["caption"] and o["caption"] != prev["caption"]):
            events.append(o)
            prev = o
    return events


def normalize_hit(raw, prev: dict, cur: dict) -> dict | None:
    """Model hit -> contract hit, or None. Deterministic, like the hp clamp.

    Runs AFTER the clamp so it judges the damage the timeline will actually show:
    hp deltas are the only evidence a blow landed, and a hit with none behind it is
    dropped. The frontend derives damage, victim and tier from those same deltas —
    what survives here is only what the model could see and code cannot infer.
    """
    if not isinstance(raw, dict):
        return None
    dropped = [s for s in SIDES if prev[s] > cur[s]]
    if not dropped:
        return None                                   # no damage -> not a hit
    by = str(raw.get("by", "")).strip().lower()
    if by not in SIDES:
        return None                                   # unattributed; frontend defaults
    clean = raw.get("clean", True) is not False
    if clean and by in dropped and len(dropped) == 1:
        by = "right" if by == "left" else "left"      # model named the victim; flip
    weapon = raw.get("weapon")
    weapon = " ".join(str(weapon).split()[:MAX_WEAPON_WORDS]).lower()[:24] if weapon else ""
    return {"by": by, "weapon": weapon or None, "clean": clean}


# Scraped threads are about the whole season, so a MaD CaTTer search surfaces the
# SawBlaze fight too. Captioning a Tombstone hit with a SawBlaze comment is the
# kind of thing a BattleBots viewer spots immediately, so a comment naming a bot
# that is not in THIS fight is used only as a last resort.
KNOWN_BOTS = {
    "tombstone", "witch doctor", "sawblaze", "madcatter", "mad catter", "manta",
    "skorpios", "jackpot", "copperhead", "hydra", "riptide", "end game",
    "whiplash", "bite force", "minotaur", "hypershock", "black dragon", "glitch",
    "banshee", "huge", "shatter", "lucky", "uppercut", "gigabyte", "valkyrie",
    "ripperoni", "malice", "yeti", "bronco", "icewave", "beta", "captain shrederator",
}


def names_a_rival(text: str, card: dict) -> bool:
    """True if the comment names a known bot that is not in this fight.

    Word-boundary matched, so "Manta," and "Mad Catter's" are caught — an
    endswith/space check misses trailing punctuation, which is exactly how a
    Manta comment first slipped onto a Copperhead hit.
    """
    low = " ".join(text.lower().split())
    ours = {n.lower() for n in (card.get("left", ""), card.get("right", "")) if n}
    for bot in KNOWN_BOTS:
        # "madcatter" and "mad catter" both count as ours if either name contains it
        if any(bot in o or o in bot for o in ours):
            continue
        # trailing s / possessive: "Mad Catters design", "Tombstone's blade"
        if re.search(rf"\b{re.escape(bot)}(?:'s|’s|s)?\b", low):
            return True
    return False


def join_comments(events: list[dict], comments: list[dict],
                  bots: dict | None = None) -> None:
    """Attach fan comments to damage moments. Each comment is used at most once.

    Ranked, best first:
      1. caption word overlap  — the comment is about this exact moment
      2. the damaged bot's name appears in the comment
      3. anything unused       — only on a genuinely big hit

    Rule 3 exists because real scraped chatter is mostly post titles, which
    rarely share a content word with a 6-word caption; matching alone left
    whole fights with zero comments on screen. A generic crowd reaction under
    a big hit still reads right, an empty HUD does not.
    """
    used: set[int] = set()
    bots = bots or {}
    for i, ev in enumerate(events):
        if i == 0:
            continue
        left_drop = events[i - 1]["left_hp"] - ev["left_hp"]
        right_drop = events[i - 1]["right_hp"] - ev["right_hp"]
        drop = max(left_drop, right_drop)
        if drop < COMMENT_DROP:
            continue
        hurt = bots.get("left" if left_drop >= right_drop else "right", "")
        cap, name = words(ev["caption"]), words(hurt)

        best, best_score = None, 0
        for j, c in enumerate(comments):
            if j in used or names_a_rival(c.get("text", ""), bots):
                continue
            ctext = words(c.get("text", ""))
            score = 2 * len(cap & ctext) + (2 if name and name <= ctext else 0)
            if score > best_score:                 # ties keep the earlier comment
                best, best_score = j, score
        if best is None and drop >= BIG_DROP:      # fall back to any clean unused one
            best = next((j for j, c in enumerate(comments)
                         if j not in used and not names_a_rival(c.get("text", ""), bots)),
                        None)
        if best is not None:
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
        # normalize_hit() clamps model noise; these catch bugs in our own code.
        h = e.get("hit")
        if h is not None:
            assert isinstance(h, dict) and set(h) == {"by", "weapon", "clean"}, \
                f"bad hit shape at {e['t']}"
            assert h["by"] in SIDES, f"bad hit.by at {e['t']}"
            assert isinstance(h["clean"], bool), f"bad hit.clean at {e['t']}"
            w = h["weapon"]
            assert w is None or (isinstance(w, str) and 0 < len(w) <= 24
                                 and len(w.split()) <= MAX_WEAPON_WORDS), \
                f"bad hit.weapon at {e['t']}"
            assert i, "hit on the baseline event"
            hurt = [s for s in SIDES if evs[i - 1][f"{s}_hp"] > e[f"{s}_hp"]]
            assert hurt, f"hit with no damage at {e['t']}"
            # an incidental blow has to name a bot that actually lost hp, or the
            # frontend can never match it to a damaged side
            assert h["clean"] or h["by"] in hurt, f"incidental hit misattributed at {e['t']}"


# ------------------------------------------------------------------------ main
def analyze(clip: str, backend: str = "api", bots: dict | None = None,
            ko: str | None = None) -> Path:
    name = Path(clip).stem
    frame_dir = ROOT / "frames" / name
    paths = sorted(frame_dir.glob("*.jpg"))
    if not paths:
        sys.exit(f"no frames in {frame_dir} — run extract_frames.py first")

    prompt = (ROOT / "backend" / "prompt.txt").read_text()
    api = {"cli": lambda: None, "openai": openai_client, "api": client}[backend]()
    print(f"backend: {backend} " + {"cli": "(claude -p, uses your subscription)",
                                    "openai": f"({OPENAI_MODEL}, OpenAI API key)",
                                    "api": f"({MODEL}, Anthropic API key)"}[backend])

    stamped = [((i) * SECONDS_PER_FRAME, p) for i, p in enumerate(paths)]
    # `look` carries each bot's appearance between calls. The model is stateless
    # per batch and the bots cross the arena constantly, so without this it
    # re-derives "left"/"right" from screen position every few frames and the
    # identities silently swap mid-fight. No hp here any more — the model emits
    # severity words and Python owns every number.
    state = {"left_look": "", "right_look": ""}
    names = {"left": None, "right": None}
    if bots:                       # a caller who knows the card anchors identity
        names.update({k: v for k, v in bots.items() if k in ("left", "right")})
    obs: list[dict] = []
    recent: list[str] = []

    for k in range(0, len(stamped), BATCH):
        batch = stamped[k:k + BATCH]
        ctx = stamped[k - 1] if k else None    # every judged frame gets a predecessor
        print(f"judging t={batch[0][0]:.0f}s..{batch[-1][0]:.0f}s "
              f"({k // BATCH + 1}/{-(-len(stamped) // BATCH)})")
        # `names`, not `bots` — it is seeded from --bots when given and filled in
        # from the broadcast graphics otherwise, so the card gets pinned either way
        out = (ask_cli(prompt, batch, ctx, recent, names, state) if backend == "cli"
               else ask_openai(api, prompt, batch, ctx, recent, names, state)
               if backend == "openai"
               else ask(api, prompt, batch, ctx, recent, names, state))

        for side in ("left", "right"):
            got = (out.get("bots") or {}).get(side)
            if got and not names[side]:
                names[side] = str(got)[:24]
            # first description wins — letting it drift per batch defeats the point
            look = (out.get("bots") or {}).get(f"{side}_look")
            if look and not state[f"{side}_look"]:
                state[f"{side}_look"] = str(look)[:60]

        by_t = {round(float(f.get("t", -1)), 1): f for f in out.get("frames", [])}
        for t, _ in batch:
            f = by_t.get(round(t, 1)) or {}     # a dropped frame is simply "no damage"
            sev = {s: str(f.get(s, "none")).lower().strip() for s in ("left", "right")}
            for s in ("left", "right"):
                if sev[s] not in SEVERITY:
                    print(f"  ! unknown severity {sev[s]!r} at t={t:.0f}s, treating as none",
                          file=sys.stderr)
            cost = {s: SEVERITY.get(sev[s], 0) for s in ("left", "right")}
            fin = f.get("finish") if f.get("finish") in ("left", "right") else None
            cap = trim_caption(f.get("caption", ""))
            # The raw hit rides along untouched until hp exist. It cannot be
            # normalised yet: pay() may still zero this frame's cost, and a hit
            # with no hp drop behind it is not a hit.
            obs.append({"t": round(t, 1), "cost": cost, "finish": fin, "caption": cap,
                        "raw_hit": f.get("hit")})
            if cost["left"] or cost["right"]:
                recent.append(f"{t:.0f}s left {sev['left']}, right {sev['right']}"
                              + (f" — {cap}" if cap else ""))
                del recent[:-2]                 # last two only; keep the footer short

    fin_i, loser = finish_at(obs)
    if fin_i is not None:
        obs = obs[:fin_i + 1]
    else:
        print("  ! no finish flag — timeline will have no KO", file=sys.stderr)
    if loser:
        # One flagged frame decides the KO, and it is often the worst frame to decide
        # it from: on manta-skorpios the KNOCKOUT graphic lands over a crowd shot with
        # no bot in it and the model picks a side at random. --ko settles it for a
        # clip someone has actually watched; otherwise the fight the model just
        # described is better evidence than its guess, so the more-damaged bot loses.
        # Ties and 0-0 keep the flag.
        took = {s: sum(o["cost"][s] for o in obs) for s in ("left", "right")}
        other = "left" if loser == "right" else "right"
        if ko and ko != loser:
            print(f"  ! KO flagged on {loser}, but --ko says {ko}", file=sys.stderr)
            loser = ko
        elif not ko and took[loser] < took[other]:
            print(f"  ! KO flagged on {loser}, but {other} took more damage "
                  f"({took}) — going with {other}", file=sys.stderr)
            loser = other
        obs[-1]["cost"][loser] = 0     # the finishing blow is free — it is forced to
                                       # 0 below, so charging it would spend budget
                                       # that belongs to the fight
    for side in ("left", "right"):
        pay(obs, side, KO_BUDGET if side == loser else LIVE_BUDGET)

    # hp at last, and only now can a hit be judged: normalize_hit() drops anything
    # with no hp drop behind it, so it has to see the damage the timeline will
    # actually show — after pay() has zeroed the surplus, not before.
    hp, observations, last = {"left": 100, "right": 100}, [], len(obs) - 1
    for i, o in enumerate(obs):
        before = dict(hp)
        for s in SIDES:
            hp[s] = max(0, hp[s] - o["cost"][s])
        if loser and i == last:                 # only the finish reaches zero, and
            hp[loser] = 0                       # it lands here so the finishing blow
                                                # has a real drop to attribute a hit to
        rec = {"t": o["t"], "left_hp": hp["left"], "right_hp": hp["right"],
               "caption": o["caption"]}
        hit = normalize_hit(o.get("raw_hit"), before, hp)
        if hit:
            rec["hit"] = hit
        elif o.get("raw_hit"):
            print(f"  ~ dropped unusable hit at t={o['t']:.1f}s")
        observations.append(rec)

    events = thin(observations)
    if not events or events[0]["t"] != 0.0:
        events.insert(0, {"t": 0.0, "left_hp": 100, "right_hp": 100, "caption": ""})
    events[0]["caption"] = ""
    events[0].pop("hit", None)                     # t=0 is a baseline, not a blow
    # The KO comes from the finish flag (cross-checked against --ko and against
    # accumulated damage), not from "first hp to hit 0" — under the budget only
    # the finish ever reaches 0, so the two agree, and the flag is the evidence.
    if loser:
        events[-1]["ko"] = loser

    # A caller who already knows the card wins over the model's reading of the
    # broadcast graphics; detection stays the default so era B still generalises
    # to a URL nobody has looked at. Resolved here so the comment join can match
    # on the real bot names.
    card = bots or {"left": names["left"] or "Bot A",
                    "right": names["right"] or "Bot B"}

    name_captions(events, card)          # "right rear on fire" -> "Tombstone rear on fire"

    comments_file = ROOT / "comments" / f"{name}.json"
    comments = json.loads(comments_file.read_text()) if comments_file.exists() else []
    if comments:
        join_comments(events, comments, card)
    else:
        print(f"(no {comments_file.name} — skipping fan comments)")

    timeline = {
        "clip": f"{name}.mp4",
        "bots": card,
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
    argv, backend, bots, ko = sys.argv[1:], "api", None, None
    if "--backend" in argv:
        i = argv.index("--backend")
        backend = argv[i + 1] if i + 1 < len(argv) else "api"
        del argv[i:i + 2]
    if "--bots" in argv:                    # same flag ingest.py takes; the broadcast
        i = argv.index("--bots")            # graphics are not always legible, and a
        pair = argv[i + 1] if i + 1 < len(argv) else ""   # misread name is worse than
        del argv[i:i + 2]                                 # no name at all
        left, _, right = pair.partition(",")
        if not (left.strip() and right.strip()):
            sys.exit('--bots takes "Left,Right"')
        bots = {"left": left.strip(), "right": right.strip()}
    if "--ko" in argv:                      # for a clip someone has watched: the
        i = argv.index("--ko")              # finish frame is often a crowd shot, and
        ko = argv[i + 1] if i + 1 < len(argv) else ""   # the model guesses the side
        del argv[i:i + 2]
        if ko not in ("left", "right"):
            sys.exit("--ko must be 'left' or 'right'")
    if backend not in ("api", "cli", "openai"):
        sys.exit("--backend must be 'api', 'cli' or 'openai'")
    # Same flag as ingest.py: re-judging a clip directly would otherwise lose the
    # card and fall back to "Bot A" / "Bot B".
    bots = None
    if "--bots" in argv:
        i = argv.index("--bots")
        pair = argv[i + 1] if i + 1 < len(argv) else ""
        left, _, right = pair.partition(",")
        if not (left.strip() and right.strip()):
            sys.exit('--bots needs two names, e.g. --bots "Manta,Skorpios"')
        bots = {"left": left.strip(), "right": right.strip()}
        del argv[i:i + 2]
    positional = [a for a in argv if not a.startswith("-")]
    if not positional:
        sys.exit(__doc__)
    analyze(positional[0], backend=backend, bots=bots, ko=ko)
