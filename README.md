# GAMEOVER

A vision model watches BattleBots clips and drives a retro arcade fighting-game HUD:
health bars, damage captions, fan comments, screen shake, K.O.

## Footage, licensing and data

**This is an unaffiliated fan project. It is not endorsed by or connected to
BattleBots Inc.** Footage © BattleBots Inc.

The [`LICENSE`](LICENSE) covers this project's own code and nothing else — it conveys
no rights in BattleBots footage or marks. The pipeline expects you to **supply your own
inputs**: `ingest.py` takes a URL you provide, and nothing here grants you the right to
redistribute what it downloads. `?clip=synthfight` is a generated test clip with no
third-party content in it, and `?demo=1` needs no video at all, so both the HUD and the
whole judging pipeline can be developed without touching anyone's footage.

> **No video is committed to this repository, and none is in git history.** The clips the
> live demo plays are served from separate object storage behind `CLIP_BASE_URL`
> (`frontend/config.js`), never from the deployment — `scripts/check_no_video.sh` fails
> the build if a video file reaches the bundle. [`COMPLIANCE.md`](COMPLIANCE.md) records
> the migration, the order it had to happen in, and what is still open.

No Reddit usernames are stored or displayed anywhere. Where the pipeline needs to tell
two commenters apart it uses a salted hash, with the salt held outside the repository —
see `crowd.author_hash()`. Read [`COMPLIANCE.md`](COMPLIANCE.md) before changing anything
that touches the footage, the scraped data, or where the site is hosted.

Takedowns: **abuse@gameover.fyi**, removed within 24 hours.

Two independent halves joined by **one JSON contract**. The backend turns a video
into `timelines/<clip>.json`; the frontend plays the clip and animates the HUD from
that file, synced to video time. No websockets, no build step, no framework.

```
video ──► extract_frames.py ──► frames/ ──► analyze.py ──► timelines/<clip>.json
                                              ▲                     │
                              comments/<clip>.json                  ▼
                              (Bright Data scrape)          frontend/index.html
```

## Run the demo (no API key needed)

```bash
python3 backend/serve.py
```

Then open **http://localhost:40911/frontend/index.html?demo=1** — press any key.
Drop the `?demo=1` and you get the synthetic test clip (`?clip=synthfight`) instead,
which is the default when no clip is named.

Serve from the **repo root**: the page loads `../clips/`, `../timelines/` and
`../comments/` relative to itself. If the clip file is missing the HUD still runs
against a placeholder arena, so the frontend is demo-able on its own.

Keys: `any` start · `r` replay · `c` CRT filter · `g` rainbow bars

## Sharing it

Deploy the public URL and send that — it works for anyone, anywhere:

```bash
vercel --prod
```

Static deploy, no build step and no server runtime: the page only fetches JSON and an
mp4. `vercel.json` rewrites `/` onto the HUD so the link is a bare domain (the query
string survives, so `/?demo=1` still works), and `.vercelignore` keeps `backend/` off
the public site. Pushing to `main` redeploys.

For a local LAN link, `python3 backend/serve.py` binds all interfaces on port 40911 —
use it rather than `python -m http.server`, which renders a browsable directory listing
and happily hands out `.env` and `.git/`. Keys in `.env` are live — `backend/config.py`
reads it — so blocking dotfiles is what keeps that from being a leak.

## Era A — a curated clip end to end

```bash
pip install -r backend/requirements.txt

# put your clip at clips/fight1.mp4
python backend/extract_frames.py fight1.mp4                        # 2 fps, 768px
python backend/transcribe.py fight1 --bots "Tombstone,Witch Doctor"  # commentary
python backend/scrape_comments.py fight1 "tombstone witch doctor" --mock
python backend/analyze.py fight1.mp4                               # -> timelines/fight1.json
```

Open **http://localhost:40911/frontend/index.html?clip=fight1**.

### Which judging backend

`analyze.py` needs an `ANTHROPIC_API_KEY` (from `.env` or the shell) by default. To
run on your Claude subscription instead, with no key at all:

```bash
python backend/analyze.py fight1.mp4 --backend cli
```

That shells out to `claude -p`. It works, but each call re-sends Claude Code's whole
system prompt, so it's roughly 20× the tokens and several times slower than the API
path — about 2.5 minutes for a 45s clip — and it spends the same quota you need for
coding. Good for a demo run, wrong for a long clip.

For real fan chatter drop `--mock` and set a Bright Data key (`BRIGHTDATA_API_KEY` or
`BRIGHTDATA_KEY`, either spelling). Everything Bright Data-specific lives in one
`brightdata_adapter()` function in [scrape_comments.py](backend/scrape_comments.py) —
marked with an ADAPTER banner.

## Era B — any YouTube fight

```bash
python backend/ingest.py "https://www.youtube.com/watch?v=..."
```

Downloads at ≤720p, caps to the first 120s, runs the whole pipeline and prints the
URL to open. The title screen also has a URL box that shows you this exact command.

## The JSON contract

```json
{
  "clip": "fight1.mp4",
  "bots": {"left": "Tombstone", "right": "Witch Doctor"},
  "events": [
    {"t": 0.0, "left_hp": 100, "right_hp": 100, "caption": ""},
    {"t": 8.0, "left_hp": 92, "right_hp": 71,
     "caption": "Witch Doctor armour panel torn off",
     "hit": {"by": "left", "weapon": "vertical spinner", "clean": true,
             "at": [0.42, 0.48]},
     "fan_comment": "NOT THE ARMOUR AGAIN"},
    {"t": 34.0, "left_hp": 88, "right_hp": 12,
     "caption": "Witch Doctor immobile, count begins", "drain": "right"},
    {"t": 41.0, "left_hp": 88, "right_hp": 0,
     "caption": "Witch Doctor counted out", "drain": "right", "ko": "right"}
  ]
}
```

Events sorted by `t`; hp are integers 0–100 that never increase; `caption` is max
6 words; `fan_comment`, `hit`, `drain` and `ko` are optional. Era B falls back to
`Bot A` / `Bot B` when names aren't legible in the broadcast graphics.

`drain` marks an hp drop that is a knockout **count**, not a blow, so a count-out
registers zero hits. `hit` carries only what the model can see — who landed it, the
weapon, whether it was clean, and optionally `at`, the impact point normalised 0–1
from the frame's top-left. Damage, victim and tier are derived from the hp deltas by
the frontend, never stored.

The model only ever judges frames. Thinning, hp clamping, KO detection and the
comment join are deterministic Python in [analyze.py](backend/analyze.py), so the
same frames always produce the same timeline.

## Restyling the HUD

Every colour, font and size is a CSS variable in the `:root` block at the top of
[frontend/index.html](frontend/index.html). Nothing below that block needs editing
to reskin it.
