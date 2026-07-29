#!/usr/bin/env python3
"""crowd.py — what the crowd said: safety gates, matchup routing, prediction labels.

Everything about turning a raw Reddit thread into showable, attributable,
per-matchup fan commentary lives here. scrape_comments.py owns Bright Data,
analyze.py owns the vision judge, and this module owns the text in between.

The two deterministic gates CLAUDE.md names are both here — is_showable() (drops
explicit language, deleted bodies, junk lengths) and names_a_rival() (a comment
naming a bot that is not in THIS fight). scrape_comments.py re-exports both, so
their documented home still resolves.

The one model call in this file, classify(), happens at SCRAPE time and is cached
into comments/<slug>.json. That is deliberate: a re-judge of the video is real
money and 15-30 minutes, and the crowd's opinion has nothing to do with the
frames. Everything downstream of the labels — the tallies, the percentages, the
"did the crowd call it" verdict — is plain counting, in Python and in the HUD.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

# --------------------------------------------------------------- safety gates
# Real comment threads are not stage-safe. The MaD CaTTer thread, for one, is a
# sustained sexual joke — fine on Reddit, not fine burned into a clip shown to
# judges or submitted to BattleBots. Filtering happens in Python so the same
# scrape always yields the same safe set.
DROP_EXACT = {"[deleted]", "[removed]", "deleted", "removed"}
DROP_WORDS = re.compile(
    r"\b(fuck\w*|shit\w*|cunt\w*|cock|dick|tits|porn\w*|sex\w*|rape\w*|nsfw|"
    r"humping|furries|scalies|slut\w*|whore|nigg\w+|fag\w*|retard\w*)\b|"
    r"(?:that|my|the)\s+hole\b",
    re.I)
MIN_LEN, MAX_LEN = 12, 180


def is_showable(text: str) -> bool:
    """Deterministic gate for anything that will appear on screen."""
    t = text.strip()
    if t.lower() in DROP_EXACT or not (MIN_LEN <= len(t) <= MAX_LEN):
        return False
    if DROP_WORDS.search(t):
        return False
    return not t.lower().startswith(("http://", "https://", "www."))


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


def bot_key(name: str) -> str:
    """Comparable form of a bot name. "MaDCaTTer", "Mad Catter" and "madcatter"
    are one robot; the timeline, the Reddit thread and the model all spell it
    differently. The frontend has a byte-identical copy of this — keep them so."""
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def mentions(text: str, bot: str) -> bool:
    """Word-boundary match with a trailing s / possessive, so "Manta," and
    "Mad Catter's" are caught — an endswith/space check misses trailing
    punctuation, which is exactly how a Manta comment first slipped onto a
    Copperhead hit.

    BOTH sides are lowercased. KNOWN_BOTS is all lowercase so this looked fine,
    but callers also pass display names straight off the card ("Skorpios",
    "MaDCaTTer") — those matched nothing at all, which silently disarmed the
    flip check on the model's picks.
    """
    return bool(re.search(rf"\b{re.escape(str(bot).lower())}(?:'s|’s|s)?\b",
                          " ".join(text.lower().split())))


def _is_ours(bot: str, ours_k: list[str]) -> bool:
    # "madcatter" and "mad catter" both count as ours if either name contains it
    k = bot_key(bot)
    return any(k in o or o in k for o in ours_k)


def names_a_rival(text: str, card: dict) -> bool:
    """True if the comment names a known bot that is not in this fight."""
    ours_k = [bot_key(n) for n in (card.get("left", ""), card.get("right", "")) if n]
    return any(mentions(text, bot) for bot in KNOWN_BOTS if not _is_ours(bot, ours_k))


# ------------------------------------------------------- multi-matchup routing
PARA = re.compile(r"\n\s*\n|\n")
SENT = re.compile(r"(?<=[.!?…])\s+|\s*[;–—]\s+")
MAX_SENTS = 12               # window generation is O(n^2); a 12-sentence cap is 78


def _windows(text: str) -> list[str]:
    """Candidate spans of a comment, LONGEST FIRST: the whole thing, each
    paragraph, then every run of consecutive sentences inside a paragraph."""
    paras = [" ".join(p.split()) for p in PARA.split(text) if p.strip()]
    out = [" ".join(text.split())]
    if len(paras) > 1:
        out += paras
    for p in paras:
        s = [x for x in SENT.split(p) if x.strip()][:MAX_SENTS]
        out += [" ".join(s[i:j]) for i in range(len(s)) for j in range(i + 1, len(s) + 1)]
    seen: set[str] = set()
    return [w for w in sorted(out, key=len, reverse=True)
            if w and not (w in seen or seen.add(w))]


def focus_segment(text: str, ours: list[str]) -> tuple[str | None, bool]:
    """The part of a comment that is about THIS fight, and whether it still
    names a rival. Returns (segment, rival); (None, False) means unusable.

    A fight-card comment covers the WHOLE card. Ellindsey's runs a paragraph per
    matchup over 900 characters, so MAX_LEN drops it whole; "My money is on
    Copperhead, Manta, and Madcatter" names six robots in one sentence, so
    names_a_rival() drops it whole. Those are the two best comments in the
    thread. Segmenting changes the UNIT being filtered from "comment" to "best
    span of a comment" — it does NOT loosen either gate. MAX_LEN is still 180 and
    is_showable() is unchanged.
    """
    if not text:
        return None, False
    body = " ".join(text.split())
    # The profanity gate applies to the WHOLE body, always, and before anything
    # else. Otherwise segmenting would let one clean sentence out of an unusable
    # comment onto the screen, which is the exact thing is_showable() exists to
    # prevent. Strictly stricter than filtering whole comments; looser only on
    # length. Do not reorder these checks.
    if body.lower() in DROP_EXACT or DROP_WORDS.search(body):
        return None, False

    ours_k = [bot_key(o) for o in ours if o]
    fallback = None
    for w in _windows(text):
        if not is_showable(w):
            continue
        named = {b for b in KNOWN_BOTS if mentions(w, b)}
        rivals = {b for b in named if not _is_ours(b, ours_k)}
        if ours_k and not (named - rivals):
            continue                     # names none of ours — not about this fight
        if not rivals:                   # windows are longest-first, so this is
            return w, False              # the largest clean span there is
        if fallback is None:
            fallback = w
    return fallback, fallback is not None


# ------------------------------------------------- author / score / thread ids
# Candidate field names, tried in order — the same idiom as TEXT_FIELDS and
# URL_FIELDS in scrape_comments.py. The first entry of each is CONFIRMED against
# a live gd_lvzdpsdlw09j6t702 row, whose full key set is:
#   comment, comment_id, parent_comment_id, root_comment_id, post_id, post_url,
#   url, user_posted, num_upvotes, num_replies, replies, date_posted, timestamp,
#   community_name, is_pinned, is_locked, is_not_safe_for_work_post, …
# The rest are fallbacks in case Bright Data renames a column. Re-derive with
# `scrape_comments.py ... --dump-keys`, which prints the keys off the first row.
ID_FIELDS = ("comment_id", "id")
PARENT_FIELDS = ("parent_comment_id", "parent_id", "reply_to_comment_id", "parent")
AUTHOR_FIELDS = ("user_posted", "author", "username", "user_name", "commenter")
SCORE_FIELDS = ("num_upvotes", "upvotes", "score", "num_votes", "points")

PERMALINK = re.compile(r"/comments/([a-z0-9]+)/[^/]*/([a-z0-9]+)/?$", re.I)
POST_ID = re.compile(r"/comments/([a-z0-9]+)", re.I)


def post_id(url: str) -> str:
    """The thread id out of any Reddit URL — a post link or a comment permalink."""
    m = POST_ID.search(url or "")
    return m.group(1) if m else ""


def ids_from_url(url: str) -> tuple[str, str]:
    """(post_id, comment_id) straight off a Reddit permalink. A post link has no
    comment id and yields ("<post>", "").

    Every record in every existing comments/*.json carries a permalink, so the
    two ids that matter survive even if Bright Data renames its columns. This is
    the one part of the mapping that cannot silently drift.
    """
    m = PERMALINK.search(url or "")
    return (m.group(1), m.group(2)) if m else (post_id(url), "")


def _first(row: dict, fields: tuple[str, ...]) -> str:
    return next((str(row[f]).strip() for f in fields
                 if row.get(f) not in (None, "") and str(row[f]).strip()), "")


def _strip_kind(s: str) -> str:
    return re.sub(r"^t\d_", "", str(s or ""))       # reddit prefixes: t1_ / t3_


# A reply is NOT another row. Bright Data nests them under the parent in
# `replies`, with a different schema — so parent_comment_id is empty on every row
# it returns and the thread looks flat. Flattening is what makes an exchange
# possible at all; without it pair_exchanges() has nothing to pair.
REPLY_FIELDS = {"reply_id": "comment_id", "reply": "comment",
                "user_replying": "user_posted", "num_upvotes": "num_upvotes",
                "date_of_reply": "date_posted"}


def flatten_replies(rows: list[dict]) -> list[dict]:
    """Each row, followed by its nested replies as rows of the same shape."""
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(row)
        kids = row.get("replies")
        if not isinstance(kids, list):
            continue
        parent_url = str(row.get("url") or "")
        for kid in kids:
            if not isinstance(kid, dict) or not kid.get("reply"):
                continue
            flat = {dst: kid[src] for src, dst in REPLY_FIELDS.items() if kid.get(src)}
            flat["parent_comment_id"] = row.get("comment_id") or ""
            flat["post_id"] = row.get("post_id") or ""
            flat["_pinned"] = row.get("_pinned", False)
            # the reply has no permalink of its own; the parent's differs only in
            # the trailing comment id
            rid = flat.get("comment_id")
            if parent_url and rid:
                flat["url"] = re.sub(r"[a-z0-9]+/?$", f"{rid}/", parent_url, flags=re.I)
            out.append(flat)
    return out


# Reddit bodies arrive HTML-escaped, and its spoiler markup would otherwise read
# as literal punctuation on screen ("&gt;!Tombstone isn't using them!&lt;").
SPOILER = re.compile(r">!(.*?)!<", re.S)


def clean_text(raw: str) -> str:
    import html
    t = html.unescape(str(raw or ""))
    t = SPOILER.sub(r"\1", t)
    return t


def enrich(row: dict, rec: dict) -> dict:
    """Copy author / score / thread ids off a raw Bright Data row onto a record."""
    post, cid = ids_from_url(rec.get("url", ""))
    rec["id"] = _first(row, ID_FIELDS) or cid
    rec["post"] = post
    parent = _strip_kind(_first(row, PARENT_FIELDS))
    rec["parent"] = "" if parent in ("", post, rec["id"]) else parent
    author = _first(row, AUTHOR_FIELDS)
    if author and author.lower() not in DROP_EXACT:
        rec["author"] = re.sub(r"^/?u/", "", author)
    raw = _first(row, SCORE_FIELDS)
    try:
        rec["score"] = int(float(raw))
    except ValueError:
        rec["score"] = 0
    return rec


# ------------------------------------------------------------ prediction labels
BATCH = 20                   # comments per model call
KINDS = ("prediction", "reaction", "banter", "meta")

SYSTEM = "You label BattleBots fan comments from r/battlebots. Reply with JSON only."

TEMPLATE = """These comments are about the fight {left} vs {right}.

For each numbered comment give:
  "pick"  — which of the two the commenter expects or wants to WIN. Exactly
            "{left}", "{right}", or "none". Use "none" if they name neither,
            hedge, or are talking about a different matchup.
  "phase" — "pre" if it predicts an outcome that has not happened yet,
            "post" if it reacts to a fight that already happened.
  "kind"  — "prediction" | "reaction" | "banter" | "meta"
            (meta = schedules, where to watch, production complaints).

Judge only what is said about THESE two robots. A comment may praise one and
pick the other: "As much as Skorpios is my goat, Manta is going to kick their
ass" is pick "Manta". A comment covering three fights picks only from this one.

{numbered}

Reply with only:
{{"labels":[{{"n":1,"pick":"...","phase":"...","kind":"..."}}]}}"""


def pick_backend(want: str = "auto") -> str:
    """Which model runs the labels. Never reaches analyze.client(): this repo's
    .env has an OPENAI_API_KEY and no ANTHROPIC_API_KEY."""
    import shutil
    if want and want != "auto":
        return want
    if config.openai_key():
        return "openai"
    return "cli" if shutil.which("claude") else "none"


def _ask_openai(prompt: str) -> dict:
    import analyze                                   # lazy: avoids an import cycle
    api = analyze.openai_client()
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": prompt}]
    for _ in range(2):                               # one retry on bad JSON
        msg = api.chat.completions.create(
            model=analyze.OPENAI_MODEL, messages=messages,
            response_format={"type": "json_object"})
        try:
            return analyze.parse_json(msg.choices[0].message.content or "")
        except (ValueError, json.JSONDecodeError):
            messages = messages + [{"role": "user", "content":
                "Your last reply was not valid JSON. Reply with the JSON object only."}]
    raise ValueError("no JSON after a retry")


def _ask_cli(prompt: str) -> dict:
    """Same labels through `claude -p`, billing a Claude subscription instead of
    an API key. analyze.ask_cli() cannot be reused — its signature is frame-shaped
    — so this borrows the shell shape only. No --allowedTools: there is nothing
    to read, the comments are in the prompt."""
    import analyze                                   # lazy: avoids an import cycle
    cmd = ["claude", "-p", "--model", analyze.MODEL, "--output-format", "json"]
    done = subprocess.run(cmd, input=f"{SYSTEM}\n\n{prompt}",
                          capture_output=True, text=True, timeout=300)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip()[:200])
    return analyze.parse_json(json.loads(done.stdout)["result"])


def _apply(batch: list[dict], out: dict, card: dict) -> None:
    """Fold one reply onto its records. All model output is untrusted."""
    names = {bot_key(card.get(s, "")): card.get(s, "") for s in ("left", "right")}
    ours = set(names) - {""}
    for lab in out.get("labels", []):
        if not isinstance(lab, dict):
            continue
        try:
            i = int(lab.get("n", 0)) - 1
        except (TypeError, ValueError):
            continue
        if not 0 <= i < len(batch):
            continue
        rec = batch[i]
        k = bot_key(lab.get("pick", ""))          # "none" and junk both fall out here
        rec["pick"] = k if k in ours else ""
        if lab.get("phase") in ("pre", "post"):
            rec["phase"] = lab["phase"]
        if lab.get("kind") in KINDS:
            rec["kind"] = lab["kind"]


def void_flips(recs: list[dict], card: dict) -> int:
    """Clear a pick that names the OTHER robot and not the picked one.

    The failure worth catching is a flip. It is deliberately narrow: voiding
    every pick whose robot goes unnamed would kill "rooting for the king of
    kinetic energy to make its comeback", which is a real Tombstone vote. It
    does cost the odd inverse-signal pick ("Is it too early to say RIP
    Skorpios?" reads as a Manta vote) — an acceptable trade against trusting a
    label that contradicts the only robot the comment actually names.

    Separate from _apply() so it can be re-run over a comments file that was
    written before this check existed.
    """
    names = {bot_key(card.get(s, "")): card.get(s, "") for s in ("left", "right")}
    ours = set(names) - {""}
    voided = 0
    for rec in recs:
        pick = rec.get("pick")
        if not pick or pick not in ours:
            continue
        other = next((o for o in ours if o != pick), "")
        if other and mentions(rec["text"], names[other]) \
                and not mentions(rec["text"], names[pick]):
            rec["pick"] = ""
            voided += 1
    return voided


def classify(recs: list[dict], card: dict, backend: str = "auto") -> list[dict]:
    """Cache a predicted-winner label onto each record, at SCRAPE time.

    Best effort throughout. Defaults are written BEFORE any model call, so a
    failure mid-run still leaves every record with a valid phase/pick/kind and
    the pipeline continues — the HUD just has no crowd card to draw.
    """
    for r in recs:
        r.setdefault("pick", "")
        r.setdefault("kind", "")
        # Deterministic default: the pinned fight card is pre-fight by
        # definition, anything discovery found is a reaction. The model may
        # override — a fight-card thread keeps collecting replies after the
        # episode airs — but this stands on its own if it never runs.
        r.setdefault("phase", "pre" if r.get("pinned") else "post")

    which = pick_backend(backend)
    if which == "none" or not recs:
        print("  … no label backend (set OPENAI_API_KEY or install claude); "
              "keeping defaults", file=sys.stderr)
        return recs
    ask = {"openai": _ask_openai, "cli": _ask_cli}.get(which)
    if ask is None:
        print(f"  ! unknown label backend {which!r}; keeping defaults", file=sys.stderr)
        return recs

    print(f"  … labelling {len(recs)} comments via {which}", file=sys.stderr)
    for k in range(0, len(recs), BATCH):
        batch = recs[k:k + BATCH]
        numbered = "\n".join(f"{i + 1}. {r['text']}" for i, r in enumerate(batch))
        prompt = TEMPLATE.format(left=card.get("left") or "the left robot",
                                 right=card.get("right") or "the right robot",
                                 numbered=numbered)
        try:
            _apply(batch, ask(prompt), card)
        except Exception as e:            # one bad batch must not lose the others
            print(f"  ! label batch {k // BATCH + 1} failed ({str(e)[:120]}); "
                  f"leaving defaults", file=sys.stderr)
    voided = void_flips(recs, card)
    if voided:
        print(f"  … voided {voided} pick(s) that named only the other robot",
              file=sys.stderr)
    return recs


def pair_exchanges(recs: list[dict], limit: int = 3) -> None:
    """Mark reply chains the HUD can play as two beats: ex="1a" on the parent,
    "1b" on the reply.

    Both halves are already showable — they are records, so they passed the gate.
    A self-reply is skipped: that is one person finishing a thought, not a crowd
    disagreeing, and the two-beat only reads as an exchange when two people are
    actually arguing.
    """
    by_id = {r["id"]: r for r in recs if r.get("id")}
    cands = []
    for r in recs:
        p = by_id.get(r.get("parent") or "")
        if not p or p is r or r.get("rival") or p.get("rival"):
            continue
        if p.get("author") and p.get("author") == r.get("author"):
            continue
        # `meta` is show-and-schedule chatter, the same thing join_comments()
        # skips. "No tombstone this season" answered by "a real shame" is a
        # conversation about the series, not about the fight on screen.
        if "meta" in (p.get("kind"), r.get("kind")):
            continue
        cands.append((p, r))
    # Ranked, in order:
    #   1. disagreement — two people picking opposite robots is the whole reason
    #      to show a reply chain at all
    #   2. both halves off the pinned fight card. Discovery drags in season
    #      rumour threads, and "No tombstone this season" / "a real shame" is a
    #      chain about the show, not about this fight
    #   3. loudest, then id so the choice is stable across scrapes rather than
    #      following Bright Data's row order
    cands.sort(key=lambda pr: (
        not (pr[0].get("pick") and pr[1].get("pick")
             and pr[0]["pick"] != pr[1]["pick"]),
        not (pr[0].get("pinned") and pr[1].get("pinned")),
        -(int(pr[0].get("score") or 0) + int(pr[1].get("score") or 0)),
        pr[0].get("id", "")))
    n = 0
    for p, r in cands:
        if p.get("ex") or r.get("ex"):
            continue
        n += 1
        p["ex"], r["ex"] = f"{n}a", f"{n}b"
        if n >= limit:
            return
