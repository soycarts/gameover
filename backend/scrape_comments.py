#!/usr/bin/env python3
"""scrape_comments.py <clipname> <query> [--mock] — fan chatter -> comments/<clipname>.json

    python backend/scrape_comments.py fight1 "tombstone witch doctor" --mock
    python backend/scrape_comments.py fight1 "tombstone witch doctor"

Pulls r/battlebots posts and YouTube comments matching the query via Bright Data
and normalises them to [{"text", "source", "url"}], capped at MAX_COMMENTS.

--mock writes plausible fake comments instead, so the pipeline never blocks on
an API key or on the exact Bright Data response shape.

If the live call misbehaves, the ONLY function you should need to touch is
brightdata_adapter() below — see the ADAPTER banner.
"""
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MAX_COMMENTS = 40
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
POLL_TRIES = 24              # give a discovery job up to ~6 minutes
SUBREDDIT = "https://www.reddit.com/r/battlebots/"
MIN_ROWS = 8                 # below this, retry without the keyword filter
# Two-step: discover posts about the fight, then pull their comment threads.
COMMENTS_DATASET = os.environ.get("BRIGHTDATA_REDDIT_COMMENTS", "gd_lvzdpsdlw09j6t702")
THREADED = os.environ.get("GAMEOVER_THREADED", "1") != "0"   # 0 = titles only
POSTS_FOR_COMMENTS = 5       # threads to expand; each costs records
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


def brightdata_adapter(query: str, source: str, api_key: str) -> list[dict]:
    """ADAPTER: return raw rows from Bright Data for `query` on `source`."""
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
            json={"input": input_rows, "limit_per_input": MAX_COMMENTS},
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

    base = {"url": SUBREDDIT, "sort_by": "Top", "sort_by_time": "All Time",
            "num_of_posts": MAX_COMMENTS}
    rows = run([{**base, "keyword": query}])
    if len(rows) < MIN_ROWS:
        # Narrow bot names often match almost nothing. Falling back to the
        # subreddit's top posts keeps the HUD stocked; the caption/comment join
        # in analyze.py is what decides relevance anyway. Costs a second job.
        print(f"  … only {len(rows)} hits for '{query}', retrying unfiltered",
              file=sys.stderr)
        rows = run([base])

    if not THREADED:
        return rows

    # --- step 2: real threaded comments off the posts we just discovered ------
    # Post titles read like headlines ("The Battlebots Season 6 Rumor Mill").
    # Actual comments read like a crowd reacting, which is what the HUD wants.
    # Costs one extra job; falls back to the titles if it yields nothing.
    urls = [r[f] for r in rows for f in URL_FIELDS
            if isinstance(r, dict) and r.get(f)][:POSTS_FOR_COMMENTS]
    if not urls:
        return rows
    print(f"  … pulling comments from {len(urls)} posts", file=sys.stderr)
    try:
        threaded = run([{"url": u, "sort_by": "Top"} for u in urls],
                       dataset_id=COMMENTS_DATASET, discover=False)
    except Exception as e:                       # keep the titles rather than nothing
        print(f"  ! comment pass failed ({e}); keeping post titles", file=sys.stderr)
        return rows
    return threaded or rows
# ============================ END ADAPTER ===================================


def _rows_to_comments(rows: list[dict], source: str) -> list[dict]:
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = next((str(row[f]).strip() for f in TEXT_FIELDS
                     if row.get(f) and str(row[f]).strip()), None)
        if not text or len(text) < 3:
            continue
        url = next((str(row[f]) for f in URL_FIELDS if row.get(f)), "")
        out.append({"text": text[:220], "source": source, "url": url})
    return out


def scrape(query: str) -> list[dict]:
    api_key = config.brightdata_key()      # .env or shell; BRIGHTDATA_API_KEY or _KEY
    if not api_key:
        sys.exit("no Bright Data key found in .env or the environment "
                 f"(tried {', '.join(config.BRIGHTDATA_NAMES)}); use --mock to work without it)")
    comments: list[dict] = []
    for source in [s for s in ("reddit", "youtube") if DATASETS.get(s)]:
        try:
            comments += _rows_to_comments(brightdata_adapter(query, source, api_key), source)
        except Exception as e:                            # one source failing is survivable
            print(f"  ! {source}: {e}", file=sys.stderr)
    return comments[:MAX_COMMENTS]


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


def mock(query: str) -> list[dict]:
    rng = random.Random(query)                            # deterministic per query
    picks = MOCK[:]
    rng.shuffle(picks)
    return [{"text": t, "source": s,
             "url": (f"https://reddit.com/r/battlebots/comments/mock{i}" if s == "reddit"
                     else f"https://youtube.com/watch?v=mock&lc={i}")}
            for i, (t, s) in enumerate(picks[:MAX_COMMENTS])]


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        sys.exit(__doc__)
    clipname, query = Path(args[0]).stem, " ".join(args[1:])

    comments = mock(query) if "--mock" in sys.argv else scrape(query)
    out = ROOT / "comments" / f"{clipname}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(comments, indent=2) + "\n")
    print(f"wrote {out} — {len(comments)} comments"
          f"{' (mock)' if '--mock' in sys.argv else ''}")


if __name__ == "__main__":
    main()
