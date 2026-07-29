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
     "hit": {"by": "left", "weapon": "vertical spinner", "clean": true},
     "fan_comment": "NOT THE ARMOUR AGAIN"},
    {"t": 41.0, "left_hp": 88, "right_hp": 0,
     "caption": "Witch Doctor immobile, drive dead", "ko": "right"}
  ]
}
```

Events sorted by `t`; hp integers 0–100 that **never increase**; `caption` max 6
words; `fan_comment`, `hit` and `ko` optional. Era B falls back to `Bot A` / `Bot B`
when names aren't legible in the broadcast graphics.

`hit` carries **only what the model can see**: `by` (the side that LANDED it),
`weapon` (≤3 words or null) and `clean` (false = wall, hazard, fall, self-inflicted).
Damage, victim and tier are deliberately **not** stored — they are pure functions of
two adjacent events, and the frontend must derive them anyway for the synthetic
timelines that have no `hit` at all. Storing them twice is how the hit count ended up
with three different answers in the first place.

`comments/<clip>.json` is the second file the page fetches — a flat array, every
key past the first three optional so the old three-key files still work:

```json
{"text": "As much as Skorpios is my goat, Manta is going to kick their ass",
 "source": "reddit", "url": "https://reddit.com/…/ovwnh4u/",
 "author": "[redacted]", "score": 13,
 "id": "ovwnh4u", "parent": "", "post": "1up1lxt", "pinned": true,
 "phase": "pre", "kind": "prediction", "pick": "manta", "rival": false, "ex": "1a"}
```

`pick` is a normalised bot **key** (`[^a-z0-9]` stripped), never `left`/`right` —
sides belong to the timeline and a re-judge can flip them, but a name key
survives that and absorbs `MaDCaTTer` / `Madcatter` drift. `ex` marks the two
halves of a reply chain (`1a` parent, `1b` reply). `rival: true` still counts in
the sentiment tally but is never shown on screen.

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

## Orchestration — parallelise, and loop on quality

This is a hackathon with a real prize on the line, so **reach for subagents and
workflows whenever the work genuinely forks**. Judgement call, not a mandate: the
win comes from covering more ground and from iterating on output quality, not from
spawning agents for their own sake.

Worth orchestrating:

- **Independent reads that don't share context.** Auditing `analyze.py`, the HUD
  and the scrape gates at once; sweeping several clips or several timelines;
  checking a change against every fight in the picker. Each agent reads its own
  slice and reports a conclusion, so the context cost is paid once per slice
  rather than once per file in one window.
- **Loops that improve an artifact.** Judging quality is the whole product, and it
  is the thing most worth iterating on: generate → critique → regenerate until a
  pass comes back with nothing new. The same shape fits caption wording, sprite
  rows in the `ART` table, and fan-comment selection.
- **Adversarial verification before trusting a result.** Model output is untrusted
  by design here. A finding about a timeline — "the KO is on the wrong side", "this
  hit is misattributed" — is worth a second, independent agent trying to refute it
  before anyone spends a re-judge on it.

Not worth it: anything where the agents would all have to read the same files to
start (that duplicates context rather than dividing it), and single mechanical
edits. One judgement worth keeping in mind — a full three-way merge of this repo's
branches was **faster to do inline** than to farm out, because every conflict
needed the same three files in one head.

Cost note: a re-judge is real money and ~15–30 min of wall clock, so parallelise
the *analysis* freely and the *API-spending* runs deliberately.

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
python backend/analyze.py fight1.mp4 --bots "Manta,Skorpios"       # pin the card

# a better comments file into an EXISTING timeline — no frames, no model, free
python backend/analyze.py manta-skorpios --rejoin --bots "Manta,Skorpios"

# era B, any fight video
python backend/ingest.py "https://www.youtube.com/watch?v=..."

# era B, one fight cut out of a multi-fight compilation. The download is cached
# under clips/.raw/, so the 2nd and 3rd fights cost no bandwidth.
python backend/ingest.py "<url>" --name manta-skorpios \
    --start 187 --duration 31 --bots "Manta,Skorpios"
```

