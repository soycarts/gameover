#!/usr/bin/env python3
"""analyze.py <clip> — frames -> Claude vision -> timelines/<clip>.json

    python backend/analyze.py fight1.mp4                    # Anthropic API key
    python backend/analyze.py fight1.mp4 --backend cli      # your Claude subscription
    python backend/analyze.py fight1.mp4 --backend openai   # OPENAI_API_KEY
    python backend/analyze.py fight1.mp4 --bots "Tombstone,Witch Doctor" --ko right
    python backend/analyze.py fight1 --rejoin                # comment join only

--rejoin re-runs ONLY the fan-comment join against an existing timeline: no
frames, no model call, no money, about a second. That is how a better
comments/<clip>.json reaches a committed timeline without re-judging the video.

--bots pins the card instead of trusting the model's reading of the broadcast
graphics, same flag ingest.py takes. Worth using on a re-judge: name detection
depends on whether a lower-third happens to be legible in the sampled frames, so
a clip that resolved to "Manta" once can come back as "Bot A" the next time.
--ko pins the losing side for a clip someone has actually watched; the finish
frame is often a crowd shot the model has to guess from.
--looks pins what each machine LOOKS like, where --bots pins only the names. Identity
is decided on batch 1 and latched for the whole run, and without this that one call has
no appearance information in it at all -- so the model maps the two names onto the two
machines by guessing, and nothing downstream can tell when it guessed wrong.

--backend openai swaps the vision judge to an OpenAI model (OPENAI_MODEL, default
gpt-5.5). Only the model call changes: the prompt, the hp clamp, thinning, KO
detection and the comment join are identical, so the JSON contract is unaffected.

--backend cli shells out to `claude -p` instead of the SDK, so judging runs on your
Claude Code subscription and needs no ANTHROPIC_API_KEY. It is slower and much
heavier per call (Claude Code re-sends its own system prompt and tool definitions
every time) and it consumes the same quota you need for coding. Fine for a demo
clip; use the API backend for anything long.

Sends frames in order, enough per call to cover BATCH_SECONDS of fight (6 at the
default 2 fps), each batch led by the previous batch's last frame as unjudged
context, plus a note of the last damage already reported (the model is stateless
between calls, so without it the same fire gets reported as fresh damage on every
frame) and the slice of broadcast commentary overlapping those frames. The frame
gap is read from frames/<clip>/meta.json, never assumed here -- there is no --fps
flag precisely so it cannot disagree with the frames on disk.

The model never emits hp: it rates each frame with a damage word per bot, and
SEVERITY turns that into points. Everything else -- merging one blow rated across
adjacent frames, discarding replays, the budget, thinning, the knockout count and the
fan comment join -- is deterministic Python, not model output.

A knockout is a COUNT, not a blow. immobile_from() finds where the loser stopped and
count_out() bleeds its remaining hp to 0 across the frames up to the finish, marked
`drain` so the frontend does not read the count as a hit. Forcing the whole remaining
bar onto the last event instead invented a finishing blow that no frame shows.

--no-audio drops the commentary and reproduces the pre-commentary behaviour exactly.

Idempotent: same frames + same comments file produce the same timeline.
"""
import base64
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
import extract_frames  # noqa: E402
import roster  # noqa: E402
import transcribe  # noqa: E402
# Scraped threads are about the whole season, so a MaD CaTTer search surfaces the
# SawBlaze fight too. names_a_rival() keeps a comment naming a bot that is not in
# THIS fight off the HUD; it lives in crowd.py next to the segmentation that
# decides what it is applied to.
from crowd import KNOWN_BOTS, names_a_rival  # noqa: E402,F401

ROOT = Path(__file__).resolve().parent.parent
MODEL = "claude-sonnet-5"
# --backend openai only. Override with OPENAI_MODEL; this account has no gpt-4o,
# so the default is the general GPT-5 model rather than a codex variant.
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.5")
# A call should span a few seconds of fight whatever the sampling rate. At 2 fps
# that is 6 frames, and the model gets a contiguous burst it can watch a blow land
# ACROSS — instead of two stills six seconds apart with the impact lost between
# them. Fixing the frame count instead would quadruple the call count and leave
# each call covering 1.5s, where nothing is ever "new".
BATCH_SECONDS = 3.0
BIG_DROP = 20                # heavy+ — the floor for a last-resort fan comment
COMMENT_DROP = 10            # solid+ — a hit worth reacting to, if a comment matches
MAX_CAPTION_WORDS = 6
MAX_WEAPON_WORDS = 3
SIDES = ("left", "right")
# What match_look() returns for a machine that is legitimately in the arena but
# cannot win or lose the fight — a minibot. Deliberately not a side and not None:
# "that was Ace" and "I could not tell" are different answers, and only the first
# is a reason to keep looking rather than to give up on the frame.
NOT_COMPETITOR = "other"

