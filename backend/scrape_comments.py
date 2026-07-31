#!/usr/bin/env python3
"""scrape_comments.py <clipname> <query> [flags] — fan chatter -> comments/<clipname>.json

    python backend/scrape_comments.py fight1 "tombstone witch doctor" --mock
    python backend/scrape_comments.py manta-skorpios "manta skorpios" --bots "Manta,Skorpios"
    python backend/scrape_comments.py ep3-fight1 "hydra riptide" --post-url "https://…"

    --mock       canned comments; no API key, deterministic, and the only way to
                 exercise the exchange/prediction paths without spending money
    --bots "L,R" pin the card. Segmentation and the prediction labels both need
                 to know which two robots are in THIS fight; without it every
                 other known bot reads as a rival (same trap as analyze.py)
    --post-url   pin an extra discussion thread (comma-separated for several)
    --backend    openai | cli | none — who labels the predictions (default: auto)
    --dump-keys  print the raw field names off the first row and carry on

Pulls the episode's pinned fight-card thread plus keyword-discovered r/battlebots
threads via Bright Data, routes each comment to this matchup, and normalises to
records carrying text, author, score, thread ids and a cached prediction label.

The PRIMARY source is the fight card — see FIGHT_CARD below. Keyword discovery
can only ever find posts written after the fight; a fight card is where the crowd
says who they think will win, which is the one thing a post-hoc search can never
surface.

If the live call misbehaves, the ONLY function you should need to touch is
brightdata_adapter() below — see the ADAPTER banner. Everything about the text
itself (safety gates, matchup routing, prediction labels) is in crowd.py.
"""
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
import crowd  # noqa: E402
# The two deterministic gates CLAUDE.md names live in crowd.py now, next to the
# segmentation that decides what they are applied TO. Re-exported so the
# documented home still resolves.
from crowd import MAX_LEN, MIN_LEN, is_showable, names_a_rival  # noqa: E402,F401

ROOT = Path(__file__).resolve().parent.parent
MAX_COMMENTS = 60            # cap on the OUTPUT file
LIMIT_PER_INPUT = 40         # Bright Data's per-input record cap — the BILLED one
TIMEOUT = 60
SCRAPE_TIMEOUT = 300         # synchronous scrape blocks while the job runs


# ============================================================================
#  ADAPTER — the one place Bright Data's API shape is assumed.
#
#  Bright Data "Reddit - Posts", discover_by=subreddit_url.
#
#    POST /datasets/v3/scrape?dataset_id=...&type=discover_new
#                     &discover_by=subreddit_url&notify=false&include_errors=true
#         body: {"input": [{"url": "https://www.reddit.com/r/battlebots/",
#                           "keyword": "...", "sort_by": "Top",
#                           "sort_by_time": "All Time", "num_of_posts": 40}],
#                "limit_per_input": 40}
#      -> 202 {"snapshot_id": "sd_..."}
#    GET  /datasets/v3/snapshot/<id>?format=json
#      -> 202 while running, 200 + [rows] once ready
#
#  WHY subreddit_url AND NOT discover_by=keyword: keyword discovery searches all
#  of Reddit and word-matches loosely. "battlebots tombstone witch doctor"
#  returned 40 rows of r/tifu, r/movies and r/politics — posts matching "doctor"
#  or "fight", nothing to do with robot combat. Scoping to r/battlebots and
#  passing the bot names as `keyword` is what makes the results on-topic.
#
#  NOTE: picking "Synchronous (Real-time)" in the dashboard does NOT make this
#  return rows inline — /scrape still queues a job and hands back a snapshot id,
#  so the poll below is required. Verified against live runs, which took 1-6 min.
#
#  Field requirements differ per mode: keyword mode requires `date`, subreddit
#  mode requires `url` and takes `sort_by_time` instead. POSTing {"input":[{}]}
#  is free and 400s with the exact required-field list — the cheapest way to
#  re-derive this if it drifts. Then fix ENDPOINT / PARAMS / the field names in
#  _rows_to_comments(); nothing else in this repo changes.
#
#  Billing is per record ($1.50/1k), so num_of_posts and limit_per_input are both
#  pinned to MAX_COMMENTS rather than left null as in their sample.
# ============================================================================
ENDPOINT = "https://api.brightdata.com/datasets/v3/scrape"
SNAPSHOT_ENDPOINT = "https://api.brightdata.com/datasets/v3/snapshot"
POLL_EVERY = 15              # seconds between snapshot checks
POLL_TRIES = 40              # ~10 min; a discovery job has overrun 6 more than once
SUBREDDIT = "https://www.reddit.com/r/battlebots/"
MIN_ROWS = 8                 # below this, retry without the keyword filter
# Two-step: discover posts about the fight, then pull their comment threads.
COMMENTS_DATASET = os.environ.get("BRIGHTDATA_REDDIT_COMMENTS", "gd_lvzdpsdlw09j6t702")
THREADED = os.environ.get("GAMEOVER_THREADED", "1") != "0"   # 0 = titles only
# Was 5, but the URL fan-out bug below meant it only ever covered ~2 distinct
# threads. Fixing that roughly tripled the billed record count, so the cap comes
# down to hold the cost flat — the pinned fight card now carries the load.
POSTS_FOR_COMMENTS = 3       # threads to expand; each costs records

