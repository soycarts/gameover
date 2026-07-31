#!/usr/bin/env python3
"""transcribe.py <clip> — broadcast commentary -> transcripts/<clip>.json

    python backend/transcribe.py manta-skorpios
    python backend/transcribe.py manta-skorpios --source openai   # needs audio API access

The commentary is the best evidence in the clip and the pipeline used to throw it
away. On manta-skorpios the captions say, in order: "A BIG HIT BY MANTA RIGHT OUT
OF THE GATE" (t=1.8), "Manta got hit by that huge drum spinner" (t=4.6), and
"Dream is already over for Scorpios ... in just 24 seconds" (t=23.6). That middle
line is Skorpios' only real blow — the exact hit the vision judge missed and the
reason the timeline reads as a shutout. The last line settles who lost, which the
frames cannot: the KNOCKOUT graphic lands over a crowd shot with no bot in it.

Two sources, same output contract:

  subs   (default) YouTube auto-captions via yt-dlp. Free, no key, no new
         dependency, already timestamped. Needs the clip's source URL and cut
         offset, recorded by ingest.py in clips/<clip>.source.json.
  openai Whisper. Better text, but it needs an OPENAI_API_KEY whose project has
         audio access — this repo's key does not (403 model_not_found on
         whisper-1; the project carries five text/vision models and no audio).
         Anthropic has no speech-to-text API at all, so there is no third option.

Idempotent: the transcript is cached, so a re-judge costs nothing. --force to redo.
"""
import difflib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STT_MODEL = "whisper-1"      # the only OpenAI model returning segment timestamps
SOURCE_SUFFIX = ".source.json"
LEAD = 1.0                   # commentary that sets a moment up
LAG = 1.5                    # ... and the reaction, which lands AFTER the blow
MAX_CUE = 2.5                # a spoken caption line; longer is a pause, not speech


def transcript_path(name: str) -> Path:
    return ROOT / "transcripts" / f"{name}.json"


def source_path(name: str) -> Path:
    return ROOT / "clips" / f"{name}{SOURCE_SUFFIX}"


def load(name: str) -> list[dict]:
    """Cached segments for a clip, or [] when there is no transcript.

    Every caller degrades to "no commentary": a clip with no source record, no
    captions or no key has to judge exactly as it did before.
    """
    try:
        data = json.loads(transcript_path(name).read_text())
    except (OSError, ValueError):
        return []
    segs = data.get("segments")
    return segs if isinstance(segs, list) else []


# ------------------------------------------------------- YouTube auto-captions
def tool(name: str) -> str:
    """Resolve a helper from the running interpreter's bin dir first — yt-dlp is
    in .venv/bin and not on PATH. Same trick as ingest.tool()."""
    local = Path(sys.executable).parent / name
    return str(local) if local.exists() else name