# The model judges severity; Python owns every number. Asking it for absolute hp
# instead made it nudge the bar down 3-5 points per frame to signal "time passed",
# which the HUD renders as mush. Nothing exists here between 0 and 4, so that drip
# is not representable. The rungs are spaced against the HUD's 5 cores x 20 hp, so
# a mis-graded hit is wrong by a category rather than by an unreadable 3 points.
SEVERITY = {"none": 0, "glance": 4, "solid": 12, "heavy": 22, "catastrophic": 35}
KO_BUDGET = 70               # damage a bot may take BEFORE the finishing blow
LIVE_BUDGET = 55             # ... for a bot still fighting at the end
FINISH_WINDOW = 0.7          # a finish flag in the first 70% of a clip is a misread
MERGE_WINDOW = 1.0           # one blow's follow-through, in seconds
MAX_DRAIN_STEPS = 20         # a count-out never adds more events than this
MAX_COUNT_SECONDS = 15.0     # a referee count is 10s; the graphic follows shortly
MIN_COUNT_SECONDS = 5.0      # ... and never shorter than this: see immobile_from()
SHUTOUT_FLOOR = SEVERITY["solid"]   # under this, a bot is "untouched" — see repass()
LOOK_FLOOR = 0.34            # below this a description matches neither machine
LOOK_MARGIN = 0.12           # ... and this close together, it is a coin flip
# "both twins are out", "two machines down" — the only way a description can say
# 60% of a true multibot has stopped, since identical machines have identical looks
PLURAL_RE = re.compile(r"\b(both|two|pair|twins|all)\b", re.I)
LADDER = ("none", "glance", "solid", "heavy", "catastrophic")
REGRADE_UP = 2               # rungs a re-look may ADD to a blow the first pass scored
REGRADE_DOWN = 1             # ... and take off it. Never below "glance": see relook()

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

    This used to say "the ONLY two competitors are X and Y", which is FALSE for a
    fight with a minibot in it, and false in the most expensive direction: a third
    machine is plainly on screen, the model has been told only two exist, so it
    files the minibot under whichever competitor it looks closest to. Ace is in the
    jackpot-copperhead frames at four separate moments. Nothing downstream can
    catch that — a hit credited to the wrong machine is self-consistent.

    So the non-competitors are named too, with what they are. That keeps the
    anti-sponsor-livery force of the original line (it is still a closed list of
    machines) while giving the model somewhere correct to put the minibot.
    """
    names = names or {}
    head = ""
    extra = state.get("others") or {}
    if names.get("left") and names.get("right"):
        head = (f"The two competitors are {names['left']} (left) and "
                f"{names['right']} (right). Use no other name in a caption — text on "
                f"the robots is sponsor livery, not a bot.\n")
        if extra:
            listed = "; ".join(f"{n} ({look})" if look else n
                               for n, look in extra.items())
            head += (f"Also in the arena, and NOT competitors: {listed}. "
                     f"These are minibots. They are not "
                     f"{names['left']} or {names['right']}, they cannot win or lose "
                     f"the fight, and NOTHING they do is damage: a minibot lifting, "
                     f"shoving or hitting a competitor is not a hit, and a minibot "
                     f"being destroyed is not damage to its team. Report their "
                     f"contact as none.\n")
    bits = []
    for side in ("left", "right"):
        look = state.get(f"{side}_look")
        if look:
            name = names.get(side)
            bits.append(f"{side}{f' ({name})' if name else ''} = {look}")
    if not bits:
        return head + ("Identify each bot by appearance, not screen position, and say "
                       "so in left_look / right_look.\n")
    # A pinned description came from a human who watched the fight, so it is stated
    # as fact. A model-derived one is its own earlier guess, and telling it that is
    # settled truth is how a bad first batch poisons an entire run.
    if state.get("pinned"):
        return head + ("These are the two machines, and this is CORRECT — do not "
                       "revise it, and do not infer identity from screen position: "
                       + "; ".join(bits) + ". A bot's weapon belongs to IT: damage "
                       "done by that weapon is damage it DEALT, never damage it took. "
                       "Re-identify by appearance in every frame.\n")
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


def commentary_note(talk: list[dict]) -> str:
    """Live broadcast commentary overlapping THIS batch's frames.

    Two jobs the frames alone do badly:
      - WHO. The commentators say the names out loud, constantly. That beats a
        lower-third that is legible in one frame out of ten, and reading the
        sides backwards is a documented failure on manta-skorpios.
      - WHAT. "A BIG HIT BY MANTA RIGHT OUT OF THE GATE" pins a real blow to a
        real second, which is how the opening hit on manta-skorpios gets scored
        at full weight instead of being lost between two stills.

    It is a clue, never a licence. Commentators exaggerate, hype moments where
    nothing happened, and talk about the crowd, the pits and earlier fights. The
    damage rating still has to come off the pixels.

    And these are AUTO-CAPTIONS, which mishear. The line after that one comes back
    as "Manta got hit by that huge drum spinner" — but the drum is Manta's OWN
    weapon, so the words are a garble of "got him with". Read literally it scored
    three separate hits against the eventual winner off one mistranscribed verb,
    which is why prompt.txt now says a weapon belongs to the bot carrying it.

    Empty when there is no transcript, and then the footer is byte-identical to
    what it was before commentary existed — which is what makes the whole feature
    strictly additive and unable to break an existing run.
    """
    if not talk:
        return ""
    lines = "\n".join(f"  [{s['start']:.1f}s] {s['text']}" for s in talk)
    return ("Live commentary heard over these frames (it lags the action by about "
            "a second, and is not always about the fight):\n" + lines + "\n"
            "Use it for WHO and WHAT. It is not proof of damage: if the frames do "
            'not show it, the rating is still "none".\n'
            # Stated HERE, next to the cues, and not only once in the system
            # prompt: these three sentences are the difference between a garbled
            # verb costing 20 hp on the eventual winner and costing nothing.
            "These are auto-captions and they mishear. A bot is never damaged by a "
            "weapon it carries — read such a line as that bot LANDING the blow. "
            "They also drop and swap subjects, so a line about something being hit, "
            "stuck or stopped is evidence that SOMETHING happened, never evidence "
            "about WHICH machine it happened to. Where two lines here disagree "
            "about who is hitting whom, believe the frames and nothing else.\n")


def immobile_note() -> str:
    """Re-state the `immobile` rule on every call, for the same reason the `hit`
    rule is re-stated: a field explained only in prompt.txt gets honoured for a
    batch or two and then quietly forgotten for the rest of a long clip.

    This one costs more to forget than most. `immobile` is the field that is meant
    to REPEAT, and the flags that matter arrive at the very END of the fight — a
    27-batch clip drifts long before it gets there, so the count-out loses its
    evidence exactly when it needs it. Asking for a description rather than a side
    is also the unusual instruction here, and the unusual instruction is the first
    one to decay back to the obvious one.
    """
    return ('"immobile": when a machine is not moving under its own power, DESCRIBE '
            'THAT MACHINE (colour, shape, weapon) — never "left"/"right". Repeat it '
            'on every frame it stays true. null when you cannot see either bot.\n')


def footer(frames: list[tuple[float, Path]], recent: list[str],
           card: dict | None = None, state: dict | None = None,
           talk: list[dict] | None = None, spf: float = 2.0) -> str:
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
            + commentary_note(talk or [])
            + f"These frames are {spf:.1f}s apart. A single blow can appear in more "
              f"than one of them — rate it on the FIRST frame where you see it, and "
              f'"none" on the frames that only show its aftermath.\n'
            + f"Already reported: {'; '.join(recent) or 'nothing yet'}\n"
            + 'For every frame where a bot takes damage (any word other than '
              '"none"), include "hit" ({"by": "left"|"right", "weapon": ..., '
              '"clean": true|false, "at": [x, y]}) naming the bot that LANDED the '
              'blow, and where on the frame it landed. '
              'Omit "hit" when both bots are "none".\n'
            + immobile_note()
            + f"Return one entry per frame above, at exactly these timestamps: "
              f"{[round(t, 1) for t, _ in frames]}")


def ask(api, prompt: str, frames: list[tuple[float, Path]],
        ctx: tuple[float, Path] | None, recent: list[str],
        card: dict | None = None, state: dict | None = None,
        talk: list[dict] | None = None, spf: float = 2.0) -> dict:
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
    content.append({"type": "text", "text": footer(frames, recent, card, state, talk, spf)})

    last_err = None
    for attempt in range(2):                       # one retry on bad JSON
        msg = api.messages.create(
            # 6 frame entries plus the bots block crowds 1024, and a truncated
            # reply falls into the bad-JSON retry and bills the batch twice
            model=MODEL, max_tokens=2048, system=prompt,
            messages=[{"role": "user", "content": content}],
        )
        try:
            return parse_json(msg.content[0].text)
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e
            content = content + [{"type": "text", "text":
                "Your last reply was not valid JSON. Reply with the JSON object only."}]
    print(f"  ! giving up on this batch: {last_err}", file=sys.stderr)
    return {"frames": [], "failed": True}


def ask_openai(api, prompt: str, frames: list[tuple[float, Path]],
               ctx: tuple[float, Path] | None, recent: list[str],
               card: dict | None = None, state: dict | None = None,
        talk: list[dict] | None = None, spf: float = 2.0) -> dict:
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
    content.append({"type": "text", "text": footer(frames, recent, card, state, talk, spf)})

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
            return {"frames": [], "failed": True}
        try:
            return parse_json(msg.choices[0].message.content or "")
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e
            messages = messages + [{"role": "user", "content":
                "Your last reply was not valid JSON. Reply with the JSON object only."}]
    print(f"  ! giving up on this batch: {last_err}", file=sys.stderr)
    return {"frames": [], "failed": True}


def ask_cli(prompt: str, frames: list[tuple[float, Path]],
            ctx: tuple[float, Path] | None, recent: list[str],
            card: dict | None = None, state: dict | None = None,
        talk: list[dict] | None = None, spf: float = 2.0) -> dict:
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
        f"{footer(frames, recent, card, state, talk, spf)}\n"
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
        return {"frames": [], "failed": True}
    if done.returncode != 0:
        print(f"  ! claude -p failed: {done.stderr.strip()[:200]}", file=sys.stderr)
        return {"frames": [], "failed": True}
    try:
        # -p --output-format json wraps the reply; the reply itself may have prose
        # and ``` fences around the JSON, which parse_json() tolerates.
        return parse_json(json.loads(done.stdout)["result"])
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        print(f"  ! could not parse claude -p reply: {e}", file=sys.stderr)
        return {"frames": [], "failed": True}


# ------------------------------------------------------------ deterministic bits
def words(text: str) -> set[str]:
    return {w for w in re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split()
            if w and w not in STOPWORDS and len(w) > 2}


def match_look(desc: str, looks: dict, names: dict,
               others: dict | None = None) -> str | None:
    """Which machine a free-text description of a stopped machine refers to.

    Returns "left", "right", NOT_COMPETITOR for a minibot, or None.

    Scored on shared content words, because that is what the descriptions ARE —
    colour, shape and weapon words, which is exactly what a human pins in --looks.
    Words common to more than one machine are discounted to nothing: on
    manta-skorpios both looks contain "wedge", so whole-string similarity (difflib
    on the pair, the obvious first idea) scores the two sides almost identically
    and decides on noise. The discriminating tokens are blue/yellow/drum versus
    copper/teal/forked/blade, and only the distinctive ones should get a vote.

    `others` maps a non-competitor machine's name to its appearance — Jackpot's
    Ace, MaDCaTTer's Gassy Cat. They are scored in the SAME contest rather than
    checked afterwards, because the question is genuinely "which of the machines
    in this arena is this", and a minibot that only competes against itself would
    win by default. A description that lands on one of them is evidence about a
    machine that cannot win or lose the fight, which callers read as no evidence
    about the SIDE — see resolve_immobile().

    Returns None when nothing clears LOOK_FLOOR or the top two are within
    LOOK_MARGIN of each other. A coin flip is precisely the failure this replaces,
    and immobile_from() already reads None as "no evidence" rather than as a side.
    """
    d = words(desc)
    if not d:
        return None
    low = (desc or "").lower()
    for name, _ in (others or {}).items():   # a name in the description settles it
        if name.lower() in low:
            return NOT_COMPETITOR
    for side in SIDES:
        n = names.get(side)
        if n and n.lower() in low:
            return side
    bags = {s: words(looks.get(s) or "") for s in SIDES}
    bags.update({f"{NOT_COMPETITOR}:{n}": words(v) for n, v in (others or {}).items()})
    # a token has to be distinctive to vote, and with three machines in the arena
    # "distinctive" means it appears in exactly one bag, not just "not in both"
    seen = Counter(w for bag in bags.values() for w in bag)
    shared = {w for w, c in seen.items() if c > 1}
    # score against the DESCRIPTION's distinctive words, not the look string's:
    # dividing by the look would mark down a short, correct answer ("low blue
    # wedge") purely for being shorter than the look it matches
    told = d - shared
    if not told:
        return None
    score = {k: len(told & (bag - shared)) / len(told) for k, bag in bags.items()}
    ranked = sorted(score, key=lambda k: -score[k])
    best = ranked[0]
    runner = score[ranked[1]] if len(ranked) > 1 else 0.0
    if score[best] < LOOK_FLOOR or score[best] - runner < LOOK_MARGIN:
        return None
    return NOT_COMPETITOR if best.startswith(NOT_COMPETITOR) else best


def others_for(names: dict) -> dict:
    """{minibot name: what it looks like} for the machines in THIS fight.

    Read off the committed roster rather than a flag, because which minibot a team
    brings is a property of the team, not of the clip — pinning it per-run is one
    more thing to get wrong on a re-judge. Empty when the roster has not been
    scraped, which is exactly the behaviour before any of this existed.
    """
    out = {}
    table = roster.load()
    for side in SIDES:
        entry = table.get(roster.bot_key(names.get(side) or ""))
        for m in roster.minibots(entry):
            out[m["name"]] = roster.minibot_look(m["name"])
    return out


def machines_needed(name: str) -> int:
    """How many of this bot's machines must stop before a count can start (7.5.4)."""
    entry = roster.load().get(roster.bot_key(name or ""))
    return roster.min_down(entry["machines"]) if entry else 1