# Era A: the episode's PRE-fight discussion thread, pinned per clip. Discovery is
# a lottery and it lost — a keyword run for "mad catter tombstone" came back with
# 14 rows of "Season 7 Rumor Mill" and 8 from a two-year-old SawBlaze fight, and
# nothing at all from the actual episode. All three demo clips are on one card:
# 1up1lxt is Pro League Episode 2 (Copperhead/Jackpot, Manta/Skorpios,
# MaDCaTTer/Tombstone), which is why focus_segment() in crowd.py has to route a
# single comment to the right matchup.
EP2 = ("https://www.reddit.com/r/battlebots/comments/1up1lxt/"
       "battlebots_pro_league_episode_2_fight_card/")
FIGHT_CARD = {
    "jackpot-copperhead": EP2,
    "manta-skorpios": EP2,
    "madcatter-tombstone": EP2,
}
DATASETS = {
    # dataset ids from the Bright Data dashboard — swap for the ones on your account
    "reddit": os.environ.get("BRIGHTDATA_REDDIT_DATASET", "gd_lvz8ah06191smkebj4"),
    # no default: YouTube needs its own scraper + id. Unset means "skip that source".
    "youtube": os.environ.get("BRIGHTDATA_YOUTUBE_DATASET", ""),
}
# Candidate field names for the comment body / link, tried in order.
TEXT_FIELDS = ("comment", "comment_text", "text", "body", "title", "description")
URL_FIELDS = ("url", "post_url", "comment_url", "link", "video_url")


def _parse_payload(text: str):
    """Bright Data answers this endpoint in NDJSON — one record per line, not a
    JSON array. A single-record reply therefore parses as a bare record dict,
    which the snapshot/envelope branches below read as "no rows" and turned into
    zero comments while the HTTP call was a perfectly healthy 200.

    Returns a list of records, or the dict when it really is a job envelope.
    """
    text = text.strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:              # several objects, one per line
        rows = []
        for line in text.splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows
    # A bare record is data, not an envelope — tell them apart by their keys.
    if isinstance(data, dict) and not ({"snapshot_id", "data", "results"} & data.keys()):
        return [data]
    return data


def discover(query: str, run) -> list[dict]:
    """Keyword-scoped subreddit discovery — the SECONDARY pool, for reactions."""
    base = {"url": SUBREDDIT, "sort_by": "Top", "sort_by_time": "All Time",
            "num_of_posts": LIMIT_PER_INPUT}
    rows = run([{**base, "keyword": query}])
    if len(rows) < MIN_ROWS:
        # Narrow bot names often match almost nothing. Falling back to the
        # subreddit's top posts keeps the HUD stocked; the caption/comment join
        # in analyze.py is what decides relevance anyway. Costs a second job.
        print(f"  … only {len(rows)} hits for '{query}', retrying unfiltered",
              file=sys.stderr)
        rows = run([base])
    return rows