The three demo fights all come from one video, `youtube.com/watch?v=rC__2ZOQhc4`.
**Always re-judge them with `--bots`, and with `--ko` where the table gives one.**
Name detection depends on whether a lower-third happens to be legible in the sampled
frames, and a re-run that came back `Manta vs Skorpios` once will happily return
`Bot A vs Bot B` the next time. Worse, an unpinned card also switches off the "the
ONLY two competitors are X and Y" line in `identity_note()`, which is the thing
stopping the model captioning sponsor decals as robots — a run with a broken
`--bots` came back `Bot A vs Horizon`, and Horizon is a sponsor.

| clip | `--start` | `--duration` | `--bots` (left,right) | `--ko` | ends on |
|---|---|---|---|---|---|
| `jackpot-copperhead`  |  23 | 144 | `Copperhead,Jackpot` | —      | TAP OUT : 152sec |
| `manta-skorpios`      | 187 |  31 | `Manta,Skorpios`     | `left` | KNOCKOUT : 24sec |
| `madcatter-tombstone` | 271 |  79 | `MaDCaTTer,Tombstone`| —      | KNOCKOUT : 72sec |

`manta-skorpios` **needs** `--ko left`: ~6 of its 16 frames are crowd shots and Manta
is flat on the floor from t≈4s, so the model reads the sides backwards and does it
*consistently* — the damage cross-check agrees with the wrong answer, so only the
explicit flag fixes it.

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
- **Clips are committed to git one by one** (`.gitignore` is `clips/*` plus a `!`
  exception per clip — currently `synthfight` and the three real fights). A
  git-connected build only sees committed files, so any new clip you want on the
  public site needs its own exception.

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
- **The model never emits hp — it rates a damage word.** `prompt.txt` asks for
  `none`/`glance`/`solid`/`heavy`/`catastrophic` per bot per frame; `SEVERITY` in
  `analyze.py` turns that into 0/4/12/22/35 points. Asking for absolute hp instead is
  what the pipeline used to do, and the model nudged the bar down 3–5 points a frame to
  signal "time passed" — 23 events with only 2 clearing the shake threshold, a HUD that
  drains but never hits. With a ladder, a 3-point delta is not representable.
- **The vision model is stateless between calls, and the state it needs is what it
  already said.** Each batch is led by the previous batch's last frame as unjudged
  context (otherwise every 3rd frame has nothing to diff "new damage" against) and
  carries the last two reported hits in the footer. Without that the model narrates one
  fire as fresh damage on ten consecutive frames. That message is `footer()`, shared by
  all three backends — it also re-states who the bots are and what they look like
  (`identity_note()`) and the `hit` rule, because a field explained only in
  `prompt.txt` gets honoured for a batch or two and then quietly forgotten for the
  rest of a long clip. There is deliberately no running-hp line: the model never
  emits hp.
- **`pay()` overspending is expected, not a bug.** The model over-fires — a fire
  sequence alone can bill 150+ points against a 100-point bar — so `pay()` spends a
  fixed budget (`KO_BUDGET`/`LIVE_BUDGET`) on the most severe moments and zeroes the
  rest. Do **not** "fix" it by scaling every hit down to fit; that reconstructs the
  3–5 point drip exactly. Budgets are under 100 on purpose: a bot bottoms out around
  hp 30 and the only route to 0 is the model's `finish` flag. Zeroed hits keep their
  captions, so the HUD still has something to type between real hits.
- **The ladder and the HUD's `TIERS` table are one design in two halves.** `SEVERITY`
  scores glance 4 / solid 12 / heavy 22 / catastrophic 35, and `TIERS` in `index.html`
  bands at 1 / 10 / 20 / 30, so each rung lands squarely in one tier. The backend owns
  *how much* damage, the frontend owns *how it looks*; they meet only at the hp delta.
  Move a rung on either side without the other and a whole category of hit silently
  changes colour, size and whether it shakes the screen.
- **One hit = one bot losing armour at one moment**, so an exchange that damages both
  bots is TWO hits. This lives in exactly one function, `deriveHits()` in
  `index.html`, which runs once at load; `fire()`, the `#hits` readout and the
  end-of-fight breakdown all read the list it returns. Before that there were three
  separate answers — the live counter said 22 on `madcatter-tombstone`, the end card
  said 24, and a backward scrub reset it to 0 and never recounted. Do not re-derive
  hits inline anywhere; if the HUD total and the breakdown ever disagree again,
  something did.