def resolve_immobile(raw, state: dict, names: dict, tally: dict) -> str | None:
    """The model's `immobile` answer -> a side, or None.

    prompt.txt now asks for a DESCRIPTION of the stopped machine rather than a
    side, because naming the side is the hardest call in the clip and the model
    gets it wrong: on manta-skorpios it flagged the WINNER immobile on 3 of 5
    frames. A description can be checked against --looks, which is human-verified;
    a side cannot be checked against anything.

    A bare "left"/"right" is still accepted — that is what every timeline judged
    before this change contains, and a model that ignores the reworded prompt has
    to keep working.
    """
    if raw in SIDES:
        tally["side"] = tally.get("side", 0) + 1
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return None
    got = match_look(raw, {s: state.get(f"{s}_look") for s in SIDES}, names,
                     state.get("others"))
    # A stopped MINIBOT is not a stopped competitor. Counting it would start a
    # referee count on a bot that is still driving, which is the single most
    # damaging thing a false immobile flag can do — count_out() then zeroes every
    # loser-side cost from that point and erases real blows. Tallied separately so
    # the run prints how often it happened rather than silently swallowing it.
    if got == NOT_COMPETITOR:
        tally["minibot"] = tally.get("minibot", 0) + 1
        return None
    tally["matched" if got else "ambiguous"] = \
        tally.get("matched" if got else "ambiguous", 0) + 1
    return got


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


def merge_blows(obs: list[dict], window: float = MERGE_WINDOW) -> None:
    """Collapse one physical blow rated across several adjacent frames.

    At one frame per 2s an impact is visible in exactly one frame. At 0.5s the
    impact, the debris and the recoil land in three or four, and the model rates
    all of them — which is a fresh way to rebuild the 3-5 point drip the severity
    ladder exists to kill, this time out of real ratings rather than invented
    ones. Per side, inside `window` seconds, keep the single most severe
    observation and zero the rest.

    max, never sum: one blow is one rung on the ladder, and adding rungs together
    produces damage totals no rung can represent and that no HUD tier can band.

    Ties go to the EARLIER frame, so this is deterministic and idempotent — run
    it twice and nothing more moves. Zeroed observations keep their captions,
    exactly like pay()'s leftovers, so thin() still has a beat for the HUD.

    Deliberately does NOT merge across sides: an exchange that damages both bots
    is TWO hits, and deriveHits() in index.html is the one place that definition
    lives. Note window < the old 2.0s gap, so this is a no-op on frames extracted
    at 0.5 fps and cannot regress a timeline judged before the change.
    """
    for side in SIDES:
        i = 0
        while i < len(obs):
            if not obs[i]["cost"][side]:
                i += 1
                continue
            j = i
            while j + 1 < len(obs) and obs[j + 1]["t"] - obs[i]["t"] <= window:
                j += 1
            keep = min(range(i, j + 1), key=lambda k: (-obs[k]["cost"][side], k))
            for k in range(i, j + 1):
                if k != keep:
                    obs[k]["cost"][side] = 0
            i = j + 1


def stop_pass(dispatch, prompt: str, stamped: list, obs: list[dict], loser: str,
              names: dict, state: dict, spf: float, talk_all: list[dict]) -> int:
    """Ask one question over the closing frames: when did the LOSER stop.

    This is the only place in the pipeline where naming the loser to the model is
    legitimate. `loser` is not settled until --ko and the damage cross-check have
    run, and telling the damage pass who loses would let it write the ending it was
    told about rather than the one it can see. Here the fight is already judged and
    the only open question is timing.

    Sub-sampled to ~1fps: on manta-skorpios half the count window is booths and
    crowd with no robot in it at all, and the answer feeds count_out(), whose drain
    step is one second anyway — so a finer grid would cost tokens to buy precision
    nothing downstream can spend.

    Writes into obs[i]["immobile"] and returns how many frames it set, so
    immobile_from() runs completely unchanged afterwards.
    """
    who, other = names.get(loser) or loser, names.get(other_side(loser)) or "the winner"
    end_t = obs[-1]["t"]
    lo = max(0.0, end_t - MAX_COUNT_SECONDS - 2.0)
    every = max(1, int(round(1.0 / spf)))
    want = [t for t, _ in stamped if lo <= t <= end_t][::every][-16:]
    frames = [(t, p) for t, p in stamped if t in set(want)]
    if not frames:
        return 0
    focus = (prompt + "\n\nFINAL PASS — ONE QUESTION.\n"
             f"{who} lost this fight. For each frame below answer ONLY:\n"
             f'  "visible": true if you can see {who} in this frame at all — a crowd '
             f"shot, a driver booth, a referee, or a close-up of {other} is false;\n"
             f'  "stopped": true if {who} is not moving under its own power — not '
             f"driving, not turning, weapon stopped or coasting down, moving only "
             f"when it is shoved. Answer this only when \"visible\" is true.\n"
             f"Say nothing about damage and do not rate either bot. Return "
             f'{{"frames": [{{"t": 0.0, "visible": true, "stopped": false}}]}}.\n')
    by_t: dict[float, dict] = {}
    for k in range(0, len(frames), 6):
        batch = frames[k:k + 6]
        talk = transcribe.window(talk_all, batch[0][0], batch[-1][0])
        print(f"stop pass t={batch[0][0]:.0f}s..{batch[-1][0]:.0f}s")
        out = dispatch(focus, batch, None, [], names, state, talk, spf)
        for f in out.get("frames", []):
            by_t[round(float(f.get("t", -1)), 1)] = f
    idx = {o["t"]: i for i, o in enumerate(obs)}
    n = 0
    for t, f in by_t.items():
        i = idx.get(t)
        if i is None or f.get("visible") is not True:
            continue          # not seeing a bot is no evidence — leave the frame be
        was = obs[i]["immobile"]
        obs[i]["immobile"] = loser if f.get("stopped") is True else None
        n += obs[i]["immobile"] != was
    return n


def other_side(s: str) -> str:
    return "left" if s == "right" else "right"


def word_for(cost: int) -> str:
    """The ladder word a cost came from. Exact by construction: nothing in the
    pipeline ever scales a cost, so every one is a SEVERITY value or zero."""
    for w, v in SEVERITY.items():
        if v == cost:
            return w
    return "none"