def brightdata_adapter(query: str, source: str, api_key: str,
                       pinned: list[str] | None = None,
                       dump_keys: bool = False) -> list[dict]:
    """ADAPTER: return raw rows from Bright Data for `query` on `source`.

    `pinned` is a list of known post URLs — the fight card. Those go straight to
    the comments dataset with discover=False and cost no discovery job at all.
    """
    import time

    import requests

    dataset = DATASETS.get(source)
    if not dataset:
        raise RuntimeError(f"no dataset id configured for {source} — skipping")

    def run(input_rows: list[dict], dataset_id: str | None = None,
            discover: bool = True) -> list[dict]:
        params = {"dataset_id": dataset_id or dataset, "notify": "false",
                  "include_errors": "true"}
        if discover:                       # omitted when collecting known URLs
            params |= {"type": "discover_new", "discover_by": "subreddit_url"}
        resp = requests.post(
            ENDPOINT,
            params=params,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json={"input": input_rows, "limit_per_input": LIMIT_PER_INPUT},
            timeout=SCRAPE_TIMEOUT,
        )
        resp.raise_for_status()
        payload = _parse_payload(resp.text)

        # 200 with rows inline is possible; 202 means "queued, poll for it".
        if isinstance(payload, list):
            return payload
        snapshot_id = payload.get("snapshot_id")
        if not snapshot_id:
            return payload.get("data") or payload.get("results") or []

        print(f"  … {source} job queued ({snapshot_id}), waiting", file=sys.stderr)
        for _ in range(POLL_TRIES):
            time.sleep(POLL_EVERY)
            got = requests.get(f"{SNAPSHOT_ENDPOINT}/{snapshot_id}",
                               params={"format": "json"},
                               headers={"Authorization": f"Bearer {api_key}"},
                               timeout=TIMEOUT)
            if got.status_code == 202:                # still running
                continue
            got.raise_for_status()
            rows = _parse_payload(got.text)
            if isinstance(rows, dict):
                rows = rows.get("data") or rows.get("results") or []
            return rows if isinstance(rows, list) else []
        raise TimeoutError(f"snapshot {snapshot_id} not ready after "
                           f"{POLL_TRIES * POLL_EVERY}s — it may still finish; "
                           f"re-run to pick it up")

    def note_keys(rows: list[dict], what: str) -> None:
        """One line that settles the undocumented column names off a live row.
        Guessing them costs a second billed run; this costs nothing."""
        first = next((r for r in rows if isinstance(r, dict)), None)
        if dump_keys and first:
            print(f"  … {what} row keys: {sorted(first)}", file=sys.stderr)

    # --- step 0: the pinned fight card. PRIMARY source ------------------------
    # The comments dataset takes a bare {"url": <post>} with discover=False, so a
    # thread we already know needs no discovery pass and no keyword luck.
    threads: list[dict] = []
    pinned_ids = {crowd.post_id(u) for u in (pinned or [])} - {""}
    if pinned and THREADED:
        print(f"  … pinned fight card: {len(pinned)} thread(s)", file=sys.stderr)
        try:
            threads = run([{"url": u, "sort_by": "Top"} for u in pinned],
                          dataset_id=COMMENTS_DATASET, discover=False)
            note_keys(threads, "comment")
            for r in threads:
                if isinstance(r, dict):
                    # `_` prefix so it is never matched by TEXT_FIELDS/URL_FIELDS
                    r["_pinned"] = True
        except Exception as e:            # discovery below is still worth running
            print(f"  ! pinned fight card failed ({e}); falling back to discovery",
                  file=sys.stderr)
    elif pinned:
        print("  ! GAMEOVER_THREADED=0 — skipping the pinned fight card, which is "
              "a comment thread by definition", file=sys.stderr)

    # Discovery is SECONDARY, so nothing it does may cost us the fight card we
    # already paid for. It runs two more jobs and each can time out at ~6 min —
    # letting that raise past here threw away a good pinned pull and wrote an
    # empty comments file over a working one.
    try:
        rows = discover(query, run)
    except Exception as e:
        print(f"  ! discovery failed ({e}); keeping the pinned fight card",
              file=sys.stderr)
        return threads
    note_keys(rows, "post")

    if not THREADED:
        return threads + rows

    # --- step 2: real threaded comments off the posts we just discovered ------
    # Post titles read like headlines ("The Battlebots Season 6 Rumor Mill").
    # Actual comments read like a crowd reacting, which is what the HUD wants.
    # Costs one extra job; falls back to the titles if it yields nothing.
    #
    # ONE url per row. The old comprehension iterated URL_FIELDS *inside* the row
    # loop, so a row carrying both `url` and `post_url` contributed two entries
    # and the [:POSTS_FOR_COMMENTS] slice covered 2 distinct threads instead of
    # 5 — which is how every clip ended up drawing from exactly two threads.
    seen, urls = set(), []
    for r in rows:
        if not isinstance(r, dict):
            continue
        u = next((str(r[f]) for f in URL_FIELDS if r.get(f)), "").split("?")[0].rstrip("/")
        if u and u not in seen and crowd.post_id(u) not in pinned_ids:   # never pay twice
            seen.add(u)
            urls.append(u)
        if len(urls) >= POSTS_FOR_COMMENTS:
            break
    if not urls:
        return threads + rows
    print(f"  … pulling comments from {len(urls)} posts", file=sys.stderr)
    try:
        threaded = run([{"url": u, "sort_by": "Top"} for u in urls],
                       dataset_id=COMMENTS_DATASET, discover=False)
        note_keys(threaded, "comment")
    except Exception as e:                       # keep the titles rather than nothing
        print(f"  ! comment pass failed ({e}); keeping post titles", file=sys.stderr)
        return threads + rows
    return threads + (threaded or rows)
