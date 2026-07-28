# GAMEOVER

A vision model watches BattleBots clips and drives a retro arcade fighting-game HUD:
health bars, damage captions, fan comments, screen shake, K.O.

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
and happily hands out `.env` and `.git/`. Better still, keep keys out of the folder:
nothing here reads dotenv files, so `export ANTHROPIC_API_KEY=...` is enough.

## Era A — a curated clip end to end

```bash
pip install -r backend/requirements.txt
export ANTHROPIC_API_KEY=...

# put your clip at clips/fight1.mp4
python backend/extract_frames.py fight1.mp4                        # 0.5 fps, 768px
python backend/scrape_comments.py fight1 "tombstone witch doctor" --mock
python backend/analyze.py fight1.mp4                               # -> timelines/fight1.json
```

Open **http://localhost:40911/frontend/index.html?clip=fight1**.

For real fan chatter drop `--mock` and set `BRIGHTDATA_API_KEY`. Everything Bright
Data-specific lives in one `brightdata_adapter()` function in
[scrape_comments.py](backend/scrape_comments.py) — marked with an ADAPTER banner.

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
     "fan_comment": "NOT THE ARMOUR AGAIN"},
    {"t": 41.0, "left_hp": 88, "right_hp": 0,
     "caption": "Witch Doctor immobile, drive dead", "ko": "right"}
  ]
}
```

Events sorted by `t`; hp are integers 0–100 that never increase; `caption` is max
6 words; `fan_comment` and `ko` are optional. Era B falls back to `Bot A` / `Bot B`
when names aren't legible in the broadcast graphics.

The model only ever judges frames. Thinning, hp clamping, KO detection and the
comment join are deterministic Python in [analyze.py](backend/analyze.py), so the
same frames always produce the same timeline.

## Restyling the HUD

Every colour, font and size is a CSS variable in the `:root` block at the top of
[frontend/index.html](frontend/index.html). Nothing below that block needs editing
to reskin it.