def relook(dispatch, prompt: str, stamped: list, obs: list[dict], spf: float,
           names: dict, state: dict) -> int:
    """Re-grade the blows the first pass already found. Returns how many moved.

    The first pass answers two questions at once — did anything happen, and how
    bad was it — across a whole fight, with a strong "if unsure, none" prior. It
    is reliably good at the first and weak at the second: on manta-skorpios the
    opening blow launches Skorpios fully airborne and came back "solid", the same
    rung as an ordinary shove, because one call had to judge it in passing.

    Three properties keep this from becoming the 3-5 point drip:

    - it only ever re-grades frames that ALREADY scored, and never creates a
      scoring frame, so the number of blows is invariant — only their rung moves;
    - a move is capped at +REGRADE_UP / -REGRADE_DOWN rungs and never reaches
      "none", so no single call can turn a graze into a knockout blow or delete a
      blow the frames genuinely show;
    - it snaps to a rung. Nothing here produces a value the ladder cannot express,
      which is the whole reason the ladder exists.

    pay() still runs afterwards on the same budgets, so the totals cannot inflate:
    a re-graded fight redistributes which blows win the auction, not how much
    there is to spend.

    Deliberately blind: the first pass's rating is NOT in the prompt. A stated
    prior turns a second opinion into a rubber stamp. Deliberately deaf too —
    talk=[] — because prompt.txt is explicit that commentary is evidence for WHO
    and WHAT and never for HOW HARD, and a micro-batch centred on a big blow is
    exactly where the commentators are shouting. commentary_note([]) returns "",
    so the footer is byte-identical to a no-transcript run.
    """
    focus = (prompt + "\n\nSECOND PASS — SEVERITY ONLY.\n"
             "These frames contain ONE blow that has already been found and "
             "attributed. Your only job is HOW HARD it was, on the ladder above. Do "
             "not look for new blows, and do not re-attribute this one. The middle "
             "frame is the moment; the frames either side are what changed. Grade "
             "what you can see change between them: whether the bot left the floor, "
             "how it landed, what came off, what stopped turning.\n")
    moved = 0
    hits = [i for i, o in enumerate(obs) if o["cost"]["left"] or o["cost"]["right"]]
    for n, i in enumerate(hits, 1):
        batch = stamped[max(0, i - 1):i + 2]
        ctx = stamped[i - 2] if i >= 2 else None
        print(f"re-grading t={obs[i]['t']:.1f}s ({n}/{len(hits)})")
        out = dispatch(focus, batch, ctx, [], names, state, [], spf)
        f = {round(float(x.get("t", -1)), 1): x
             for x in out.get("frames", [])}.get(obs[i]["t"]) or {}
        for side in SIDES:
            old = obs[i]["cost"][side]
            if not old:
                continue                       # this side was not the one damaged
            sev = str(f.get(side, "")).lower().strip()
            if sev not in SEVERITY:
                continue
            lo = LADDER.index(word_for(old))
            new = min(LADDER.index(sev), lo + REGRADE_UP)
            new = max(new, lo - REGRADE_DOWN, 1)       # never back down to "none"
            if new != lo:
                print(f"  {obs[i]['t']:.1f}s {side} {LADDER[lo]} -> {LADDER[new]}")
                obs[i]["cost"][side] = SEVERITY[LADDER[new]]
                moved += 1
    return moved


def verify(dispatch, prompt: str, stamped: list, obs: list[dict], spf: float,
           names: dict, state: dict) -> int:
    """Re-ask WHO landed each scored blow, or whether one landed at all.

    relook() is the right shape and the wrong question: its brief forbids
    re-attribution and its floor stops it ever answering "nothing happened here".
    So the one failure neither it nor any deterministic guard can reach is a blow
    the model was TALKED INTO — the damage word and `hit.by` come from a single
    act of identification, so a wrong one is self-consistent and `normalize_hit()`
    sees no contradiction to flip.

    On manta-skorpios the auto-captions said "Manta got hit by that / huge drum
    spinner" — the drum is Manta's, so the line is a garble of "got him with" —
    and the judge charged the eventual WINNER 20 hp across three frames, with a
    caption inverting the attribution on every one. The frames show no contact at
    all on two of them.

    Deaf on purpose (talk=[]), for a sharper reason than relook()'s: the garbled
    commentary is the very thing being checked against, so letting it into this
    call would ask the model to mark its own homework with the same crib sheet.

    Bounded to three outcomes, none of which can invent damage:
      - "none"  -> no contact in this frame: drop the blow and its caption;
      - a side  -> keep it, flipping `by` and the damaged side if it disagrees;
      - unparseable -> leave the frame exactly as it was.
    It never touches a frame that scored zero, and never changes severity — that
    is --regrade's job, and keeping the two passes to one question each is what
    makes either of them auditable.
    """
    changed = 0
    hits = [i for i, o in enumerate(obs) if o["cost"]["left"] or o["cost"]["right"]]
    for n, i in enumerate(hits, 1):
        # A WIDER window than relook()'s, and that is the whole point. The question
        # "is this a new blow or the tail of the last one" cannot be answered from
        # the moment alone: on manta-skorpios t=7.5 is Skorpios dropping back down
        # from the lift it took at t=6.5, and a three-frame window starting at t=7.0
        # does not contain the lift, so the pass was being told "settling after an
        # earlier hit is not contact" while being shown no earlier hit. Lead by
        # MERGE_WINDOW's worth of frames so the originating blow is always in view.
        lead = max(2, round(MERGE_WINDOW / spf))
        batch = stamped[max(0, i - lead):i + 2]
        ctx = stamped[max(0, i - lead - 1)] if i > lead else None
        t = obs[i]["t"]
        focus = (prompt + "\n\nSECOND PASS — ATTRIBUTION ONLY.\n"
                 f"A blow was rated at t={t:.1f}s. The frames before it are there so "
                 "you can see what led into it. Two questions about that ONE moment, "
                 "and nothing else:\n"
                 f"1. Do the frames show the machines making NEW contact at t={t:.1f}s, "
                 "or a machine visibly taking fresh damage there? A bot dropping back "
                 "down, bouncing, sliding or coming to rest after a hit in an EARLIER "
                 "frame is the aftermath of that hit, not a new one — and neither is "
                 "driving past, turning to line up, or sitting still.\n"
                 f"2. If it is new contact, WHICH machine landed it at t={t:.1f}s?\n"
                 'Answer as {"contact": true|false, "by": "left"|"right"|null}. Say '
                 "contact false whenever you are unsure: a blow that did not happen "
                 "costs more than one that is missed, because it is charged to the "
                 "wrong robot. Do not grade how hard it was.\n")
        print(f"verifying t={obs[i]['t']:.1f}s ({n}/{len(hits)})")
        out = dispatch(focus, batch, ctx, [], names, state, [], spf)
        f = {round(float(x.get("t", -1)), 1): x
             for x in out.get("frames", [])}.get(obs[i]["t"])
        if not isinstance(f, dict):
            f = out if isinstance(out, dict) and "contact" in out else None
        if not isinstance(f, dict) or "contact" not in f:
            continue                       # unparseable: leave the frame alone
        if f.get("contact") is False:
            print(f"  {obs[i]['t']:.1f}s no contact — dropping the blow")
            obs[i]["cost"] = {s: 0 for s in SIDES}
            obs[i]["raw_hit"] = None
            obs[i]["caption"] = ""
            changed += 1
            continue
        by = str(f.get("by", "")).strip().lower()
        if by not in SIDES:
            continue
        victim = "left" if by == "right" else "right"
        if obs[i]["cost"][victim] or not obs[i]["cost"][by]:
            continue                       # already agrees, or an exchange: leave it
        # the damage sits on the side this call says LANDED the blow — swap it
        print(f"  {obs[i]['t']:.1f}s re-attributed to {names.get(by) or by}")
        obs[i]["cost"] = {victim: obs[i]["cost"][by], by: 0}
        if isinstance(obs[i].get("raw_hit"), dict):
            obs[i]["raw_hit"]["by"] = by
        # the caption named the old attacker ("Skorpios forks lift Manta") and is
        # now backwards. Blank beats wrong: the hp still moves, so the hit and its
        # marker survive, and the HUD simply types nothing over them.
        obs[i]["caption"] = ""
        changed += 1
    return changed