def fetch_subs(url: str, force: bool = False) -> Path | None:
    """Whole-video auto-captions, cached. Three fights come out of one video, so
    the 2nd and 3rd cost no network. Dotted dir: serve.py 404s it."""
    vid = re.search(r"(?:v=|youtu\.be/|/shorts/)([A-Za-z0-9_-]{6,})", url)
    stem = vid.group(1) if vid else re.sub(r"\W+", "-", url)[-32:]
    cache = ROOT / "transcripts" / ".subs"
    out = cache / f"{stem}.en.json3"
    if out.exists() and not force:
        return out
    cache.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(
        [tool("yt-dlp"), "--write-auto-sub", "--sub-lang", "en",
         "--sub-format", "json3", "--skip-download",
         "-o", str(cache / f"{stem}.%(ext)s"), url],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if not out.exists():
        print(f"  ! no auto-captions for {url}: {done.stderr.decode()[-200:]}",
              file=sys.stderr)
        return None
    return out


def parse_json3(path: Path) -> list[dict]:
    """YouTube json3 -> segments in SOURCE-video time."""
    try:
        events = json.loads(path.read_text()).get("events", [])
    except (OSError, ValueError):
        return []
    segs = []
    for e in events:
        if "segs" not in e:
            continue
        text = " ".join("".join(s.get("utf8", "") for s in e["segs"]).split())
        # ">>" is the captioner's speaker-change marker, not speech.
        text = text.replace(">>", " ").strip()
        if not text:
            continue
        start = e.get("tStartMs", 0) / 1000.0
        segs.append({"start": round(start, 2),
                     "end": round(start + e.get("dDurationMs", 0) / 1000.0, 2),
                     "text": text})
    return segs


def tidy(segs: list[dict]) -> list[dict]:
    """Make rolling captions disjoint.

    YouTube's auto-captions roll: each cue's dDurationMs covers the time the text
    stays on screen, which overlaps the next two or three cues. Left alone, a
    1.5s lookahead window drags in ~8s of text and the timestamps stop meaning
    anything. Ending each cue where the next one starts restores a usable
    line-to-moment mapping.

    Capped at MAX_CUE as well, because ending-where-the-next-begins overshoots
    whenever the commentators pause: a two-second sentence inherits the whole
    silence after it and reads as a claim about four seconds of fight. On
    manta-skorpios "huge drum spinner" stretched to 4s that way, and the judge
    scored damage off it on three separate frames.
    """
    segs = sorted(segs, key=lambda s: s["start"])
    for a, b in zip(segs, segs[1:]):
        a["end"] = min(a["end"], b["start"])
    for s in segs:
        s["end"] = round(min(s["end"], s["start"] + MAX_CUE), 2)
    return [s for s in segs if s["end"] > s["start"]]


def cut(segs: list[dict], start: float, duration: float) -> list[dict]:
    """Source-video time -> clip time. ingest.py cuts a window out of a long
    compilation, so a clip's t=0 is `start` seconds into the source.

    Callers pass the cut's REAL origin (`t0` in source.json), not the `--start`
    that was asked for: `-ss` before `-i` with `-c copy` snaps back to the
    nearest keyframe, so the two differ by up to a keyframe interval.
    """
    out = []
    for s in segs:
        if s["end"] < start or s["start"] > start + duration:
            continue
        # clamp to the clip: a cue straddling t=0 is the ring announcer, not a
        # line about a blow, and a negative timestamp confuses the window maths
        a, b = max(0.0, s["start"] - start), min(duration, s["end"] - start)
        if b <= a:
            continue
        out.append({"start": round(a, 2), "end": round(b, 2), "text": s["text"]})
    return out


# --------------------------------------------------------------- OpenAI Whisper
def openai_whisper(clip_src: Path, hint: str) -> list[dict]:
    """--- ADAPTER: OpenAI Whisper -------------------------------------------
    whisper-1 specifically: it is the only model that returns segment timestamps
    (response_format="verbose_json"), and the gpt-4o-transcribe family is
    json/text only. Without timestamps commentary cannot be matched to a frame,
    which is the whole point.
    """
    audio = ROOT / "transcripts" / ".audio" / f"{clip_src.stem}.mp3"
    audio.parent.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(
        ["ffmpeg", "-y", "-i", str(clip_src), "-vn", "-ac", "1",
         "-ar", "16000", "-b:a", "32k", str(audio)],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if done.returncode != 0 or not audio.exists():
        print(f"  ! could not extract audio: {done.stderr.decode()[-200:]}",
              file=sys.stderr)
        return []

    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("pip install -r backend/requirements.txt")
    key = config.openai_key()
    if not key:
        sys.exit("no OPENAI_API_KEY in .env or the environment")

    with audio.open("rb") as fh:
        resp = OpenAI(api_key=key).audio.transcriptions.create(
            model=STT_MODEL, file=fh, language="en",
            response_format="verbose_json", timestamp_granularities=["segment"],
            prompt=f"Live robot combat commentary. Competitors: {hint}.")
    return [{"start": round(float(s.start), 2), "end": round(float(s.end), 2),
             "text": " ".join(str(s.text).split())}
            for s in (getattr(resp, "segments", None) or []) if str(s.text).strip()]


# ------------------------------------------------------------------------ names
def fix_names(segs: list[dict], names: list[str]) -> int:
    """Snap near-misses of the pinned bot names back to the real spelling.

    ASR mangles proper nouns consistently — the auto-captions render Skorpios as
    "Scorpios" every single time. identity_note() pins the card on exact names,
    so an unfixed transcript names a robot that is not in the fight, which is the
    same class of error as captioning a sponsor decal.
    """
    if not names:
        return 0
    # match against the despaced name: the captions write MaDCaTTer as two words
    # ("Mad Catter"), so a single-token comparison never fires on it
    keys = [re.sub(r"\W+", "", n).lower() for n in names]
    strip = ".,!?;:'\""
    fixed = 0

    for s in segs:
        words = s["text"].split()
        out, i = [], 0
        while i < len(words):
            span = 0
            # try the two-word form first: on its own "Mad" matches nothing and
            # "Catter" would be rewritten alone, stranding a "Mad" beside it
            for n in (2, 1):
                if i + n > len(words):
                    continue
                core = "".join(w.strip(strip) for w in words[i:i + n])
                if core and difflib.get_close_matches(core.lower(), keys, 1, 0.85):
                    span = n
                    canon = names[keys.index(
                        difflib.get_close_matches(core.lower(), keys, 1, 0.85)[0])]
                    break
            if not span:
                out.append(words[i])
                i += 1
                continue
            last = words[i + span - 1]
            tail = last[len(last.rstrip(strip)):]        # keep trailing punctuation
            # compare against what is actually written: "Mad Catter" despaces to
            # an exact key match yet still needs rewriting to "MaDCaTTer"
            if " ".join(words[i:i + span]) != canon + tail:
                fixed += 1
            out.append(canon + tail)
            i += span
        s["text"] = " ".join(out)
    return fixed


# --------------------------------------------------------------------- garbles
# Weapon nouns worth owning. Kept small on purpose: a word only earns a place
# here if a bot can plausibly be described as CARRYING it.
WEAPON_WORDS = {"drum", "spinner", "blade", "bar", "hammer", "flipper", "saw",
                "saws", "fork", "forks", "disc", "axe", "crusher", "wedge",
                "lifter", "clamp", "beater"}
# "<bot> ... got/was/gets hit" and friends. Deliberately narrow: it has to be
# the PASSIVE form, because the active one ("Manta hit that") is correct English
# and correct attribution.
HURT_RE = (r"\b{name}\b[^.?!]{{0,24}}?\b(?:got|gets|getting|was|is|been|being)"
           r"\s+(?:\w+\s+){{0,2}}?"
           r"(?:hit|hurt|caught|smashed|nailed|clobbered|rocked|walloped)\b")


def weapon_owners(looks: dict | None) -> dict:
    """weapon word -> the side whose machine carries it, from the pinned --looks.

    Words in BOTH descriptions are discounted to nothing, exactly as
    match_look() does: both machines here are a "wedge", so keeping it would
    make every wedge line ambiguous and the rule would never fire safely.
    """
    if not looks:
        return {}
    bags = {s: set(re.findall(r"[a-z]+", (looks.get(s) or "").lower())) & WEAPON_WORDS
            for s in ("left", "right")}
    shared = bags["left"] & bags["right"]
    return {w: s for s in ("left", "right") for w in bags[s] - shared}


def drop_own_weapon_garbles(segs: list[dict], bots: dict | None,
                            looks: dict | None) -> int:
    """Drop cues claiming a bot was damaged by a weapon that bot carries.

    These are auto-captions and they mishear constantly. The one that has now
    cost two runs is "Manta got hit by that huge drum spinner" — the drum is
    MANTA'S, so the real line is "got him with". Read literally it says the
    eventual winner took the damage, and the judge believed it: 20 hp across
    three frames, twice, with captions inverting the attribution on every one.

    A weapon belongs to the bot carrying it, so "X was hit by X's weapon" is a
    contradiction in terms and the transcription is wrong. Dropping is honest
    where rewriting is not: we know the line is garbled, we do not know what was
    actually said, and the frames still show the blow. The weapon half of the
    sentence usually lands in the NEXT cue, so the test spans the pair.
    """
    owner = weapon_owners(looks)
    names = {(bots or {}).get(s): s for s in ("left", "right") if (bots or {}).get(s)}
    if not (owner and names):
        return 0
    keep, dropped = [], 0
    for i, seg in enumerate(segs):
        text = seg["text"].lower()
        nxt = segs[i + 1]["text"].lower() if i + 1 < len(segs) else ""
        hurt = next((side for nm, side in names.items()
                     if re.search(HURT_RE.format(name=re.escape(nm.lower())), text)), None)
        if hurt and any(owner.get(w) == hurt
                        for w in owner if re.search(rf"\b{w}\b", text + " " + nxt)):
            print(f"  ~ dropped garbled cue at {seg['start']:.1f}s: {seg['text']!r} — "
                  f"says {bots[hurt]} was hit by its own weapon", file=sys.stderr)
            dropped += 1
            continue
        keep.append(seg)
    segs[:] = keep
    return dropped


# ------------------------------------------------------------------------- main
def transcribe(clip: str, bots: dict | None = None, source: str = "subs",
               force: bool = False, looks: dict | None = None) -> list[dict]:
    name = Path(clip).stem
    out = transcript_path(name)
    if out.exists() and not force:
        segs = load(name)
        print(f"{len(segs)} commentary segments already in {out} (--force to redo)")
        return segs

    src = ROOT / "clips" / (clip if clip.endswith(".mp4") else clip + ".mp4")
    names = [v for v in (bots or {}).values() if v]

    if source == "openai":
        if not src.exists():
            sys.exit(f"no such clip: {src}")
        segs = openai_whisper(src, ", ".join(names) or "two robots")
    else:
        try:
            rec = json.loads(source_path(name).read_text())
        except (OSError, ValueError):
            print(f"  ! no {source_path(name).name} — cannot fetch captions without "
                  f"the source URL and cut offset. Judging will fall back to "
                  f"frames alone.", file=sys.stderr)
            return []
        subs = fetch_subs(rec["url"], force=force)
        if not subs:
            return []
        # t0/span are where the cut LANDED, start/duration what ingest asked for.
        # They differ because -ss with -c copy snaps back to a keyframe, and
        # mapping from `start` put every caption ~1s early. Old source.json files
        # carry neither key, so they fall back to the previous behaviour exactly.
        segs = cut(tidy(parse_json3(subs)),
                   float(rec.get("t0", rec.get("start", 0))),
                   float(rec.get("span", rec.get("duration", 1e9))))

    segs.sort(key=lambda s: s["start"])
    n = fix_names(segs, names)
    if n:
        print(f"  snapped {n} mangled name(s) to {names}")
    # after fix_names, so the bot names in a cue are already canonical
    g = drop_own_weapon_garbles(segs, bots, looks)
    if g:
        print(f"  dropped {g} garbled cue(s) — a bot cannot be hit by its own weapon")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"clip": src.name, "source": source, "segments": segs}, indent=2) + "\n")
    print(f"transcribed {len(segs)} segments -> {out}")

    # A pinned name the commentary never says is the signal that --bots is wrong,
    # and a broken --bots silently disables the competitor-pinning header.
    blob = " ".join(s["text"] for s in segs).lower()
    for nm in names:
        if nm.lower() not in blob:
            print(f"  ! commentary never says {nm!r} — check --bots", file=sys.stderr)
    return segs


