# CLAUDE.md — gameover

Hackathon project. A vision model watches robot-combat clips and drives a retro
arcade fighting-game HUD. Read this before changing anything.

## Architecture — do not deviate

Two independent halves joined by **one JSON contract**, `timelines/<clip>.json`.

- **Backend (Python)** turns a video into that JSON via the Anthropic API.
- **Frontend (single HTML page, no build step)** plays the clip and animates the
  HUD from that JSON, synced to video time. **No websockets.**
- LLMs do vision judging and language only. All joining, matching and stats are
  deterministic code.
- No tests, no CI, no TypeScript, no frameworks. Core stays around ~700 lines.

```json
{
  "clip": "fight1.mp4",
  "bots": {"left": "Tombstone", "right": "Witch Doctor"},
  "events": [
    {"t": 8.0, "left_hp": 92, "right_hp": 71,
     "caption": "Witch Doctor armour panel torn off",
     "fan_comment": "NOT THE ARMOUR AGAIN"},
    {"t": 41.0, "left_hp": 88, "right_hp": 0,
     "caption": "Witch Doctor immobile, drive dead", "ko": "right"}
  ]
}
```

Events sorted by `t`; hp integers 0–100 that **never increase**; `caption` max 6
words; `fan_comment` and `ko` optional. Era B falls back to `Bot A` / `Bot B` when
names aren't legible in the broadcast graphics.

Model for all API calls: **`claude-sonnet-5`**.

`analyze.py` also takes `--backend cli` (shells to `claude -p`, uses your Claude
subscription) and `--backend openai` (`OPENAI_MODEL`, default `gpt-5.5`). Only the
model call changes — the prompt, hp clamp, thinning, KO detection and comment join
are shared, so every backend emits the same JSON contract. The demo clips were
judged on `--backend openai` because only an `OPENAI_API_KEY` was on hand.

## Eras

- **Era A** — polished demo on pre-selected clips. Must work. Built first.
- **Era B** — same pipeline generalised to any YouTube URL via `ingest.py`.
  Stretch goal; only touch it once Era A runs end to end.

## Commands

Python deps live in `.venv/` (gitignored). Use `.venv/bin/python`, not system
python3 — the latter has no `anthropic`. Set up with
`python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt`.

```bash
# demo mode — no API key, no clip file needed
python3 backend/serve.py                        # port 40911, blocks dotfiles
# -> http://localhost:40911/frontend/index.html?demo=1

# synthetic clip — a REAL <video> to develop the HUD against, no API key
bash backend/make_test_clip.sh
# -> http://localhost:40911/frontend/index.html?clip=synthfight

# era A, one clip
python backend/extract_frames.py fight1.mp4                        # 0.5 fps, 768px
python backend/scrape_comments.py fight1 "tombstone witch doctor" --mock
python backend/analyze.py fight1.mp4                               # -> timelines/
python backend/analyze.py fight1.mp4 --backend cli                 # no API key needed

# era B, any fight video
python backend/ingest.py "https://www.youtube.com/watch?v=..."

# era B, one fight cut out of a multi-fight compilation. The download is cached
# under clips/.raw/, so the 2nd and 3rd fights cost no bandwidth.
python backend/ingest.py "<url>" --name manta-skorpios \
    --start 187 --duration 31 --bots "Manta,Skorpios"
```

The three demo fights all come from one video, `youtube.com/watch?v=rC__2ZOQhc4`:

| clip | `--start` | `--duration` | ends on |
|---|---|---|---|
| `jackpot-copperhead`  |  23 | 144 | TAP OUT : 152sec |
| `manta-skorpios`      | 187 |  31 | KNOCKOUT : 24sec |
| `madcatter-tombstone` | 271 |  79 | KNOCKOUT : 72sec |

Keys in the page: `any` start · `r` replay · `c` CRT filter · `g` rainbow bars.

## Sharing it — use the public URL, not the LAN

**Send people the Vercel URL.** The LAN link only ever worked for devices on the same
wifi with `serve.py` still running; anyone off the network gets nothing, which is not
a bug you can debug locally.

```bash
vercel --prod        # from the repo root — prints the live URL
```

The site is a pure static deploy: no build step, no serverless functions, no API key
in the browser. Three pieces make it work, and none of them should be "cleaned up":