- **Damage, victim and tier are derived, never stored.** The timeline's `hit` object
  carries only what the model can see (`by`, `weapon`, `clean`). `deriveHits()` works
  with no `hit` field at all — `synthfight` and `demo/fight1.json` are synthetic and
  are never re-judged, which makes them the regression test for the fallback path.
  Model data only ever *enriches* a hit record that the hp deltas already produced.
- **A transient's lifetime lives in its CSS variable, not in a JS timer.** `lifeMs()`
  reads `--hm-life` / `--strike-life` / `--comment-life` / `--exchange-gap` so the
  removal timer and the animation can't disagree; hard-coding a second copy in JS
  is how the hitmarkers first ended up vanishing mid-animation. It is deliberately
  not `animationend` — reduced motion kills the animation and the event with it.
  Every one of those timers must also be cleared in `hideComments()`: a dwell
  timer left running across a backward scrub fires later and hides a comment shown
  *after* the scrub, and an orphaned exchange reply lands with no parent on screen.
- **The comments file is a second, richer source the HUD reads at runtime.** The
  timeline contract still carries only `fan_comment` **text**; `credits[norm(text)]`
  in `index.html` looks that string back up in `comments/<clip>.json` to recover
  the author, the source and the prediction label. That indirection is the whole
  reason attribution, the pre-fight `#preds` block and the `04 / CROWD` card cost
  no re-judge — the contract never had to grow a field. It also means a re-scrape
  that drops a string a timeline still references degrades that one comment to
  "no author"; run `--rejoin` straight after a scrape.
- **`loserSide()` is the ONE definition of who lost**, the same way `deriveHits()`
  is the one definition of a hit — `finish()` and the crowd card must never
  disagree about the result. It reads the contract's `ko` first (set for a tap-out
  as much as a knockout, so `jackpot-copperhead` needs no special case despite its
  `TAP OUT` graphic) and falls back to final hp only when no event carries a
  finish flag. A genuine tie returns `null` rather than guessing.
- **Exchanges outrank single fan comments for a beat.** `scheduleExchanges()`
  prefers hits the backend's comment join left empty but will take an occupied one
  rather than not play at all; `fire()` gives the exchange precedence, so a
  displaced `fan_comment` is simply not shown, never shown twice.
- **Serve from the repo root.** `index.html` reaches up to `../clips/`,
  `../timelines/` and `../comments/`. Serving `frontend/` alone breaks it.
- **No `?clip=` defaults to `madcatter-tombstone`**, so a bare URL is a working share
  link that opens on a real fight. The title card carries a fight picker built from the
  `FIGHTS` array in `index.html`; each button just navigates to `?clip=<slug>`, so
  adding a clip is a one-line change. Any clip in that array must be committed (see the
  `.gitignore` `!` exceptions) or the public site will 404 it. `synthfight` is still
  reachable at `?clip=synthfight`.
- **A clip's slug is not its arena order.** `jackpot-copperhead` fights *Copperhead* on
  the left. The picker therefore labels each button from that clip's `bots` and only
  falls back to the slug if the timeline fetch fails — don't "simplify" it back to
  splitting the filename.
  There is no `timelines/fight1.json` — `fight1` is a name used only by `demo/`.
- **Picker buttons must `stopPropagation()`.** A window-level `click` listener starts
  the fight on any click, and `keydown` starts it on any key, so without that guard
  choosing a fight would also start the one already loaded.
- **Frame N (1-indexed) is at t = (N-1) × 2.0s**, from the 0.5 fps extraction.
- **All model output is untrusted.** Thinning, the severity→hp table, the `pay()`
  budget, KO detection (`finish_at()` — the first frame flagged `finish` in the last
  30% of the clip; an earlier flag is a misread and would truncate the fight) and the
  comment join all happen in Python so the same frames always produce the same
  timeline.
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
  Two deterministic gates handle it, both in `crowd.py` (re-exported from
  `scrape_comments.py` / `analyze.py`, which is where they used to live) —
  `is_showable()` drops explicit language, deleted bodies and junk lengths, and
  `names_a_rival()` keeps a comment naming a bot that is not in THIS fight to
  last-resort only, so a SawBlaze quote never lands on a Tombstone hit. Filtering
  ~45% of a discovery scrape is normal; ~80% of a fight-card scrape is also
  normal, because one card covers three matchups. Never loosen these.