def window(segments: list[dict], t0: float, t1: float) -> list[dict]:
    """Commentary overlapping ONE batch's frames.

    Deliberately a window and never the whole transcript: hand the judge the full
    commentary and it hears the knockout call before the fight gets there, then
    back-fills the earlier frames to match an ending it has not seen.

    Asymmetric on purpose. A commentator reacts about a second AFTER the blow —
    "Manta got hit by that huge drum spinner" lands at t=4.6 for an impact around
    t=4 — so the useful line sits later than the frame. LAG is capped at 1.5s:
    enough to catch the reaction, short enough that the only future it can leak
    is a second and a half of it. The KO decision does not run on this anyway;
    finish_at()'s 70% window and --ko own that.
    """
    lo, hi = t0 - LEAD, t1 + LAG
    return [s for s in segments if s["end"] >= lo and s["start"] <= hi]


if __name__ == "__main__":
    argv = sys.argv[1:]
    bots, source = None, "subs"
    if "--bots" in argv:
        i = argv.index("--bots")
        left, _, right = (argv[i + 1] if i + 1 < len(argv) else "").partition(",")
        if not left.strip() or not right.strip():
            sys.exit('--bots takes "Left,Right"')
        bots = {"left": left.strip(), "right": right.strip()}
        del argv[i:i + 2]
    if "--source" in argv:
        i = argv.index("--source")
        source = argv[i + 1] if i + 1 < len(argv) else ""
        if source not in ("subs", "openai"):
            sys.exit("--source must be 'subs' or 'openai'")
        del argv[i:i + 2]
    # same spelling as analyze.py's --looks; it is what owns each machine's weapon,
    # and without it drop_own_weapon_garbles() cannot fire
    looks = None
    if "--looks" in argv:
        i = argv.index("--looks")
        left, _, right = (argv[i + 1] if i + 1 < len(argv) else "").partition("|")
        if not left.strip() or not right.strip():
            sys.exit('--looks takes "left desc|right desc"')
        looks = {"left": left.strip(), "right": right.strip()}
        del argv[i:i + 2]
    args = [a for a in argv if not a.startswith("-")]
    if not args:
        sys.exit(__doc__)
    transcribe(args[0], bots=bots, source=source, force="--force" in argv, looks=looks)
