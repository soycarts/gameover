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


# ============================================================================
#  ADAPTER — the one place Bright Data's API shape is assumed.
#
#  This targets the Bright Data SERP / Web Scraper "trigger + snapshot" flow:
#    POST https://api.brightdata.com/datasets/v3/trigger?dataset_id=...
#         Authorization: Bearer $BRIGHTDATA_API_KEY
#         body: [{"url": "..."}]  ->  {"snapshot_id": "..."}
#    GET  https://api.brightdata.com/datasets/v3/snapshot/<id>?format=json
#
#  If their docs say otherwise, fix ENDPOINT / DATASETS / the field names in
#  _rows_to_comments() and nothing else in this repo needs to change.
# ============================================================================
ENDPOINT = "https://api.brightdata.com/datasets/v3"
DATASETS = {
    # dataset ids from the Bright Data dashboard — swap for the ones on your account
    "reddit": os.environ.get("BRIGHTDATA_REDDIT_DATASET", "gd_lvz8ah06191smkebj4"),
    "youtube": os.environ.get("BRIGHTDATA_YOUTUBE_DATASET", "gd_lk56epmy2i5g7lzu0k"),
}
# Candidate field names for the comment body / link, tried in order.
TEXT_FIELDS = ("comment", "comment_text", "text", "body", "title", "description")
URL_FIELDS = ("url", "post_url", "comment_url", "link", "video_url")


def brightdata_adapter(query: str, source: str, api_key: str) -> list[dict]:
    """ADAPTER: return raw rows from Bright Data for `query` on `source`."""
    import time

    import requests

    seed = (f"https://www.reddit.com/r/battlebots/search/?q={requests.utils.quote(query)}"
            if source == "reddit" else
            f"https://www.youtube.com/results?search_query={requests.utils.quote(query)}")

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    trigger = requests.post(f"{ENDPOINT}/trigger",
                            params={"dataset_id": DATASETS[source], "format": "json"},
                            headers=headers, json=[{"url": seed}], timeout=TIMEOUT)
    trigger.raise_for_status()
    snapshot_id = trigger.json().get("snapshot_id")
    if not snapshot_id:
        raise RuntimeError(f"no snapshot_id in trigger response: {trigger.text[:200]}")

    for _ in range(20):                                   # poll until the job is ready
        got = requests.get(f"{ENDPOINT}/snapshot/{snapshot_id}",
                           params={"format": "json"}, headers=headers, timeout=TIMEOUT)
        if got.status_code == 202:                        # still running
            time.sleep(5)
            continue
        got.raise_for_status()
        rows = got.json()
        return rows if isinstance(rows, list) else rows.get("data", [])
    raise TimeoutError("Bright Data snapshot never became ready")
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
    for source in ("reddit", "youtube"):
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