- **`vercel.json`** rewrites `/` → `/frontend/index.html`, so the shared link is a bare
  domain. Vercel preserves the query string through the rewrite, so `/?demo=1` still
  arrives as `location.search`. The deploy root stays the **repo root** — `index.html`
  reaches up to `../clips/`, `../timelines/` and `../comments/`.
- **`.vercelignore`** keeps `.env`, `backend/`, `frames/`, `.venv/` and `CLAUDE.md` off
  the public site. Without it, static hosting would serve `/backend/analyze.py` as
  readable plaintext to anyone who guessed the path. Note it **replaces** `.gitignore`
  for CLI uploads rather than adding to it, which is why `.env` is listed explicitly —
  being gitignored is not enough to keep a file out of a `vercel --prod` upload.
- **`clips/synthfight.mp4` is the one clip committed to git** (`.gitignore` is
  `clips/*` + a `!` exception). A git-connected build only sees committed files, so
  any new clip you want on the public site needs its own exception.

Pushing to `main` on the private GitHub repo auto-deploys. If a shared link ever
returns **401**, it is Vercel Deployment Protection, not your code — turn it off under
Project → Settings → Deployment Protection.

### Local dev server

Still the fastest loop for editing the HUD, and unaffected by any of the above:

```bash
python3 backend/serve.py     # -> http://localhost:40911/frontend/index.html?clip=synthfight
```

- **Run the server from a human terminal, not from a Claude Code background task.**
  Agent-spawned processes get cleaned up between sessions; yours survives, and the
  request log tells you whether a request actually landed.
- **Serve with `backend/serve.py`, never bare `python -m http.server`.** The bare
  version has no auth, renders a browsable directory listing, and happily hands out
  `.env` and `.git/` to anyone on the wifi — this already happened once during
  development. `serve.py` is the same static server with dotfiles and directory
  listings 404'd. `backend/config.py` does read `.env`, so keys in the repo are live
  — `serve.py` blocking dotfiles is what keeps that from being a leak. Exporting in
  your shell instead still works and always wins over the file.
- Edits are live on refresh; no restart needed. Timeline/comment fetches use
  `no-store`, but the browser caches `index.html`, so hard-refresh (Cmd+Shift+R)
  after editing the page itself.

## Gotchas worth not rediscovering

- **Two judging backends.** `--backend api` (default) uses the SDK and needs an
  `ANTHROPIC_API_KEY`. `--backend cli` shells out to `claude -p`, which bills your
  Claude subscription and needs no key — verified working end to end. The catch is
  weight: every `claude -p` call re-sends Claude Code's own system prompt and tool
  definitions, so one 2-frame batch cost ~87k tokens and ~10s versus roughly 4k
  tokens direct. A 45s clip is 8 batches / ~2.5 min; a 120s Era B clip is ~20. It
  draws down the same quota you need for coding, so prefer the API backend for
  anything long.
- **Keys come from `.env` or the shell.** `backend/config.py` loads `.env` (real env
  vars win) and accepts either `BRIGHTDATA_API_KEY` or `BRIGHTDATA_KEY` — the two
  spellings already diverged once and silently produced "no key found".
- **The vision model is stateless between calls.** `analyze.py` sends 2–3 frames per
  call and must include the running hp state in the message, or per-call guesses
  oscillate and the monotonic clamp flattens the timeline into noise.
- **Serve from the repo root.** `index.html` reaches up to `../clips/`,
  `../timelines/` and `../comments/`. Serving `frontend/` alone breaks it.
- **No `?clip=` defaults to `synthfight`**, so a bare URL is a working share link.
  There is no `timelines/fight1.json` — `fight1` is a name used only by `demo/`.
- **Frame N (1-indexed) is at t = (N-1) × 2.0s**, from the 0.5 fps extraction.
- **All model output is untrusted.** Thinning, hp clamping, KO detection (first hp
  to hit 0) and the comment join all happen in Python so the same frames always
  produce the same timeline.
- **`ingest.py` cuts a window, it does not take the head of the video.** `--start` /
  `--duration` pick the fight; the full download is cached at `clips/.raw/<slug>.mp4`
  and reused, so re-cutting is free. That dir is dotted (`serve.py` 404s dotfiles) and
  listed in `.vercelignore` — without that entry a `vercel --prod` would upload the
  whole 34MB source alongside the clips.