- **The fight card is the primary source, and it is PINNED.** `FIGHT_CARD` in
  `scrape_comments.py` maps each Era A clip to its episode's pre-fight thread
  (all three demo clips are r/battlebots `1up1lxt`, Pro League Episode 2);
  `--post-url` does the same for Era B. Discovery can only ever find posts
  written *after* the fight, so predictions are unreachable without this — and
  discovery is a lottery that already lost: a keyword run for "mad catter
  tombstone" returned 14 rows of "Season 7 Rumor Mill" and 8 from a two-year-old
  SawBlaze fight, and nothing from the episode. Discovery stays on as the
  secondary pool for reactions, wrapped so a timeout can never cost the pinned
  pull. **A scrape that returns zero rows refuses to overwrite an existing
  file** — the committed timelines reference these exact strings by text.
- **One comment covers three fights, so route it, don't drop it.**
  `focus_segment()` in `crowd.py` picks the longest span of a comment that names
  only THIS fight's robots — whole comment, else a paragraph, else a run of
  sentences. Ellindsey's prediction is one paragraph per matchup over 600 chars,
  so `MAX_LEN=180` dropped it whole; "My money is on Copperhead, Manta, and
  Madcatter" names six robots, so `names_a_rival()` dropped it whole. Both are
  the best comments in the thread. This changes the UNIT being filtered, not the
  gates — and the profanity check still runs on the **whole body first**, so a
  clean sentence can never escape an unusable comment. Do not reorder that.
- **Replies are NESTED, not rows.** The comments dataset returns
  `parent_comment_id` empty on every row and hangs children off a `replies` list
  with a *different* schema (`reply_id` / `user_replying` / `reply`).
  `flatten_replies()` expands them, and without it `pair_exchanges()` has nothing
  to pair — the thread looks completely flat. Bodies are HTML-escaped and carry
  Reddit spoiler markup, so `clean_text()` runs before the gates.
- **Prediction labels are cached at SCRAPE time, never at judge time.**
  `crowd.classify()` asks one model call per 20 comments for `pick` / `phase` /
  `kind` and writes them into `comments/<slug>.json`. That is why the crowd card
  costs no re-judge, and why a re-judge never re-pays for the labels. All model
  output is validated in Python: a `pick` naming the *other* robot for a comment
  that never mentions it is voided, and every failure path leaves valid defaults.
  The tally, the percentages and the verdict are plain counting in the HUD.
- **Two-step comment scrape.** `discover_by=subreddit_url` finds posts, then the
  Reddit-Comments dataset (`gd_lvzdpsdlw09j6t702`) expands the top
  `POSTS_FOR_COMMENTS` of them into real threaded reactions. Post *titles* alone
  read like headlines ("Season 6 Rumor Mill") and make a poor fan comment.
  `GAMEOVER_THREADED=0` falls back to titles. `GET /datasets/list` (undocumented)
  returns every dataset id on the account. The URL-collection step takes **one**
  url per row — iterating `URL_FIELDS` inside the row loop made one row
  contribute two entries, so the `[:POSTS_FOR_COMMENTS]` slice only ever covered
  two distinct threads.
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
  a DOM read. Two corollaries that cost real time: `tick()` never advances on its own
  there, so drive the engine by calling `tick()` after setting `video.currentTime`;
  and a transient like `.hitmark` is long gone by the time a screenshot lands, so
  freeze it (`animation: none; opacity: 1`) rather than trying to catch it. Slowing
  the animation down does not work — it just stretches the fade-*in*, so the capture
  arrives while the element is still at `opacity: 0`.

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

The same rule constrains the hitmarkers. On-bar `.hitmark` bursts are anchored to the
core rows, so they are structurally incapable of reaching that corner. The full-stage
`#strike` crosshair is not — it is parked at `--strike-top` (54%) and nudged toward
the victim's half. If a clip's burned-in band runs taller, raise `--strike-top` and
`--safe-top` together; that is why both are variables.
