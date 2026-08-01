# GAMEOVER

**A vision model watches robot-combat footage and turns it into a playable-looking
arcade fighting game — health bars, damage numbers, K.O. — with the real crowd
reacting in the margins.**

Live: **[gameover.fyi](https://gameover.fyi)** · press **Space**

The fight is real footage. Everything overlaid on it is derived: the health bars come
from a vision model's frame-by-frame damage ratings, the hit markers land where the
model saw contact, and the comments floating past are real people from
[r/battlebots](https://reddit.com/r/battlebots), pulled with **Bright Data**, timed to
the blows they are reacting to.

---

## What's actually hard here

A fight video is 150 seconds of unstructured pixels. An arcade HUD needs a number
between 0 and 100, updating twice a second, that never lies about who is winning.
Getting from one to the other is the project.

Three things carry it:

1. **The model rates, code decides.** The vision model never emits hp. It rates a
   damage word per bot per frame — `none` / `glance` / `solid` / `heavy` /
   `catastrophic` — and deterministic Python turns that into a bar. Asking for hp
   directly is what the pipeline used to do, and the model nudged the bar down 3–5
   points a frame to signal "time passed": 23 events, 2 real hits, a bar that drains
   but never lands.
2. **A knockout is a count, not a blow.** Forcing the loser to 0 on the last event
   invented a 68-point finishing hit out of a referee standing at the driver booth.
   Now the code finds where the loser stopped moving and bleeds the remaining hp
   across the count, one step a second.
3. **The crowd is a second channel.** The HUD would be a data viz without it. Real
   comments — a pre-fight prediction split, a reaction fired on the blow it describes,
   a two-person argument replayed as an exchange — are what make it feel like a fight
   people watched together.

---

## Bright Data: what the crowd layer is built on

Every comment in the HUD comes through Bright Data. Not as a bulk dump — as two
datasets playing two different roles, because a fight has a *before* and an *after*
and they are not the same problem.

### Two pools, and why one of them cannot be discovered

| | dataset | role |
|---|---|---|
| **Pinned** | Reddit — Comments (`gd_lvzdpsdlw09j6t702`) | the episode's **pre-fight card thread**, expanded into real threaded comments |
| **Discovery** | Reddit — Posts (`discover_by=subreddit_url`) | everything written *about* the fight afterwards |

**The pinned thread is the primary source, and this is the design decision the whole
crowd layer rests on.** Discovery — by definition — can only find posts that already
exist. Every post about a fight is written *after* it. So a discovery-only pipeline can
never surface a **prediction**, and predictions are the most interesting thing the
crowd produces: they are the only comments where the audience is wrong on record.

The HUD's pre-fight `CROWD CALL` panel — *"As much as Skorpios is my goat, Manta is
going to kick their ass"* against *"Skorpios over manta is some serious copium"*, with
a percentage split — exists only because `FIGHT_CARD` pins each clip to its episode's
fight-card thread and expands it with the Comments dataset. Discovery stays on as the
secondary pool for reactions, wrapped so a timeout on it can never cost the pinned
pull.

### Scoping, and a failure worth naming

Discovery runs `discover_by=subreddit_url`, **not** `discover_by=keyword`. Keyword
discovery searches all of Reddit and word-matches loosely: `"battlebots tombstone
witch doctor"` came back with 40 rows from r/tifu, r/movies and r/politics — posts
matching *"doctor"* or *"fight"*, nothing to do with robot combat. Scoping to
`r/battlebots` and passing the bot names as `keyword` is what makes results on-topic.

Even scoped, discovery is a lottery: a run for *"mad catter tombstone"* returned 14
rows of "Season 7 Rumor Mill" and 8 from a two-year-old SawBlaze fight. That is not a
criticism of the tool — it is what searching a subreddit for a matchup actually
returns — and it is exactly why the pinned thread carries the load.

### What the API shape taught us

Three things that cost real debugging time, recorded so nobody repeats them:

- **Replies are nested, not rows.** `parent_comment_id` is empty on every top-level
  row, and children hang off a `replies` list with a *different* schema
  (`reply_id` / `user_replying` / `reply` / `date_of_reply`). `flatten_replies()`
  expands them. Without it the thread looks completely flat — and **the whole
  exchange feature is impossible**, because there are no parent/child pairs to
  replay. The nesting is a feature we depend on; we just had to notice it was there.
- **Responses are NDJSON, not a JSON array.** One record per line, and a
  single-record reply is a bare dict. `resp.json()` yields zero comments on a
  perfectly healthy HTTP 200.
- **"Synchronous" still queues.** `/datasets/v3/scrape` returns `202` with a
  `snapshot_id`; you poll `/snapshot/<id>` until it turns `200`. Live runs took 1–6
  minutes. Picking "Real-time" in the dashboard does not change this.

### What we do with the data once it lands

The scrape is the start, not the end. Every stage below is deterministic Python:

- **`focus_segment()` routes, rather than drops.** One fight-card thread covers three
  matchups, so a single comment often names robots from all of them. Ellindsey's
  prediction is one paragraph per matchup, over 600 characters; *"My money is on
  Copperhead, Manta, and Madcatter"* names six robots. A naive length cap and a naive
  rival filter dropped both — the two best comments in the thread. `focus_segment()`
  finds the longest span of a comment that names only *this* fight's robots: whole
  comment, else a paragraph, else a run of sentences. It changes the **unit** being
  filtered, not the filters.
- **Two safety gates that never loosen.** Reddit threads are the real thing: one of
  our three is a sustained sexual joke, `[deleted]` bodies arrive as literal text, and
  a search for one bot surfaces its other fights. `is_showable()` drops explicit
  language, deleted bodies and junk lengths; `names_a_rival()` demotes a comment
  naming a robot not in *this* fight. Filtering ~45% of a discovery scrape is normal.
  The profanity check runs on the **whole body first**, so a clean sentence can never
  escape an unusable comment.
- **Prediction labels are cached at scrape time.** One model call per 20 comments
  assigns `pick` / `phase` / `kind`, written into `comments/<clip>.json`. That is why
  the crowd card costs no re-judge, and why re-judging never re-pays for labels. A
  `pick` naming a robot the comment never mentions is voided in Python.
- **Exchanges.** `pair_exchanges()` uses the flattened parent/child links to find
  two-person arguments and replays them in sequence over the fight.
- **No username ever touches disk.** `author_hash()` salts and truncates at scrape
  time, and *refuses to run* without a salt held outside the repo rather than emit a
  hash reversible by trying a candidate list. Records carry an opaque token used only
  for exchange pairing. The HUD credits `r/battlebots`.

### Cost discipline

Billing is per record, so `num_of_posts` and `limit_per_input` are pinned rather than
left null, `POSTS_FOR_COMMENTS` caps thread expansion at 3, and two flags exist purely
to avoid re-scraping: `--reclassify` re-runs labels over a pool already on disk, and
`--backfill-dates` adds timestamps by merging **only** `{comment_id → created_utc}`
into existing records — so a re-scrape that comes back thinner cannot damage a good
pool. A scrape returning zero rows refuses to overwrite an existing file, because the
committed timelines reference those exact strings.

### Where we would take it next

Honest about what is not built yet:

- **YouTube comments as a second platform.** The adapter already has a `youtube`
  dataset slot, deliberately unset. Era B ingests any YouTube fight; those videos have
  their own comment threads, and a fight watched on two platforms has two crowds worth
  contrasting.
- **Replace the hand-pinned `FIGHT_CARD` with a real lookup.** Right now three clips
  map to one thread by hand. Bright Data's SERP API could find the episode discussion
  thread from the bot names and air date, which is what makes the crowd layer work for
  *any* fight rather than the three we curated.
- **Use `created_utc` for real phase detection.** We store it now but still classify
  pre/post-fight with a model. Comparing the comment's actual timestamp against the
  episode air time is deterministic, free, and strictly better.
- **Scheduled scrapes for a live event.** The pipeline is batch. Polling a live
  discussion thread during an episode would let the HUD show the crowd reacting at
  roughly the speed they actually reacted — the pinned/discovery split already models
  before-and-after, so the shape is there.
- **Move the roster scrape onto Bright Data.** `roster.py` fetches the Pro League page
  with `requests`, which works only because the data is in the server HTML. That is
  luck, not architecture.

Everything Bright Data-specific is in **one function**, `brightdata_adapter()` in
[scrape_comments.py](backend/scrape_comments.py), under an ADAPTER banner with the
exact request shapes documented. `--mock` keeps the rest of the pipeline unblocked
without a key.

---

## How it fits together

Two independent halves joined by **one JSON contract**. The backend turns a video into
`timelines/<clip>.json`; the frontend plays the clip and animates the HUD from that
file, synced to video time. No websockets, no build step, no framework.

```
video ──► extract_frames.py ──► frames/ ──► analyze.py ──► timelines/<clip>.json
                                              ▲                     │
                       comments/<clip>.json ──┘                     ▼
                        (Bright Data scrape)                frontend/index.html
```

LLMs do vision judging and language only. Every join, every match, every statistic is
deterministic code, so the same frames always produce the same timeline.

## Run it

```bash
python3 backend/serve.py
```

- **http://localhost:40911/frontend/index.html?demo=1** — no API key, no clip file
- **`?clip=synthfight`** — a generated test clip, real `<video>`, no third-party content

Serve from the **repo root**: the page loads `../timelines/` and `../comments/`
relative to itself. A missing clip falls back to a placeholder arena, so the frontend
demos on its own.

Keys: `space` start / pause · `←→` seek, or change fight on the title card ·
`↑↓` move between picker rows · `esc` pause menu · `r` replay · `h` home ·
`c` CRT filter · `g` rainbow bars

### A clip end to end

```bash
pip install -r backend/requirements.txt

python backend/extract_frames.py fight1.mp4                     # 2 fps, 768px
python backend/transcribe.py fight1 --bots "Manta,Skorpios"     # broadcast commentary
python backend/scrape_comments.py fight1 "manta skorpios" --mock
python backend/analyze.py fight1.mp4                            # -> timelines/
```

Drop `--mock` and set `BRIGHTDATA_API_KEY` for real crowd data. `analyze.py` runs on
`--backend api` (Anthropic), `--backend cli` (your Claude subscription, no key), or
`--backend openai` — only the model call changes, so every backend emits the same
contract.

### Any YouTube fight

```bash
python backend/ingest.py "<url>" --name my-fight --start 187 --duration 32.5
```

## The JSON contract

```json
{
  "clip": "manta-skorpios.mp4",
  "bots": {"left": "Manta", "right": "Skorpios"},
  "events": [
    {"t": 8.0, "left_hp": 92, "right_hp": 71,
     "caption": "Skorpios armour panel torn off",
     "hit": {"by": "left", "weapon": "drum spinner", "clean": true,
             "at": [0.42, 0.48], "sev": "heavy"},
     "fan_comment": "NOT THE ARMOUR AGAIN"},
    {"t": 41.0, "left_hp": 88, "right_hp": 0,
     "caption": "Skorpios counted out", "drain": "right", "ko": "right"}
  ]
}
```

`hit` carries only what the model can **see** — who landed it, the weapon, whether it
was clean, where it landed, how hard. Damage and victim are *derived* from the hp
deltas by the frontend, never stored: they are pure functions of two adjacent events,
and storing them twice is how the hit count once ended up with three different answers.
`drain` marks an hp drop that is a knockout count rather than a blow, so a count-out
registers zero hits.

## Footage, licensing and data

**This is an unaffiliated fan project. It is not endorsed by or connected to
BattleBots Inc.** Footage © BattleBots Inc.

The [`LICENSE`](LICENSE) covers this project's own code and nothing else — it conveys
no rights in BattleBots footage or marks. The pipeline expects you to **supply your own
inputs**: `ingest.py` takes a URL you provide, and nothing here grants you the right to
redistribute what it downloads.

> **No video is committed to this repository, and none is in git history.** The clips
> the live demo plays are served from separate object storage behind `CLIP_BASE_URL`
> (`frontend/config.js`), never from the deployment — `scripts/check_no_video.sh` fails
> the build if a video file reaches the bundle.

No Reddit usernames are stored or displayed anywhere. Where the pipeline needs to tell
two commenters apart it uses a salted hash, with the salt held outside the repository.
[`COMPLIANCE.md`](COMPLIANCE.md) is the full posture — read it before changing anything
that touches the footage, the scraped data, or where the site is hosted.

Takedowns: **abuse@gameover.fyi**, removed within 24 hours.

## Restyling

Every colour, font and size is a CSS variable in the `:root` block at the top of
[frontend/index.html](frontend/index.html). Nothing below that block needs editing to
reskin it.