def repass(dispatch, prompt: str, stamped: list, batch_n: int, spf: float,
           talk_all: list[dict], names: dict, state: dict, side: str) -> dict:
    """Judge the frames again, watching ONE bot — the one the first pass never
    scored.

    A fight where one machine is never rated above "none" is almost always a
    mis-read, not a clean sweep: the winner of a hard match still loses parts.
    The first pass has a strong "if unsure, none" prior and a whole fight to
    cover; this pass has one job, so it notices the scuffs.

    Only ever ADDs, and the blast radius is bounded by code that already exists:
    whatever comes back is max()'d into the first pass's costs and then still has
    to survive pay() on LIVE_BUDGET, so even a maximally over-eager second pass
    cannot take this bot below hp 45. Nothing here fabricates damage — a rating
    with no hp drop behind it is dropped by normalize_hit() exactly as before.
    """
    who = names.get(side) or side
    focus = (prompt + "\n\nSECOND PASS — ONE BOT ONLY.\n"
             f"A first pass over these same frames rated {who} (the {side} bot) as "
             f'"none" on every single frame of this fight. That is almost always a '
             f"mis-read. Watch {who} and nothing else. Rate the OTHER bot \"none\" "
             f"throughout — it has already been judged and is not your job here.\n"
             f"Look for what a busy first pass misses on the bot that is winning: a "
             f"panel bent or torn, a wheel or tyre damaged, sparks off its armour, "
             f"being thrown, flipped, or slammed into a wall or hazard, smoke, a "
             f"weapon that stops turning. Some of these frames genuinely are "
             f'"none" — do not invent a hit to fill the fight. Report only damage '
             f"you can point at in the frame.\n")
    found: dict[float, dict] = {}
    recent: list[str] = []
    for k in range(0, len(stamped), batch_n):
        batch = stamped[k:k + batch_n]
        ctx = stamped[k - 1] if k else None
        talk = transcribe.window(talk_all, batch[0][0], batch[-1][0])
        out = dispatch(focus, batch, ctx, recent, names, state, talk, spf)
        by_t = {round(float(f.get("t", -1)), 1): f for f in out.get("frames", [])}
        for t, _ in batch:
            f = by_t.get(round(t, 1)) or {}
            sev = str(f.get(side, "none")).lower().strip()
            cost = SEVERITY.get(sev, 0)
            if not cost:
                continue
            cap = trim_caption(f.get("caption", ""))
            found[round(t, 1)] = {"cost": cost, "caption": cap,
                                  "raw_hit": f.get("hit")}
            recent.append(f"{t:.0f}s {side} {sev}" + (f" — {cap}" if cap else ""))
            del recent[:-2]
    return found


def drop_replays(obs: list[dict]) -> int:
    """Score no new damage on replay frames.

    Broadcasts cut to slow motion constantly, and a replay is a blow the judge has
    already scored live. Counting it again is double-counting the same hit — on
    manta-skorpios the whole t=12..21.5s stretch is a slow-motion replay with the
    match clock hidden, and the pipeline read it as fresh action.

    Captions survive: a replay is a perfectly good moment for the HUD to narrate,
    it just must not move the bar. Returns how many frames were zeroed.
    """
    n = 0
    for o in obs:
        if o.get("replay") and (o["cost"]["left"] or o["cost"]["right"]):
            o["cost"] = {s: 0 for s in SIDES}
            o["raw_hit"] = None
            n += 1
    return n


def drop_downed_hits(obs: list[dict], names: dict | None = None) -> int:
    """A machine that is not moving under its own power did not just land a blow.

    The model answers the damage word and `hit.by` in one breath, from one act of
    identification, so a mis-identification is SELF-CONSISTENT: `normalize_hit()`
    only flips a hit whose `by` contradicts the hp delta, and here it does not.
    This is the one cross-check the pipeline can make on its own, because it
    compares two INDEPENDENT answers about the same frame — "who landed this" and
    "which machine has stopped" — and the second has already been matched against
    the human-verified --looks by resolve_immobile().

    On manta-skorpios the model flagged Skorpios immobile from t=14.0 and then
    credited it with a clean blow at t=14.5. It also fed that phantom blow to
    immobile_from(), which reads `raw_hit.by == side` as proof the bot was still
    driving — so the false hit was corrupting the count-out walk as well. This
    runs BEFORE that walk, to take the bad evidence out rather than argue with it.

    Only `clean` hits: an incidental one is a fire, a wall or a fall, and a
    stopped machine suffers those exactly as well as a moving one.
    """
    dropped = 0
    for o in obs:
        raw = o.get("raw_hit") or {}
        by = str(raw.get("by", "")).strip().lower()
        if by not in SIDES or raw.get("clean") is False:
            continue
        if o.get("immobile") != by:
            continue
        who = names.get(by) if names else by
        print(f"  ~ dropped hit at t={o['t']:.1f}s: {who} is described immobile on "
              f"that frame, so it did not land it", file=sys.stderr)
        # the blow's damage landed on the OTHER side; anything the immobile bot
        # itself took on this frame came from a different blow and stands
        victim = "left" if by == "right" else "right"
        o["cost"][victim] = 0
        o["raw_hit"] = None
        # the caption described the blow just deleted, so it goes with it — but
        # only once nothing else on the frame scored, or it may be narrating the
        # other half of an exchange
        if not any(o["cost"][s] for s in SIDES):
            o["caption"] = ""
        dropped += 1
    return dropped


def immobile_from(obs: list[dict], side: str, confirm: int = 3,
                  need: int = 1) -> int | None:
    """Start of the run of immobility that `side` never comes back from.

    The count-out starts here, not at the KNOCKOUT graphic — the bot dies well
    before the broadcast says so, and draining from the graphic is what produced
    the one fabricated massive blow this function exists to remove.

    Walked BACKWARDS from the end, because that is the question being asked: not
    "when did it first look stopped" but "how far back does the stop that ended the
    fight reach". Only positive evidence that the fight was still on breaks the walk,
    and there are exactly two kinds:

      - the bot LANDING a blow, since it has to be driving to do that;
      - the bot TAKING a scored blow. A frame that cost hp is a frame a judge was
        still watching a fight, not a count. On manta-skorpios the model called
        Skorpios immobile at t=14.0, but Manta LAUNCHES it at t=15.5 — and the
        count window zeroes every loser-side cost from its start, so that launch
        scored nothing, emitted no `hit` and landed on the HUD as a caption over a
        frozen bar. The broadcast's own KNOCKOUT : 24sec settles it: a ten-second
        count ending at match 24 cannot have started at clip t=14.

    The second rule is bounded by MIN_COUNT_SECONDS, and the bound is load-bearing.
    A winner grinding on a downed bot one second before the graphic would otherwise
    collapse the count to a single step — which is the phantom finishing blow this
    whole function exists to delete, rebuilt out of a real rating. A blow that close
    to the end is treated as no evidence and the walk continues past it.

    Everything else is treated as no evidence, deliberately:
      - a frame where the bot is not on screen reports None. Crowd shots, driver
        booths and close-ups of the other machine fill the back half of a KO clip,
        and reading an absent bot as a moving one would reject every real count-out;
      - a frame naming the OTHER bot says nothing about this one. `immobile` holds a
        single side, so the model cannot report both at once.

    `confirm` sightings are needed overall, so one blurred misread cannot start a
    count on a bot that is still fighting.

    `need` is the 7.5.4 rule: a multibot is counted out only when 60% or more of
    its COMBINED weight has stopped. For every ordinary bot, and for every bot
    with a minibot, roster.min_down() returns 1 — a 250lb machine is 93% of itself
    plus a 20lb minibot — so this branch is inert and the walk behaves exactly as
    it always has. It is 2 only for a true multibot like The Twins, where one of
    two equal machines is 50% and not enough. There the sighting has to say more
    than one machine is down, because two identical twins cannot be told apart
    from a description and `immobile` holds one machine at a time.

    WHICH bot is down comes from `side` (the settled loser), not from the model.
    "Something has stopped" is an easy call; "which of these two machines is it" is
    the hardest call in this clip, and the model gets it wrong — on manta-skorpios
    it flags Manta, the WINNER, immobile across the very frames Skorpios is being
    counted out on. So any immobile flag counts as a sighting and it is read against
    the loser. That is safe by construction here: the walk runs backwards from the
    end, and the bot still being counted out at the end of a fight is the one that
    lost it. Disagreements are printed rather than swallowed.
    """
    end = obs[-1]["t"] if obs else 0.0
    # only for the message below: a blow BEFORE anything was ever called immobile
    # just ends a pointless walk, and saying so would read as a correction it isn't
    first_imm = next((o["t"] for o in obs if o.get("immobile")), None)
    start, seen, swapped, stopped_by = None, 0, 0, None
    for i in range(len(obs) - 1, -1, -1):
        o = obs[i]
        # Both checked FIRST, and they win: the model can flag a bot immobile on the
        # very frame it also credits it with a blow, and the blow is the harder
        # evidence. Checking immobility first walks straight past the contradiction.
        if (o.get("raw_hit") or {}).get("by") == side:
            break                              # it threw a punch: it was alive here
        if o["cost"][side] and end - o["t"] >= MIN_COUNT_SECONDS:
            stopped_by = o["t"]                # it was still being fought here
            break
        if o.get("immobile"):
            # A true multibot needs 60% of its weight down, and one of two equal
            # twins is 50%. Since both twins answer to the same description, the
            # only honest signal is the model saying more than one has stopped.
            if need > 1 and not PLURAL_RE.search(str(o.get("immobile_raw") or "")):
                continue
            swapped += o["immobile"] != side
            start, seen = i, seen + 1
    if need > 1:
        print(f"  {side} is a multibot: {need} machines must stop for a count "
              f"(rule 7.5.4, 60% of combined weight) — "
              f"{seen} frame(s) said more than one was down")
    if seen and swapped:
        print(f"  ! model named the other bot immobile on {swapped}/{seen} frames — "
              f"reading them as {side}, the side that loses", file=sys.stderr)
    if (stopped_by is not None and seen >= confirm
            and first_imm is not None and stopped_by >= first_imm):
        print(f"  {side} was flagged immobile from t={first_imm:.1f}s but still took a "
              f"blow at t={stopped_by:.1f}s — the count starts after it, not at the flag")
    return start if seen >= confirm else None