- **`yt-dlp` is not on PATH**, only in `.venv/bin`. `ingest.tool()` resolves tools
  from the running interpreter's own bin dir first, so `.venv/bin/python
  backend/ingest.py` works without activating the venv. Don't replace it with a bare
  `shutil.which()`; that was what made ingest exit with "yt-dlp not found".
- **Bright Data replies in NDJSON, not a JSON array.** One record per line, and a
  single-record reply is a bare dict. `resp.json()` plus a `.get("data")` fallback
  silently yields zero comments on a perfectly healthy HTTP 200 — `_parse_payload()`
  handles all three shapes. If comments go empty, print `resp.text` before assuming
  the key or dataset id is wrong.
- **Scraped comments are NOT safe to show unfiltered.** Reddit threads are the
  real thing: the MaD CaTTer thread is a sustained sexual joke, `[deleted]` bodies
  appear as literal text, and a search for one bot surfaces its *other* fights.
  Two deterministic gates handle it — `is_showable()` in `scrape_comments.py`
  (drops explicit language, deleted bodies, junk lengths) and `names_a_rival()` in
  `analyze.py` (a comment naming a bot that is not in THIS fight is last-resort
  only, so a SawBlaze quote never lands on a Tombstone hit). Filtering ~45% of a
  scrape is normal. Never loosen these for a public build.
- **Two-step comment scrape.** `discover_by=subreddit_url` finds posts, then the
  Reddit-Comments dataset (`gd_lvzdpsdlw09j6t702`) expands the top
  `POSTS_FOR_COMMENTS` of them into real threaded reactions. Post *titles* alone
  read like headlines ("Season 6 Rumor Mill") and make a poor fan comment.
  `GAMEOVER_THREADED=0` falls back to titles. `GET /datasets/list` (undocumented)
  returns every dataset id on the account.
- **`serve.py` implements HTTP Range itself.** `SimpleHTTPRequestHandler` ignores
  the header and answers 200 with the whole file, so the browser cannot seek and
  `currentTime` snaps back to 0. Vercel serves ranges already; this only ever bit
  local dev, which is where demos get rehearsed.
- **Everything Bright Data-specific is in one `brightdata_adapter()` function** in
  `scrape_comments.py`, under an ADAPTER banner. The dataset IDs there are
  placeholders. `--mock` keeps the pipeline unblocked.
- **A missing clip file is fine.** The HUD falls back to a placeholder arena driven
  by a rAF clock, so the frontend demos without any video present.
- **`video.play()` can fail without rejecting.** Autoplay policies may leave the
  video paused while `play()` resolves fine, which froze the whole HUD at t=0 —
  `now()` returns `currentTime`, so nothing ever advanced. `watchdog()` in
  `index.html` now checks 1.2s after start whether the clock actually moved, retries
  muted (showing a click-to-unmute hint), then falls back to the virtual clock. Do
  not remove it; the failure is silent and looks like "the HUD is just broken".
- **Test the video path, not just `?demo=1`.** Demo mode without a clip runs the rAF
  fallback, so it exercises none of the video sync. `?clip=synthfight` is the cheap
  way to test the real path — the burned-in clock in the frame makes desync visible.
- **Verifying in a headless browser is misleading.** `requestAnimationFrame` and
  media playback stall when nothing is painting, so state reads between JS calls go
  stale and look like engine bugs. Force a paint (take a screenshot) before trusting
  a DOM read.

## Restyling

Every colour, font and size is a CSS variable in the `:root` block at the top of
`frontend/index.html`. Reskinning should not require touching anything below that
block.

**The top-left of the frame belongs to the broadcaster.** Real fight footage burns
in its own graphics there — the match clock and a `KNOCKOUT : 72sec` banner that
runs from the left edge to roughly 60% of the width and a quarter of the way down.
Anything the HUD puts in that corner is unreadable on top of it. So the health
bars, names, hp numbers and fan comments live in **one bottom row** (left stack ·
caption · right stack), and the only top-anchored readouts (`#hits`, `#muted`) hug
the **right** edge at `--safe-top`. Raise `--safe-top` if a clip's band spans the
full width; do not move the bars back up to reclaim the space.