# ============================ END ADAPTER ===================================


def _rows_to_comments(rows: list[dict], source: str, card: dict) -> list[dict]:
    """Raw Bright Data rows -> showable records routed to THIS matchup.

    The unit being filtered is a span of a comment, not the comment — see
    focus_segment() in crowd.py. A record's `text` is therefore the part about
    this fight, which is how Ellindsey's three-matchup prediction reaches three
    different clips instead of being dropped for length.
    """
    ours = [card.get("left", ""), card.get("right", "")]
    out, dropped, seen = [], 0, set()
    for row in crowd.flatten_replies(rows):
        if not isinstance(row, dict):
            continue
        raw = next((str(row[f]).strip() for f in TEXT_FIELDS
                    if row.get(f) and str(row[f]).strip()), None)
        if not raw:
            continue
        text, rival = crowd.focus_segment(crowd.clean_text(raw), ours)
        if not text:
            dropped += 1
            continue
        url = next((str(row[f]) for f in URL_FIELDS if row.get(f)), "")
        rec = crowd.enrich(row, {"text": text, "source": source, "url": url})
        # The same comment can arrive twice — the fight card is pinned AND
        # discoverable — and a duplicate quote on screen reads as a bug.
        key = rec.get("id") or crowd.bot_key(text)
        if key in seen:
            continue
        seen.add(key)
        rec["rival"] = rival
        if row.get("_pinned"):
            rec["pinned"] = True
        out.append(rec)
    if dropped:
        print(f"  … filtered {dropped} unshowable comments", file=sys.stderr)
    return out