def count_out(obs: list[dict], loser: str, start: int, hp_left: int,
              step_seconds: float = 1.0) -> None:
    """Bleed the loser's remaining hp from `start` to the last observation.

    A knockout is a referee counting, not a blow. The bar should slide to zero
    across the count and land on 0 exactly at the frame the broadcast confirms the
    finish -- which is the last observation, since finish_at() truncates there.

    Marked `drain` rather than charged as damage, because deriveHits() in the
    frontend reads hp deltas and cannot otherwise tell a count-out from a hit: that
    is precisely how a 68-point phantom ended up winning BEST BLOW on a fight whose
    real biggest blow was 12.

    Stepped on ~step_seconds rather than every frame so the HUD gets a readable
    tick-down (its 400ms core tween carries the motion between steps) instead of 20
    events a second. Integer arithmetic, remainder on the last step, so it always
    lands exactly on 0 and hp never increases.
    """
    gap = obs[1]["t"] - obs[0]["t"] if len(obs) > 1 else step_seconds
    every = max(1, round(step_seconds / gap)) if gap > 0 else 1
    # A long count would otherwise emit an event per second for a minute, most of
    # them rounding to a 0-point step. Spread the same bar over MAX_DRAIN_STEPS so
    # every step actually moves the bar and the timeline stays readable.
    span = len(obs) - start
    every = max(every, -(-span // MAX_DRAIN_STEPS))
    steps = list(range(start, len(obs), every))
    if steps[-1] != len(obs) - 1:
        steps.append(len(obs) - 1)             # the finish frame always lands on 0

    # Remainder goes on the EARLIEST steps, not the last one. Piling it on the end
    # rebuilds a miniature version of the very thing this replaces: a final drop
    # bigger than every step before it, which reads as a blow.
    per, extra = divmod(hp_left, len(steps))
    for n, i in enumerate(steps):
        obs[i]["drain"] = {"side": loser, "amount": per + (1 if n < extra else 0)}


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
    if not clean and by not in dropped:
        # An incidental blow — a fire, a wall, a fall — has to name a bot that
        # actually lost hp, or the frontend can never match it to a damaged side.
        # The model does emit the other one ("Tombstone catches fire" credited to
        # MaDCaTTer), and validate() rightly rejects that. Coerce to the victim
        # while it is unambiguous; that is what self-inflicted damage means.
        # Left unclamped this crashed a finished 27-batch run at the last step.
        if len(dropped) != 1:
            return None
        by = dropped[0]
    weapon = raw.get("weapon")
    weapon = " ".join(str(weapon).split()[:MAX_WEAPON_WORDS]).lower()[:24] if weapon else ""
    out = {"by": by, "weapon": weapon or None, "clean": clean}
    at = clamp_at(raw.get("at"))
    if at:
        out["at"] = at            # never "at": None — the key is absent or it is a pair
    return out


def clamp_at(raw) -> list[float] | None:
    """A normalised [x, y] impact point, or None. REJECTS rather than clamps.

    Clamping is the wrong instinct here. A model that answers in pixels — [361, 95]
    on a 768x432 frame — would clamp to [1.0, 1.0], the bottom-right corner, which
    is a confident wrong answer that puts the crosshair on the HUD's own bar. Out
    of range means the model did not answer the question that was asked, and the
    honest fallback is the frontend's fixed position, which is merely approximate.
    """
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        return None
    try:
        x, y = float(raw[0]), float(raw[1])
    except (TypeError, ValueError):
        return None
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        return None
    return [round(x, 3), round(y, 3)]


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
            if c.get("kind") == "meta":      # "When and where to watch?" is never
                continue                     # a reaction to a hit
            ctext = words(c.get("text", ""))
            score = 2 * len(cap & ctext) + (2 if name and name <= ctext else 0)
            # A pre-fight prediction landing under a hit at t=52 reads wrong.
            # Ranked, not filtered: jackpot-copperhead's only usable comment is a
            # pre-fight one, and an empty HUD is worse than an early quote. Old
            # records carry no phase, so .get() is None and the score is
            # bit-identical to before.
            score += {"post": 3, "pre": -1}.get(c.get("phase"), 0)
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
        d = e.get("drain")
        if d is not None:
            assert d in SIDES, f"bad drain at {e['t']}"
            assert evs[i - 1][f"{d}_hp"] > e[f"{d}_hp"], f"drain with no drop at {e['t']}"
            # A drain event MAY carry a hit — the winner can take a blow while the
            # loser is being counted out. What it must never do is pass off the
            # count itself as a blow, so any hit here has to be explained by the
            # other side losing hp too.
            if "hit" in e:
                o = "left" if d == "right" else "right"
                assert evs[i - 1][f"{o}_hp"] > e[f"{o}_hp"], \
                    f"hit on a count-out with no other damage at {e['t']}"
        # normalize_hit() clamps model noise; these catch bugs in our own code.
        h = e.get("hit")
        if h is not None:
            # subset, not equality: "at" is OPTIONAL, so every timeline judged
            # before it existed still has to validate and still has to load
            assert isinstance(h, dict) and \
                {"by", "weapon", "clean"} <= set(h) <= {"by", "weapon", "clean", "at"}, \
                f"bad hit shape at {e['t']}"
            a = h.get("at")
            assert a is None or (isinstance(a, list) and len(a) == 2
                                 and all(isinstance(v, (int, float)) and 0 <= v <= 1
                                         for v in a)), f"bad hit.at at {e['t']}"
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
            ko: str | None = None, audio: bool = True,
            partial: bool = False, looks: dict | None = None,
            regrade: bool = False, stop: bool = False,
            verify_pass: bool = False) -> Path:
    name = Path(clip).stem
    frame_dir = ROOT / "frames" / name
    paths = sorted(frame_dir.glob("*.jpg"))
    if not paths:
        sys.exit(f"no frames in {frame_dir} — run extract_frames.py first")

    # The gap comes from what was ACTUALLY extracted, never from a constant here.
    # There is deliberately no --fps on this script: one flag that could disagree
    # with the frames on disk is all it takes to scale every timestamp in the
    # timeline by a constant, and a HUD that drifts off the video looks like a
    # frontend bug for hours before anyone suspects the extractor.
    spf = extract_frames.seconds_per_frame(name)
    batch_n = max(2, round(BATCH_SECONDS / spf))
    print(f"frames: {len(paths)} at {1 / spf:.3g} fps ({spf:.2f}s apart), "
          f"{batch_n} per call")

    talk_all = transcribe.load(name) if audio else []
    print(f"commentary: {len(talk_all)} segments" if talk_all else
          "commentary: none — judging on frames alone")

    prompt = (ROOT / "backend" / "prompt.txt").read_text()
    api = {"cli": lambda: None, "openai": openai_client, "api": client}[backend]()
    print(f"backend: {backend} " + {"cli": "(claude -p, uses your subscription)",
                                    "openai": f"({OPENAI_MODEL}, OpenAI API key)",
                                    "api": f"({MODEL}, Anthropic API key)"}[backend])

    def dispatch(sys_prompt, batch, ctx, recent, names, state, talk, spf) -> dict:
        """Pick the backend once. repass() runs the same batches a second time,
        and two copies of this ternary is how one of them drifts."""
        if backend == "cli":
            return ask_cli(sys_prompt, batch, ctx, recent, names, state, talk, spf)
        if backend == "openai":
            return ask_openai(api, sys_prompt, batch, ctx, recent, names, state,
                              talk, spf)
        return ask(api, sys_prompt, batch, ctx, recent, names, state, talk, spf)

    # Rounded once, at the source. The label, footer() and the by_t lookup all
    # round to one decimal, so quantising here makes that round-trip exact by
    # construction instead of by three independent roundings agreeing.
    stamped = [(round(i * spf, 1), p) for i, p in enumerate(paths)]
    # `look` carries each bot's appearance between calls. The model is stateless
    # per batch and the bots cross the arena constantly, so without this it
    # re-derives "left"/"right" from screen position every few frames and the
    # identities silently swap mid-fight. No hp here any more — the model emits
    # severity words and Python owns every number.
    #
    # --looks seeds it. Left empty, the ONE call that decides identity for the whole
    # fight -- batch 1 -- is also the only call with no appearance information in it:
    # --bots gives the model two names and their sides but never says which machine
    # is which. Whatever it guesses there is latched below and re-sent verbatim for
    # every later batch and every repass, and nothing downstream can detect that it
    # was wrong. Seeding is the entire fix; the latch already refuses to overwrite a
    # non-empty value, so a human description can never be replaced by a guess.
    state = {"left_look": "", "right_look": "", "pinned": bool(looks)}
    if looks:
        state.update({f"{k}_look": v for k, v in looks.items() if k in SIDES})
    names = {"left": None, "right": None}
    if bots:                       # a caller who knows the card anchors identity
        names.update({k: v for k, v in bots.items() if k in ("left", "right")})
    # Which extra machines this fight puts in the arena, from the committed roster.
    # Needs the card, so an unpinned run gets none — the same degradation as
    # --looks, and for the same reason: we do not know who is fighting yet.
    state["others"] = others_for(names)
    if state["others"]:
        print(f"  minibots in this fight: "
              + ", ".join(state["others"]) + " (not competitors)")
    obs: list[dict] = []
    recent: list[str] = []
    failed = 0                 # batches that never reached the model
    imm_tally: dict = {}       # how the immobile descriptions resolved, for one report

    for k in range(0, len(stamped), batch_n):
        batch = stamped[k:k + batch_n]
        ctx = stamped[k - 1] if k else None    # every judged frame gets a predecessor
        talk = transcribe.window(talk_all, batch[0][0], batch[-1][0])
        print(f"judging t={batch[0][0]:.0f}s..{batch[-1][0]:.0f}s "
              f"({k // batch_n + 1}/{-(-len(stamped) // batch_n)})"
              + (f" +{len(talk)} commentary" if talk else ""))
        # `names`, not `bots` — it is seeded from --bots when given and filled in
        # from the broadcast graphics otherwise, so the card gets pinned either way
        out = dispatch(prompt, batch, ctx, recent, names, state, talk, spf)
        failed += bool(out.get("failed"))

        for side in ("left", "right"):
            got = (out.get("bots") or {}).get(side)
            if got and not names[side]:
                names[side] = str(got)[:24]
        # First description wins — letting it drift per batch defeats the point. Taken
        # as a PAIR: latching the two sides independently let right_look come from a
        # later batch than left_look, so the two descriptions could be of different
        # moments, and "the other one" is exactly the comparison they exist to support.
        got = out.get("bots") or {}
        pair = {s: str(got.get(f"{s}_look") or "")[:60] for s in SIDES}
        if all(pair.values()) and not any(state[f"{s}_look"] for s in SIDES):
            state.update({f"{s}_look": pair[s] for s in SIDES})

        by_t = {round(float(f.get("t", -1)), 1): f for f in out.get("frames", [])}
        for t, _ in batch:
            f = by_t.get(round(t, 1)) or {}     # a dropped frame is simply "no damage"
            sev = {s: str(f.get(s, "none")).lower().strip() for s in ("left", "right")}
            for s in ("left", "right"):
                if sev[s] not in SEVERITY:
                    print(f"  ! unknown severity {sev[s]!r} at t={t:.0f}s, treating as none",
                          file=sys.stderr)
            cost = {s: SEVERITY.get(sev[s], 0) for s in ("left", "right")}
            # Three separate questions, deliberately three separate fields. They
            # used to be one: "finish" meant both "stopped moving" and "KNOCKOUT is
            # on screen", which are ~11s apart on manta-skorpios, and the pipeline
            # took whichever fired first as the end of the fight.
            fin = f.get("finish") if f.get("finish") in ("left", "right") else None
            # `immobile` is now a DESCRIPTION of the stopped machine; the side is
            # decided here, against the --looks anchor, not by the model
            imm = resolve_immobile(f.get("immobile"), state, names, imm_tally)
            rep = f.get("replay") is True
            cap = trim_caption(f.get("caption", ""))
            # The raw hit rides along untouched until hp exist. It cannot be
            # normalised yet: pay() may still zero this frame's cost, and a hit
            # with no hp drop behind it is not a hit.
            obs.append({"t": round(t, 1), "cost": cost, "finish": fin, "caption": cap,
                        "immobile": imm, "immobile_raw": f.get("immobile"),
                        "replay": rep, "raw_hit": f.get("hit")})
            if cost["left"] or cost["right"]:
                recent.append(f"{t:.0f}s left {sev['left']}, right {sev['right']}"
                              + (f" — {cap}" if cap else ""))
                del recent[:-2]                 # last two only; keep the footer short

    if imm_tally:
        bits = ", ".join(f"{v} {k}" for k, v in sorted(imm_tally.items()))
        pin = "pinned --looks" if state.get("pinned") else "the model's own latched looks"
        print(f"  immobile: {bits} (matched against {pin})")

    # A replay is a blow that was already judged live. Must run before merge_blows()
    # and before the shutout check, so neither is fed damage that never happened.
    dropped = drop_replays(obs)
    if dropped:
        print(f"  {dropped} replay frame(s) scored no damage — already judged live")

    # One blow rated on three consecutive frames is still one blow. Must run
    # before the finish-frame handling below, or a merged-away frame could take
    # the finishing frame's place.
    merge_blows(obs)

    # Re-grade AFTER merge_blows, so each physical blow is re-graded exactly once
    # rather than once per impact/debris/recoil frame, and BEFORE the shutout check
    # below, which reads the totals this can change: a bot whose one real blow was
    # under-graded clears SHUTOUT_FLOOR here and skips a whole-clip repass().
    if regrade:
        moved = relook(dispatch, prompt, stamped, obs, spf, names, state)
        print(f"  re-look moved {moved} rung(s)")
        merge_blows(obs)      # a promotion can create a new maximum in a window

    # A bot the first pass never scored gets one focused look. Checked before the
    # KO truncation so a shutout on the winner is judged over the whole fight.
    took = {s: sum(o["cost"][s] for o in obs) for s in SIDES}
    for side in SIDES:
        if took[side] >= SHUTOUT_FLOOR:
            continue
        print(f"  ! {names.get(side) or side} ({side}) took {took[side]} damage in the "
              f"whole fight — re-judging that bot on its own", file=sys.stderr)
        extra = repass(dispatch, prompt, stamped, batch_n, spf, talk_all,
                       names, state, side)
        by_t = {o["t"]: o for o in obs}
        for t, got in extra.items():
            o = by_t.get(t)
            if not o:
                continue
            o["cost"][side] = max(o["cost"][side], got["cost"])   # only ever adds
            if got["caption"] and not o["caption"]:
                o["caption"] = got["caption"]
            if got["raw_hit"] and not o.get("raw_hit"):
                o["raw_hit"] = got["raw_hit"]
        merge_blows(obs)          # the new ratings need collapsing too
        print(f"  second pass found {sum(o['cost'][side] for o in obs)} damage "
              f"for {names.get(side) or side}")

    # WHO, and whether a blow happened at all. This runs AFTER the shutout rescue,
    # and the order is load-bearing: repass() exists to rescue a bot that was never
    # scored and it only ever adds (max() per frame), so a deletion pass in front of
    # it gets undone wholesale. Run the other way round it did exactly that — verify
    # correctly left Manta having taken 0 damage, the shutout check read that zero as
    # a mis-read, and repass put 62 back, inverting the fight.
    if verify_pass:
        n = verify(dispatch, prompt, stamped, obs, spf, names, state)
        print(f"  verify changed {n} blow(s)")
        merge_blows(obs)

    # A dropped blow here also takes a false "it was still driving" signal out of
    # immobile_from()'s walk, which is why it runs before the walk and not after.
    n = drop_downed_hits(obs, names)
    if n:
        print(f"  dropped {n} hit(s) credited to a machine that had stopped")

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
        if ko and took[ko] < took["left" if ko == "right" else "right"]:
            # --ko silences the damage cross-check below, which is the only thing that
            # could ever notice the model had the two machines the wrong way round: an
            # inverted run is perfectly self-consistent, it just has the winner taking
            # the beating. Say so rather than pinning the loser over the top in silence.
            print(f"  ! {names.get(ko) or ko} is pinned as the loser but took LESS "
                  f"damage ({took}) — identity may be inverted; check --looks",
                  file=sys.stderr)
        elif not ko and took[loser] < took[other]:
            print(f"  ! KO flagged on {loser}, but {other} took more damage "
                  f"({took}) — going with {other}", file=sys.stderr)
            loser = other
        obs[-1]["cost"][loser] = 0     # the finishing blow is free — it is forced to
                                       # 0 below, so charging it would spend budget
                                       # that belongs to the fight

    # The loser is settled but the frames have not been read for immobility yet —
    # the only point in the run where naming the loser to the model is legitimate.
    if stop and loser:
        n = stop_pass(dispatch, prompt, stamped, obs, loser, names, state, spf, talk_all)
        print(f"  stop pass set {n} frame(s) of immobility for "
              f"{names.get(loser) or loser}")

    # A knockout is a referee counting, not a blow. Find the moment the loser
    # actually stopped; from there the count owns the bar, so those frames are
    # taken out of pay()'s auction before it runs.
    drain_from = (immobile_from(obs, loser, need=machines_needed(names.get(loser)))
                  if loser else None)
    if drain_from is not None:
        # A count is a bounded thing — ten seconds, plus a beat for the graphic. A
        # longer one means immobility was called while the bot was still fighting,
        # and draining then bleeds a live machine. On madcatter-tombstone the model
        # called Tombstone immobile at t=45 and the commentary has it "back into the
        # fight" at t=56 with its weapon dying at t=60; clamping to the last 15s puts
        # the count where the fight actually ended.
        floor = obs[-1]["t"] - MAX_COUNT_SECONDS
        if obs[drain_from]["t"] < floor:
            was = obs[drain_from]["t"]
            drain_from = next(i for i, o in enumerate(obs) if o["t"] >= floor)
            print(f"  ! immobility called at t={was:.1f}s, "
                  f"{obs[-1]['t'] - was:.0f}s before the finish — too long for a count, "
                  f"clamping to t={obs[drain_from]['t']:.1f}s", file=sys.stderr)
        for o in obs[drain_from:]:
            o["cost"][loser] = 0
    # More frames means more candidate blows against the same absolute budget, so
    # these two lines are how you tell a busier fight from an inflated one without
    # re-reading the whole timeline. The budgets themselves stay put: merge_blows()
    # keeps the number of DISTINCT blows fps-invariant, which is what makes 70/55
    # keep meaning what they meant at 0.5 fps. Raising them to fit more hits is
    # arithmetically the same as having no budget, and that is the drip.
    print(f"  raw damage before budget: "
          f"{ {s: sum(o['cost'][s] for o in obs) for s in SIDES} } "
          f"(budgets {LIVE_BUDGET} live / {KO_BUDGET} ko)")
    for side in ("left", "right"):
        pay(obs, side, KO_BUDGET if side == loser else LIVE_BUDGET)
    for side in SIDES:
        if not sum(o["cost"][side] for o in obs):
            print(f"  ! SHUTOUT: {names.get(side) or side} takes no damage in the "
                  f"final timeline — check the frames before shipping this",
                  file=sys.stderr)

    # Schedule the count-out now that pay() has settled what damage actually lands,
    # so the drain bleeds exactly the bar the fight left standing.
    if loser and drain_from is not None:
        hp_left = max(0, 100 - sum(o["cost"][loser] for o in obs[:drain_from]))
        count_out(obs, loser, drain_from, hp_left)
        who = names.get(loser) or loser
        obs[drain_from]["caption"] = (obs[drain_from]["caption"]
                                      or trim_caption(f"{who} immobile, count begins"))
        print(f"  {who} immobile from t={obs[drain_from]['t']:.1f}s — {hp_left} hp bled "
              f"over the count to t={obs[-1]['t']:.1f}s")
    elif loser:
        print("  ! never saw the loser stop moving — the KO falls back to a single "
              "drop at the finish frame", file=sys.stderr)

    # hp at last, and only now can a hit be judged: normalize_hit() drops anything
    # with no hp drop behind it, so it has to see the damage the timeline will
    # actually show — after pay() has zeroed the surplus, not before.
    hp, observations, last = {"left": 100, "right": 100}, [], len(obs) - 1
    for i, o in enumerate(obs):
        before = dict(hp)
        for s in SIDES:
            hp[s] = max(0, hp[s] - o["cost"][s])
        # Judge the hit against the DAMAGE change only, before the count-out moves
        # the bar. A drain is nobody's blow, and normalize_hit() would happily
        # attribute one to whichever bot is still standing.
        hit = normalize_hit(o.get("raw_hit"), before, hp)
        drain = o.get("drain")
        if drain and drain["amount"]:
            hp[drain["side"]] = max(0, hp[drain["side"]] - drain["amount"])
        elif loser and drain_from is None and i == last:
            hp[loser] = 0            # fallback: the model never saw it stop, so the
                                     # finish frame still has to reach zero
        rec = {"t": o["t"], "left_hp": hp["left"], "right_hp": hp["right"],
               "caption": o["caption"]}
        if drain and drain["amount"]:
            rec["drain"] = drain["side"]
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
    # A batch that never reached the model comes back empty, which is indistinguishable
    # from a quiet stretch of fight — so a run that lost its API key half way through
    # still produces a plausible, validating, WRONG timeline and writes it over a good
    # one. That happened: 5 batches 401'd on madcatter-tombstone and the result was a
    # 43-second fight with no knockout. Refuse the overwrite instead.
    if failed and out_path.exists() and not partial:
        sys.exit(f"\n{failed} batch(es) never reached the model, so this timeline has "
                 f"holes in it.\nRefusing to overwrite {out_path.name} — fix the "
                 f"backend and re-run, or pass --partial to write it anyway.")
    if failed:
        print(f"  ! {failed} batch(es) failed — this timeline has holes in it",
              file=sys.stderr)
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(timeline, indent=2) + "\n")
    print(f"wrote {out_path} — {len(events)} events, "
          f"{timeline['bots']['left']} vs {timeline['bots']['right']}")
    return out_path