def scrape(query: str, card: dict | None = None, pinned: list[str] | None = None,
           backend: str = "auto", dump_keys: bool = False) -> list[dict]:
    api_key = config.brightdata_key()      # .env or shell; BRIGHTDATA_API_KEY or _KEY
    if not api_key:
        sys.exit("no Bright Data key found in .env or the environment "
                 f"(tried {', '.join(config.BRIGHTDATA_NAMES)}); use --mock to work without it)")
    card = card or {}
    comments: list[dict] = []
    for source in [s for s in ("reddit", "youtube") if DATASETS.get(s)]:
        try:
            rows = brightdata_adapter(query, source, api_key,
                                      pinned=pinned if source == "reddit" else None,
                                      dump_keys=dump_keys)
            comments += _rows_to_comments(rows, source, card)
        except Exception as e:                            # one source failing is survivable
            print(f"  ! {source}: {e}", file=sys.stderr)
    # Pinned fight-card comments first, then loudest — MAX_COMMENTS truncates the
    # tail, and the predictions are the whole point of the pinned pass.
    comments.sort(key=lambda c: (not c.get("pinned"), -int(c.get("score") or 0)))
    comments = comments[:MAX_COMMENTS]
    crowd.classify(comments, card, backend)
    crowd.pair_exchanges(comments)
    return comments


MOCK = [
    ("NOT THE ARMOUR AGAIN", "reddit"),
    ("that armour panel never survives a hit like that", "reddit"),
    ("THAT SENT HIM TO THE MOON", "youtube"),
    ("massive hit, airborne again", "reddit"),
    ("the drive is gone, it's over", "reddit"),
    ("chain snapped, weapon dead", "youtube"),
    ("that wheel is wobbling so bad", "youtube"),
    ("immobile, count it", "reddit"),
    ("sparks everywhere, what a fight", "youtube"),
    ("spins up faster than anything in the box", "reddit"),
    ("weapon still spinning somehow", "youtube"),
    ("frame is bent, look at that", "reddit"),
    ("first contact and it's already carnage", "youtube"),
    ("both bots still mobile, incredible", "reddit"),
    ("hitting itself lmao", "youtube"),
    ("judges won't need to decide this one", "reddit"),
]
# Pre-fight lines, so --mock exercises the VS card and the crowd tally. {bot} is
# filled from --bots; without a card these stay unlabelled and both new UI blocks
# hide themselves, which is the behaviour worth testing too.
MOCK_PRE = [
    "{bot} takes this one, easily",
    "no way {bot} loses this matchup",
    "{bot} by KO, calling it now",
    "as much as I love the other guy, {bot} wins",
    "hard disagree — {bot} has the better weapon here",
    "{bot} looked rough last episode but I still like them",
]


def mock(query: str, card: dict | None = None) -> list[dict]:
    """Canned comments. There are no tests in this repo, so --mock IS the test:
    it has to cover authors, predictions and a reply chain, or the only way to
    exercise those paths is to spend money on a live scrape."""
    rng = random.Random(query)                            # deterministic per query
    card = card or {}
    sides = [card.get("left", ""), card.get("right", "")]
    picks = MOCK[:]
    rng.shuffle(picks)
    out = [{"text": t, "source": s,
            "url": (f"https://reddit.com/r/battlebots/comments/mock{i}" if s == "reddit"
                    else f"https://youtube.com/watch?v=mock&lc={i}"),
            "author": f"mockfan{i}", "score": 40 - i, "id": f"m{i}", "parent": "",
            "post": "mock", "rival": False, "phase": "post", "kind": "reaction",
            "pick": ""}
           for i, (t, s) in enumerate(picks[:MAX_COMMENTS])]

    for k, tmpl in enumerate(MOCK_PRE):
        bot = sides[k % 2] or ""
        rec = {"text": tmpl.format(bot=bot) if bot else tmpl.replace("{bot} ", ""),
               "source": "reddit",
               "url": f"https://reddit.com/r/battlebots/comments/mock/pre{k}",
               "author": f"mockpredictor{k}", "score": 30 - k, "id": f"p{k}",
               "parent": "", "post": "mock", "pinned": True, "rival": False,
               "phase": "pre", "kind": "prediction",
               "pick": crowd.bot_key(bot) if bot else ""}
        out.insert(k, rec)
    # One reply chain with OPPOSING picks — "hard disagree" answering the
    # Skorpios take — so pair_exchanges() has a real argument to find and the
    # two-beat playback is testable without a live thread.
    if len(out) > 5 and sides[0] and sides[1]:
        out[4]["parent"] = out[1]["id"]
    crowd.pair_exchanges(out)
    return out[:MAX_COMMENTS]