def rejoin(clip: str, bots: dict | None = None) -> Path:
    """Re-run ONLY the comment join against an existing timeline.

    No frames, no model call, no money, about a second. The comment pool is the
    only input to join_comments(), and the hp curve, captions, hits and KO are
    already settled — so a better scrape reaches the committed timelines without
    paying for a re-judge. A re-judge is real money and 15-30 minutes, and it
    would re-roll hp numbers that have already been checked by eye.

    Idempotent: the same pool always produces the same result, because every
    previous fan_comment is dropped first.
    """
    name = Path(clip).stem
    path = ROOT / "timelines" / f"{name}.json"
    if not path.exists():
        sys.exit(f"no {path} — run a full judge first")
    timeline = json.loads(path.read_text())
    card = bots or timeline.get("bots") or {}
    for ev in timeline["events"]:
        ev.pop("fan_comment", None)
    comments_file = ROOT / "comments" / f"{name}.json"
    comments = json.loads(comments_file.read_text()) if comments_file.exists() else []
    if not comments:
        sys.exit(f"no {comments_file} — nothing to join")
    join_comments(timeline["events"], comments, card)
    # Deliberately NOT name_captions(): the captions are already named, and a
    # second substitution pass could double-substitute.
    validate(timeline)
    path.write_text(json.dumps(timeline, indent=2) + "\n")
    joined = sum(1 for e in timeline["events"] if e.get("fan_comment"))
    print(f"rejoined {path} — {joined} fan comments across {len(timeline['events'])} events")
    return path


if __name__ == "__main__":
    argv, backend, bots, ko, looks = sys.argv[1:], "api", None, None, None
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
    if "--looks" in argv:                   # pins WHICH MACHINE is which, where --bots
        i = argv.index("--looks")           # only pins the names. Batch 1 decides
        pair = argv[i + 1] if i + 1 < len(argv) else ""   # identity for the whole run
        del argv[i:i + 2]                                 # and has nothing else to go on
        # pipe, not comma: a useful description has commas in it
        left, _, right = pair.partition("|")
        if not (left.strip() and right.strip()):
            sys.exit('--looks takes "left description|right description"')
        looks = {"left": left.strip(), "right": right.strip()}
    if "--ko" in argv:                      # for a clip someone has watched: the
        i = argv.index("--ko")              # finish frame is often a crowd shot, and
        ko = argv[i + 1] if i + 1 < len(argv) else ""   # the model guesses the side
        del argv[i:i + 2]
        if ko not in ("left", "right"):
            sys.exit("--ko must be 'left' or 'right'")
    if backend not in ("api", "cli", "openai"):
        sys.exit("--backend must be 'api', 'cli' or 'openai'")
    positional = [a for a in argv if not a.startswith("-")]
    if not positional:
        sys.exit(__doc__)
    if "--rejoin" in argv:                  # comment pool only; no frames, no spend
        rejoin(positional[0], bots)
        sys.exit(0)
    analyze(positional[0], backend=backend, bots=bots, ko=ko,
            audio="--no-audio" not in argv, partial="--partial" in argv,
            looks=looks, regrade="--regrade" in argv, stop="--stop-pass" in argv,
            verify_pass="--verify" in argv)