def flag(name: str, default: str = "") -> str:
    """--name value, or --name=value."""
    argv = sys.argv
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return default


def relabel(path: Path, card: dict, backend: str) -> list[dict]:
    """Re-run the prediction labels over a pool already on disk. No scrape.

    classify() only ever ran inside scrape(), so improving a label meant paying
    Bright Data again and risking the pool — and re-scraping the same pinned
    thread is a lottery that can quietly return a WORSE set, which the
    zero-rows guard does not catch because it only fires on nothing at all.

    Only `pick`, `phase` and `kind` move. `text` is untouched, so no timeline's
    fan_comment can be orphaned by this and no --rejoin is needed afterwards.
    It IS non-deterministic — the model may label a comment it skipped last time,
    or skip one it labelled — and it re-runs pair_exchanges(), so the `ex` pairs
    can shuffle. Diff the file before committing.
    """
    if not path.exists():
        sys.exit(f"no {path.name} to re-classify — scrape it first")
    comments = json.loads(path.read_text())
    before = sum(1 for c in comments if c.get("pick"))
    crowd.classify(comments, card, backend)
    crowd.pair_exchanges(comments)
    after = sum(1 for c in comments if c.get("pick"))
    print(f"  re-classified {len(comments)} comments: {before} -> {after} picks")
    return comments


def main() -> None:
    flagged = {f"--{n}" for n in ("bots", "post-url", "backend")}
    args, skip = [], False
    for a in sys.argv[1:]:                 # a flag's value is not a positional
        if skip:
            skip = False
            continue
        if a in flagged:
            skip = True
        elif not a.startswith("--"):
            args.append(a)
    if len(args) < 2:
        sys.exit(__doc__)
    clipname, query = Path(args[0]).stem, " ".join(args[1:])

    names = [b.strip() for b in flag("--bots").split(",") if b.strip()]
    card = {"left": names[0], "right": names[1]} if len(names) == 2 else {}
    if not card:
        print("  ! no --bots: every other known robot reads as a rival and the "
              "prediction labels have no card to pick from", file=sys.stderr)
    # --post-url wins, then the Era A table, then discovery alone.
    pinned = [u.strip() for u in flag("--post-url").split(",") if u.strip()] \
        or ([FIGHT_CARD[clipname]] if clipname in FIGHT_CARD else [])

    out = ROOT / "comments" / f"{clipname}.json"
    out.parent.mkdir(exist_ok=True)

    if "--reclassify" in sys.argv:
        comments = relabel(out, card, flag("--backend", "auto"))
    elif "--mock" in sys.argv:
        comments = mock(query, card)
    else:
        comments = scrape(query, card, pinned, flag("--backend", "auto"),
                          "--dump-keys" in sys.argv)
    # A timed-out job is not a reason to destroy a working pool. The committed
    # timelines reference these exact strings by text, so an empty file silently
    # strips every fan comment and every author off a fight that had them.
    if not comments and out.exists():
        sys.exit(f"scrape returned nothing — keeping the existing {out.name}. "
                 f"Re-run to pick up a snapshot that may still be finishing.")
    out.write_text(json.dumps(comments, indent=2) + "\n")
    picks = sum(1 for c in comments if c.get("pick"))
    exes = sum(1 for c in comments if str(c.get("ex", "")).endswith("a"))
    print(f"wrote {out} — {len(comments)} comments, {picks} picks, {exes} exchanges"
          f"{' (mock)' if '--mock' in sys.argv else ''}")


if __name__ == "__main__":
    main()
