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

Events sorted by `t`; hp integers 0–100 that **never increase**; `caption` max 6
words; `fan_comment`, `hit`, `drain` and `ko` optional. Era B falls back to
`Bot A` / `Bot B` when names aren't legible in the broadcast graphics.

`drain` names the side whose hp drop on that event is a **knockout count-out, not a
blow**. `deriveHits()` skips it, so a count-out registers zero hits. An event may
carry `hit` or `drain`, never both — `validate()` enforces it.

`hit` carries **only what the model can see**: `by` (the side that LANDED it),
`weapon` (≤3 words or null), `clean` (false = wall, hazard, fall, self-inflicted) and
**`at`**, an optional `[x, y]` impact point normalised 0–1 from the frame's top-left.
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

`at` is **optional and must stay optional**: `validate()` takes the key set as a
subset, not an equality, so every timeline judged before the field existed still
loads and still validates. `normalize_hit()` **rejects** an out-of-range value rather
than clamping it — a model that answers in pixels (`[361, 95]`) would clamp to
`[1, 1]`, the bottom-right corner, which is a confident wrong answer that puts the
crosshair on the HUD's own bar. Rejecting falls back to the fixed 36%/64% position,
which is merely approximate.

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
python backend/extract_frames.py fight1.mp4                        # 2 fps, 768px
# commentary. Pass --looks too: it is what lets the garble guard know whose weapon
# is whose, and without it a mis-transcribed "X got hit by X's own drum" gets through
python backend/transcribe.py fight1 --bots "Tombstone,Witch Doctor" --looks "...|..."
python backend/scrape_comments.py fight1 "tombstone witch doctor" --mock
python backend/analyze.py fight1.mp4                               # -> timelines/
python backend/analyze.py fight1.mp4 --backend cli                 # no API key needed
python backend/analyze.py fight1.mp4 --bots "Manta,Skorpios"       # pin the card
python backend/analyze.py fight1.mp4 --looks "blue wedge|copper forks"  # pin the machines
python backend/analyze.py fight1.mp4 --regrade      # re-grade each blow's severity
python backend/analyze.py fight1.mp4 --stop-pass    # re-ask when the LOSER stopped
python backend/analyze.py fight1.mp4 --verify       # re-ask WHO landed each blow

# the one sampled sound. Regenerating is a deliberate act — the file is committed.
python backend/say.py --list                        # voices on the account
python backend/say.py perfect "Perfect." --voice Adam --pitch 0.82 --room 0.30

# where did a blow land? probe first — writes nothing, and the frame with no
# impact in it MUST come back null before hit.at is worth paying to judge
python backend/probe_at.py manta-skorpios --at 2.0 15.5 23.0 --repeat 2

# a better comments file into an EXISTING timeline — no frames, no model, free
python backend/analyze.py manta-skorpios --rejoin --bots "Manta,Skorpios"

# era B, any fight video
python backend/ingest.py "https://www.youtube.com/watch?v=..."

# era B, one fight cut out of a multi-fight compilation. The download is cached
# under clips/.raw/, so the 2nd and 3rd fights cost no bandwidth.
python backend/ingest.py "<url>" --name manta-skorpios \
    --start 187 --duration 32.5 --bots "Manta,Skorpios"

# lengthen an existing clip's tail without re-judging it. --recut is a no-op
# without the flag: ingest returns early when clips/<name>.mp4 already exists.
python backend/ingest.py "<url>" --name manta-skorpios \
    --start 187 --duration 32.5 --recut
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
| `jackpot-copperhead`  |  23 | 149.4 | `Copperhead,Jackpot` | —       | TAP OUT : 152sec |
| `manta-skorpios`      | 187 |  32.5 | `Manta,Skorpios`     | `right` | KNOCKOUT : 24sec |
| `madcatter-tombstone` | 271 |  79 | `MaDCaTTer,Tombstone`| —       | KNOCKOUT : 72sec |

The durations run **past the KO on purpose** — far enough to reach the BattleBots
interstitial card that closes each fight, because the HUD now plays through the
celebration instead of freezing on the K.O. stamp. The margins are tight and were
established by extracting frames from the cached source, not by guessing:

| clip | card at (source) | next fight starts | cut ends |
|---|---|---|---|
| `manta-skorpios`      | 217.75–219.2 | 219.75 (MaDCaTTer intro) | 219.5 |
| `jackpot-copperhead`  | 170.8–172.3  | 173.0 (MANTA intro)      | 172.4 |
| `madcatter-tombstone` | **none**     | — (YouTube outro ~356.5) | 350   |

`madcatter-tombstone` is last in the compilation, so it has no card — it runs into
the channel's subscribe outro and is deliberately left at 79s.

**Re-cutting does not need a re-judge.** `-ss` is applied before `-i` and is
independent of `-t`, so a longer cut is byte-identical at the front: single-frame
MD5s at t=0/10/40 match between the old and new clips, and every timeline timestamp
still lines up. `ingest.py --recut` does exactly this and then **stops** — no frame
extraction, no judging, no API spend:

```bash
python backend/ingest.py "<url>" --name manta-skorpios --start 187 --duration 32.5 --recut
```

**`--ko` names the LOSER**, not the winner — `loser = ko` in `analyze()`, and the flag
lands in the timeline as `events[-1]["ko"]`, the side whose hp is 0.

**`--looks` pins WHICH MACHINE is which**, where `--bots` only pins the names. Verified
by eye against the frames; pipe-separated because the descriptions contain commas:

```bash
--looks "low blue wedge, wide yellow drum spinner|copper forked wedge, teal vertical blade, teal wheels"   # manta-skorpios
```

`manta-skorpios` **needs `--ko right`**: Skorpios loses. Its KNOCKOUT graphic lands over
a crowd shot with no bot in it, so the model has nothing to read the finish off and picks
a side. This table said `left` for a long time, which is exactly backwards and would
invert the fight on any re-judge that followed it. The source video's own commentary
settles it — "Dream is already over for Skorpios in this fight, in just 24 seconds"
(clip t≈23.6s), which is now in `transcripts/manta-skorpios.json`.

Keys in the page: `space` starts the fight and then toggles play/pause · `←`/`→` ∓10s ·
`esc` pause menu mid-fight (RESUME / REPLAY / HOME), and on the GAME OVER card steps
back INTO the fight so it can be rewound · `r` replay · `h` home · `c` CRT filter ·
`g` rainbow bars. A control bar with play/pause, a scrubber, skip buttons, a clock and mute fades
in on mouse movement and stays up while paused. The fight card also carries
BACK TO FIGHT / REPLAY / HOME buttons.

**Space, not any key.** A stray keystroke should not drop you into a fight, and Space
already means play/pause once it is running, so the two agree. `r` is gated on
`started` for the same reason — `replay()` ends in `start()`, so an ungated `r` starts
the fight from the title screen whatever the start key is. Picker buttons `blur()`
themselves on click: clicking the fight already loaded navigates nowhere and leaves the
button focused, and the `INPUT`/`BUTTON` guard in the keydown handler then swallows
Space forever.

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
- **A git worktree has its own `.env`, and `config.ROOT` resolves to the worktree.**
  So rotating the key in the main checkout does nothing for a run started from
  `.claude/worktrees/<name>/` — it keeps using the stale copy and 401s, which reads
  as "the new key is broken". This cost a whole re-judge. Compare fingerprints rather
  than eyeballing (`sha256` of the value, first 8 chars) and never print the key
  itself. Same trap for `.venv/`: the worktree has none, so use the main checkout's
  interpreter at `/Users/carter/dev/gameover/.venv/bin/python`.
- **The commentary is evidence, and it used to be thrown away.** `transcribe.py` puts
  the broadcast commentary in `transcripts/<clip>.json` with timestamps, and
  `analyze.py` feeds each batch only the **window** of it overlapping that batch's
  frames (`transcribe.window()`, 1.0s lead / 1.5s lag — commentators react *after* the
  blow). Never the whole transcript: minute one names the eventual winner, and the
  judge would back-fill a result it has not seen. It enters through `commentary_note()`
  inside `footer()`, so one edit reaches all three backends. No transcript, no key, or
  `--no-audio` → the footer is byte-identical to before, so the feature cannot break an
  existing run. It is a clue for WHO and WHAT, never proof of damage — that rule is in
  `prompt.txt`, because commentators exaggerate and talk about off-camera things.
- **Transcripts come from YouTube auto-captions, not Whisper.** `yt-dlp --write-auto-sub`
  on the clip's source video, sliced to its window using `clips/<clip>.source.json`
  (written by `ingest.py`; backfilled by hand for the three demo clips). Free, no key,
  no new dependency, and it works for any clip whose `.source.json` names a YouTube URL.
  `--source openai` (whisper-1) is the better-quality alternative and **depends on which
  key is in `.env`**: the original service-account key carried five text/vision models
  and 403'd `whisper-1` with `model_not_found`, which is why auto-captions are the
  default; the key in place since has 127 models including `whisper-1`. Check before
  assuming either way. Anthropic has no speech-to-text API at all, so transcription is
  OpenAI-or-captions whatever `--backend` the judge runs on.
  Two deterministic fixes are applied on the way in: YouTube's rolling captions overlap
  by several seconds so `tidy()` ends each cue where the next begins, and ASR mangles
  proper nouns so `fix_names()` snaps near-misses back to the pinned `--bots` spelling
  ("Scorpios" → `Skorpios`, "Mad Catter" → `MaDCaTTer`). A pinned name the commentary
  never says is warned about — that is a free cross-check on a flag that silently
  disables the competitor-pinning header when it is wrong.
- **A bot the first pass never scores gets one focused re-look.** If a side finishes
  under `SHUTOUT_FLOOR`, `repass()` re-judges the same frames watching only that bot.
  A fight where one machine is never above "none" is almost always a mis-read, not a
  clean sweep. It only ever **adds** (`max()` per frame) and is bounded by code that
  already exists — the result still goes through `pay()` on `LIVE_BUDGET`, so even a
  maximally over-eager pass cannot take the winner below hp 45. It does not fabricate
  anything: a rating with no hp drop behind it is still dropped by `normalize_hit()`.
  On `manta-skorpios` the first pass gave Manta 4 damage and this found 24.
- **The count cannot start while the loser is still being hit.** `immobile_from()`
  already broke its backward walk when the loser LANDED a blow; it now also breaks
  when the loser TAKES scored damage, because a frame that cost hp is a frame the
  fight was still on. This is not cosmetic: the count window zeroes every loser-side
  cost from its start (`o["cost"][loser] = 0`), so a blow inside it scores nothing,
  emits no `hit` via `normalize_hit()`, and lands on the HUD as a caption over a
  frozen bar. On `manta-skorpios` that erased *"Manta launches Skorpios airborne"* at
  t=15.5 — a real launch, and Manta's third hit. The broadcast settles it: its own
  `KNOCKOUT : 24sec` means a ten-second count cannot have started at clip t=14. The
  rule is bounded by **`MIN_COUNT_SECONDS` (5s)** and the bound is load-bearing — a
  winner grinding on a downed bot one second before the graphic would otherwise
  collapse the count to a single step, which is the phantom finishing blow below
  rebuilt out of a real rating. A blow that close to the end is treated as no
  evidence and the walk continues past it. It prints only when it actually moved the
  count, never when it merely ended a pointless walk.
- **A knockout is a count, not a blow.** Forcing `hp[loser] = 0` onto the last event
  invented a finishing hit out of whatever bar was left — 68 points on
  `manta-skorpios`, where the frames show *no contact at all* in the final third and
  t=27.0 is a referee standing at the driver-booth glass. It won BEST BLOW on two of
  three clips. Now `immobile_from()` finds where the loser stopped and `count_out()`
  bleeds the remaining hp to 0 across the count, one step a second, each marked
  `drain`. The single forced drop survives **only** as the fallback for a clip where
  the model never sees the loser stop.
- **`finish` used to mean four different things** — "counted out, tapped out, a
  KNOCKOUT graphic on screen, or dead and not moving". Those are different moments:
  the bot dies at t=16, the banner appears at t=27. Whichever fired first past the
  70% index became the end of the fight. It is now three fields: `immobile` (stopped
  moving), `finish` (the broadcast says so — banner, count, celebration) and
  `replay`. `immobile` is deliberately **exempt from the no-repeat rule** — it is a
  state reported on every frame it holds, not a blow.
- **The count is clamped to `MAX_COUNT_SECONDS` (15s), because the model calls
  immobility early.** A referee count is ten seconds and the graphic follows shortly;
  anything longer means the bot was still fighting when it got flagged, and draining
  then bleeds a live machine. On `madcatter-tombstone` the model called Tombstone
  immobile at t=45 — but the commentary has it "back into the fight" at t=56 with its
  weapon "dying down" at t=60, so the honest count starts ~t=59.5, not t=45. The clamp
  is a floor on the start, never a change to where the drain ends. It leaves
  `manta-skorpios` alone (a 9s count) and prints when it fires.
- **Identity is decided on batch 1, and without `--looks` that call is the only one
  with no appearance information in it.** `--bots` gives the model two names and their
  sides but never says which machine is which; whatever it guesses gets latched by the
  first-description-wins rule, re-sent verbatim to every later batch and every
  `repass()`, and **nothing downstream can detect it was wrong** — an inverted run is
  perfectly self-consistent, so the `--ko` arbitration, `immobile_from()`,
  `normalize_hit()` and `validate()` all pass. `--looks` seeds `state` so the anchor is
  human-verified from the first frame; the existing latch then refuses to overwrite it.
  Errors cluster where the model has least to go on — the replay stretch and the
  post-KO close-ups. It is **not** a global swap: the t=2.0 opener on `manta-skorpios`
  is independently confirmed by both the commentary and the frames, and 37 of 38
  hp-scored captions name the correct victim. Never "fix" it by flipping the sides.
- **Auto-captions mishear, and one garbled verb scored three hits.** `"Manta got hit by
  that huge drum spinner"` — but the drum is *Manta's own weapon*, so the line is a
  garble of "got him with". Read literally it put 20 hp of damage on the eventual
  winner across three frames. Two guards now: `prompt.txt` states a weapon belongs to
  the bot carrying it (so damage by that weapon is damage it DEALT), and `tidy()` caps a
  cue at `MAX_CUE` seconds — ending each cue where the next begins overshoots badly
  whenever the commentators pause, inflating a 2s sentence into a 4s claim.
- **`bots/*.png` are stale, wrong and unused.** `bot_shots.py` picks sides by screen
  position in one arbitrary frame, which is a second identity decision unrelated to the
  timeline's — and it shows: `bots/manta-skorpios-left.png` actually contains *Skorpios*,
  and the `-right.png` contains both bots, because both were cut from a frame where the
  machines are vertically stacked. Nothing loads them (the hand-drawn `ART` sprites win
  the portrait cascade), and they are now in `.vercelignore`. Do **not** feed them to the
  judge as reference images — they would teach the swap.
- **`immobile` is trusted for WHEN, never for WHICH bot.** "Something has stopped" is
  easy; "which of these two machines is it" is the hardest call in the clip, and the
  model gets it wrong — on `manta-skorpios` it flags *Manta*, the winner, immobile
  across the very frames Skorpios is being counted out on. So `immobile_from()` walks
  **backwards** from the end, counts a flag on either side, and reads it against the
  settled loser; the bot still being counted out at the end of a fight is the one
  that lost it. It prints when the model disagreed. The only thing that breaks the
  walk is the loser *landing a blow* — it has to be driving to do that.
- **Broadcasts cut to slow motion, and a replay is damage you already judged.**
  `drop_replays()` zeroes damage on frames the model flags `replay` (captions survive —
  a replay is fine to narrate, it just must not move the bar). Without it the same blow
  scores twice.
  **A missing match clock does NOT mean a replay.** This file used to claim
  `manta-skorpios` t=12–21.5 was one, on exactly that reasoning. It is not — measured,
  the burned-in clock is absent t=11.0–22.0 (sample the clock box: blue-minus-red ≈ +44
  with it, ≤ +22 without), and that whole stretch is **live**: the broadcast cuts to the
  driver booth and then to a low ringside angle that does not carry the overlay. The
  real t=15.5 launch is in there. Do not build a clock-based replay gate off this
  signal — on this clip it would zero live action and delete a real blow.
- **A wrong attribution is SELF-CONSISTENT, so almost nothing downstream can see it.**
  The per-bot damage word and `hit.by` come from one act of identification, so when the
  model puts a blow on the wrong robot it puts both on the wrong robot. `obs[i]["cost"]`
  is read from the damage words and never from `hit.by`; `normalize_hit()` only flips a
  hit whose `by` names the side that *lost* hp, and only coerces on `clean: false`;
  `relook()` is forbidden to re-attribute and is floored so it can never say "nothing
  happened"; `validate()` is a shape check. A `clean: true` hit with `by` on the
  opposite side is the *canonical* shape, so every guard passes it. Three defences now
  exist, and they are independent on purpose:
  - **`drop_own_weapon_garbles()`** (`transcribe.py`) drops a cue saying a bot was
    damaged by a weapon it carries, testing across adjacent cues because the weapon
    usually lands in the next one. This is the `"Manta got hit by that" / "huge drum
    spinner"` garble — really "got him with" — which has now cost two runs, charging the
    eventual WINNER 20 hp across three frames both times, with the caption inverted on
    every one. It needs `--looks` (that is where each machine's weapon is named) and
    does nothing without it. It **drops** rather than rewrites: we know the line is
    garbled, we do not know what was said, and the frames still carry the blow.
  - **`drop_downed_hits()`** (`analyze.py`) deletes a clean hit whose `by` is a machine
    described immobile on that same frame. This is the pipeline's one genuinely
    independent cross-check — "who landed this" and "which machine has stopped" are
    separate answers, and the second has already been matched to a side against the
    human-verified `--looks`. It runs **before** `immobile_from()`, which reads
    `raw_hit.by == side` as proof the bot was still driving, so a false hit was
    corrupting the count-out walk as well.
    **Its weak point is the side, not the rule.** It trusts `resolve_immobile()`, and
    the same run still printed `model named the other bot immobile on 2/9 frames` —
    the model does flag the WINNER immobile, which is why `immobile_from()` reads
    flags against the settled loser rather than at face value. Two things keep this
    safe rather than lucky: the description is matched against the human-verified
    `--looks`, and `match_look()` returns `None` when it is a coin flip. If a real
    blow ever disappears with this message on it, that is where to look.
  - **`--verify`** re-asks WHO, deaf (`talk=[]`), on frames that already scored. It is
    the only pass that can answer "no contact here" and delete a blow. Bounded: it
    cannot touch a zero-scoring frame and cannot change severity. Deaf for a sharper
    reason than `--regrade`: the garbled commentary is the thing being checked against.
    A re-attributed frame loses its caption — it named the old attacker.
    Its window leads by `MERGE_WINDOW`'s worth of frames, **wider than `relook()`'s on
    purpose**: "is this a new blow or the tail of the last one" cannot be answered from
    the moment alone. `manta-skorpios` t=7.5 is Skorpios dropping back down from the
    lift it took at t=6.5, and a three-frame window starting at t=7.0 does not contain
    the lift — so the pass was told "settling after an earlier hit is not contact"
    while being shown no earlier hit, and kept the phantom. `merge_blows()` cannot
    catch this one either: it deliberately does not merge across sides, and an
    aftermath frame gets scored against the OTHER bot.
- **A deletion pass must run AFTER the shutout rescue, never before.** The passes are
  ordered `merge_blows` → `relook` (how hard) → `repass` (shutout rescue) → `verify`
  (who, or whether) → `drop_downed_hits` → `finish_at`, and that order is load-bearing.
  `repass()` exists to rescue a bot the first pass never scored and it **only ever adds**
  (`max()` per frame). Put `verify()` in front of it and the two fight: on
  `manta-skorpios`, verify correctly deleted every false blow and left Manta having
  taken **0** damage — which is the true answer for a 24-second knockout — the shutout
  check read that zero as a mis-read, and `repass()` put **62** back, tripping the
  "identity may be inverted" warning and handing the winner more damage than the loser.
  Same lesson as `relook()` running before the shutout check and for the opposite
  reason: anything that changes the totals has to be placed relative to whatever reads
  them next.
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
  The one exception is `drain`: an hp delta that is a count-out and not a blow. That
  is a fact code cannot infer from two adjacent events, which is exactly why it has
  to be stored. It is honoured in `deriveHits()` and nowhere else — with `h.ko` now
  never set (there is no hit at the KO), the end card's KO tick is placed from the
  `ko` event directly, and the fan-comment side falls back to `ev.ko` instead of the
  vanished top hit, which otherwise put every right-side KO comment over the winner.
- **The KO is the referee's call, not the end of the broadcast.** `koSequence()` used
  to `v.pause()` the instant the `ko` event was crossed, which threw away every frame
  after it — 5s on `manta-skorpios`, including the whole celebration. The stamp now
  plays *over* the live footage and `finish()` waits for the video to run out. The
  backstop watches `currentTime`, **not a wall clock**: a wall-clock deadline assumes
  video time tracks real time, so one buffering stall cuts the celebration off
  mid-shot, which is the exact thing the longer cut exists to prevent. A **paused**
  video is not a stalled one either — a backgrounded tab pauses playback, and counting
  that would drop the viewer back on GAME OVER when they return. `finish()` is
  idempotent (`overDone`) because `ended` and the backstop can both fire.
  FIGHT TIME and the timeline strip stay keyed to the last **event**, never to
  `v.duration`, or every clip's fight time stretches across the dead air.
- **The count-out is ten seconds where nothing happens**, and on `manta-skorpios` it
  is 12 of 18 events, all with empty captions. `deriveCount()` turns the run of
  consecutive `drain` events into a referee count in the loser's own status line
  (`COUNT 1`…`COUNT 10`, capped because a referee count is ten seconds). It is applied
  in `render()`, *after* `setSide()` writes `statusFor(hp)`, so scrubbing off the
  count heals the line automatically. Frontend-only and derived — no re-judge.
- **`hit.at` was gated on a probe, and the probe's negative control is the point.**
  `backend/probe_at.py` asks for an impact point on frames whose answer is known and
  **writes nothing**. A wrong `by` contradicts the hp deltas and a wrong `weapon` reads
  oddly, but a wrong coordinate just puts the crosshair somewhere plausible and nobody
  notices — so it gets tested before a re-judge is paid for. The load-bearing case is
  `--at 23.0` on `manta-skorpios`, a driver booth with no robot in it: the model must
  answer `null`. It does, repeatably. Worth knowing that the human ground truth was the
  thing that was wrong here — (0.47, 0.22) was the *spark plume*; the model's
  (0.42, 0.48) is the actual contact point, confirmed by drawing it on the frame.
- **`object-fit: cover` means the model's point is NOT the stage's point.** `#video`
  is centre-cropped into `#stage`, so a normalised frame coordinate has to go through
  `frameToStage()` — `s = max(stageW/videoW, stageH/videoH)` and the centring offset —
  and nothing else in the page reads `videoWidth`. It is clamped by `--mark-min-top` /
  `--mark-max-top` / `--mark-inset`; the top floor is load-bearing, because an impact
  high in the frame would otherwise land squarely on the burned-in `KNOCKOUT : 24sec`
  banner. Raise them with `--safe-top` and `--strike-top`, never alone. The arena
  marker is an **addition** to the on-bar `.hitmark`, never a replacement:
  `hitAnchor()` anchors to the health core that drained, which is what makes it
  structurally incapable of reaching that corner, and it is the only marker a
  synthetic or pre-`at` timeline can draw.
- **`--regrade` re-grades blows; it cannot invent or delete them.** The first pass
  answers "did anything happen" and "how bad was it" at once, across a whole fight,
  with a strong if-unsure-none prior — reliably good at the first, weak at the second.
  `relook()` re-asks only the second question, on the frames that already scored,
  after `merge_blows()` so each physical blow is re-graded exactly once. It is bounded
  three ways: the number of scoring frames is invariant, a move is capped at
  +2/−1 rungs and never reaches `none`, and it snaps to a `SEVERITY` rung so it cannot
  produce a value the ladder can't express. It runs **before** the shutout check,
  which reads the totals it changes — an under-graded blow that clears
  `SHUTOUT_FLOOR` here skips a whole-clip `repass()`. It is asked **blind** (the first
  pass's rating is not in the prompt — a stated prior turns a second opinion into a
  rubber stamp) and **deaf** (`talk=[]`, because `prompt.txt` is explicit that
  commentary is evidence for WHO and WHAT and never for HOW HARD).
- **A launch used to be scored `solid`, because the prompt said so.** `pay()` can only
  *delete* a hit, never shrink one, and nothing between the model's word and the hp
  delta scales anything — so a 12-point delta means the model literally emitted
  `"solid"`. The cause was the ladder text: "bot thrown or flipped" sat under `solid`
  while `heavy` demanded "thrown across the arena", which is a *distance* judgement a
  768px still cannot support. `heavy` now asks about being airborne and how it landed,
  which a still can answer. If you move a rung's wording, check the `raw damage before
  budget` line: totals at or above the budgets mean `pay()` has started deleting hits.
- **`immobile` is a DESCRIPTION now, not a side.** Naming the side is the hardest call
  in the clip and the model got it wrong — on `manta-skorpios` it flagged the *winner*
  immobile on 3 of 5 frames. It now describes the stopped machine and `match_look()`
  decides the side in Python, against the human-verified `--looks`. The scoring is
  distinctive-token overlap with words common to BOTH looks discounted to nothing:
  both machines are a "wedge", so whole-string similarity (the obvious first idea)
  scores the two sides almost identically and decides on noise. It is normalised by
  the **description's** distinctive words, not the look's, or a short correct answer
  ("low blue wedge") is marked down purely for being shorter than the look it matches.
  Ambiguous returns `None`, which `immobile_from()` already reads as no evidence. A
  bare `"left"`/`"right"` is still accepted — that is what every older timeline holds.
- **`immobile` is restated in `footer()`**, like the `hit` rule, and for a sharper
  reason: it is the field that is meant to REPEAT, and the flags that matter arrive at
  the very end of a long clip, which is the far side of where a model drifts back to
  the obvious answer.
- **`--stop-pass` is the only call allowed to name the loser.** It runs after `--ko`
  and the damage cross-check have settled `loser` and before `immobile_from()`.
  Telling the *damage* pass who loses would let it write the ending it was told about
  rather than the one it can see. It is sub-sampled to ~1fps because half the count
  window on `manta-skorpios` is booths and crowd with no robot in it, and `count_out()`
  drains one step a second anyway — a finer grid buys precision nothing can spend.
- **A clip's `t=0` is `t0`, not `--start` — and that is now recorded, not re-derived.**
  `-ss` before `-i` with `-c copy` snaps back to the nearest keyframe and
  `-avoid_negative_ts make_zero` rebases from there, so clip `t=0` is the keyframe
  (185.977s on `manta-skorpios`, not the 187 that was asked for) and the file runs
  longer than `--duration` by the same amount. `transcribe.cut()` mapped captions with
  `s["start"] - start`, which put every manta caption **1.02s early** (madcatter 0.81s,
  jackpot 0.10s). `ingest.cut_window()` now probes the raw source for the keyframe the
  cut actually landed on and writes `t0`/`span` into `clips/<clip>.source.json`;
  `transcribe()` maps from those, falling back to `start`/`duration` so a
  `source.json` written before this still behaves exactly as it did.
  Two traps in the probe, both of which produced confidently wrong numbers:
  `ffprobe -read_intervals` with `%+duration` measures that duration from wherever its
  **seek** landed — a keyframe *before* the requested start — so the window closes
  early and the real answer falls outside it (it returned a keyframe 3s too early on
  manta). Use an absolute end, `lo%hi`. And `cut_window()` cross-checks the probe
  against `start - (span - duration)`, an independent estimate that needs no packet
  parsing; a disagreement over 0.5s means the probe missed, and the arithmetic wins.
  Re-transcribing is free, but the fix only reaches the HUD through a **re-judge** —
  the transcript is an input to `analyze.py`, not something the page reads.
- **A transient's lifetime lives in its CSS variable, not in a JS timer.** `lifeMs()`
  reads `--hm-life` / `--strike-life` / `--comment-life` / `--exchange-gap` so the
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
- **Any JUMP in the timeline must re-derive, never replay.** `tick()` used to fire
  every crossed event in one frame, which was invisible until a scrub bar existed:
  a forward seek then stacked N `sfx('hit')` tones, N `shake()` calls clobbering each
  other and N captions into a single frame, and crossing the KO scheduled the
  fireball 1000ms after a moment already gone. The rule is now `i < applied ||
  i - applied > 1 → reseat(i)` — events are ≥0.5s apart and frames ~16ms, so
  advancing by more than one only ever means a seek or a stall. `reseat()` ends by
  re-applying the KO **quietly** (`koSequence(loser, true)` — end state, no blast) if
  the landing point is at or past it, or seeking to the tail means GAME OVER never
  arrives. `koSequence()`'s 1000ms beat keeps its handle in `koTimer` so a scrub
  back inside that second can cancel it, and `playOut()`'s `ended` listener is named
  (`outEnded`) so re-arming cannot leave one holding a stale `loser`.
- **`watchdog()` cannot tell a user pause from a blocked one — `userPaused` can.**
  Pausing inside its 1.2s window got the video muted and force-played; holding ~2.1s
  defected to `fallbackClock()`, painting DEMO ARENA over live footage while the
  video sat still. Both guard chains now check `userPaused`. Anything that pauses
  must go through `pbSetPaused()`, not a bare `video.pause()`, or the watchdog will
  fight it.
- **The caption's `flex-basis` must stay `0`.** `#caption` sits between the two
  `.side` columns in one flex row. With `flex: 1 1 auto` its base size is its own
  max-content width, so a long caption pushed the row into negative free space and
  both sides — `flex-shrink: 1`, `min-width: 0`, no min-content floor — were squeezed
  below `--bar-w`: measured, the health cores went 69px → 27px and the fan comment
  rewrapped with them. `flex: 1 1 0` is arithmetically identical wherever there IS
  free space, so the short-caption look is unchanged. `.core` also carries
  `flex: 0 0 auto` — a core is a fixed size, never a share of the row.
- **`#caption` has two children and no longer takes `textContent`.** `.prev` (faded)
  holds the previous line and `.cur` is the one being typed; the blinking `::after`
  cursor lives on `.cur`, not on `#caption`, or it renders after both. Writing
  `$('caption').textContent = ''` destroys the structure — use `clearCaption()`.
  `typeCaption()` demotes the tracked full text of the outgoing line, not what is on
  screen, because `clearInterval(typeTimer)` can abandon typing mid-word. A scrub
  uses `showCaptionAt(i)`, which walks BACK to the last two events that actually said
  something: live playback only types on a non-empty caption, and a count-out is ten
  seconds of blank ones.
- **PERFECT is `tally(s).in === 0`, and nothing else.** `tally()` is the same function
  the fight card prints `DMG TAKEN` from, so the HUD badge and the card cannot claim
  different results — that is the whole reason `tally()` exists. It already excludes
  the count-out `drain` (`deriveHits()` skips the drained side), so a knockout winner
  is not credited with the bar the loser bled and still qualifies. `HITS.length > 0`
  guards a timeline with no damage at all, which would otherwise perfect both bots. It
  fires at the K.O. stamp inside `koSequence()`'s `land()`, not at GAME OVER — by then
  `#over` covers the HUD — and honours the existing `quiet` flag so a scrub past the
  knockout lands the badge with no pop and no announcer. Today it fires on
  `manta-skorpios` only.
- **`.perfect` needs `z-index: 8` and its own `[hidden]` rule, for two different
  reasons.** `#ko`'s fireball is `z-index: 7` and covers the whole frame for the
  stamp's life, so the badge would sit under it; `.bars` is positioned but has no
  `z-index`, so it opens no stacking context and lifting the badge alone works. And
  `display` in an author rule beats the UA's `[hidden]` — the same trap that made
  `#preds` unhideable for its entire life, painting an empty CROWD CALL header on every
  clip and never hiding on the ones with no picks. Any new element that is both styled
  with `display` and toggled with `hidden` needs `[hidden] { display: none }`.
- **One sampled sound, and one only.** Everything else is oscillators; `sfx/perfect.mp3`
  is an announcer line generated once by `backend/say.py` (ElevenLabs, then pitched down
  and given a room with ffmpeg — resampling drops the formants too, which is what makes
  it read as a big voice rather than a slowed-down small one). It is committed and
  served statically: no key in the browser, no API call at runtime. It decodes through
  the same `AudioContext` as everything else and degrades in two steps — no sample, the
  synth fanfare alone; no audio, silence and the badge still lands. **`ac()` now resumes
  on every call**: `loadVoice()` decodes at boot, which creates the context before any
  user gesture and therefore suspended, and a suspended context plays nothing silently.
  The key lives in `.env` as `ELEVENLABS_KEY` — and a worktree has its OWN `.env`, so a
  key added to the main checkout is invisible from `.claude/worktrees/<name>/`.
- **A hit tick's colour is WHICH bot, its height is HOW HARD.** Both strips — the
  end card's hit log and the scrubber — take `--left-color` / `--right-color` from
  `h.by`, the same value that decides the end card's above/below split, so colour and
  side cannot disagree. Colour used to carry the tier, which meant the strip and the
  `.bd-tier` chips directly above it spoke the same palette about two different things,
  and left the strip saying nothing about who. Tier survives as height (and width) —
  which the scrubber never had: every tick there was a flat 14px, so colour was its
  only channel and it had to gain `--tick-h` steps to keep saying both at once. Tier
  colour still lives in `.hitmark`, `#strike`, `#hits .hl` and the chips.
- **The title card reserves its space too, and the order of `boot()`'s awaits is part
  of it.** Switching fights was visibly jittery: `boot()` awaited the timeline, then
  awaited `comments/<clip>.json`, and only *then* called `setVs()` — so the biggest
  element on the screen sat behind a second serial round-trip it needed nothing from,
  and the crowd call rendered before the bot art. The comments fetch is now started and
  not awaited until the end (nothing it sets up is read before the fight starts), and
  `.vs .bot` / `.pq blockquote` carry `min-height` so the card is laid out at its final
  size on the first paint — measured, the VS panel is now the same height with and
  without its sprite. The picker also stopped re-fetching the current clip's timeline:
  `loadJSON` is `no-store`, so that duplicate could never be served from cache and
  competed with the one request the whole page was waiting on.
- **The caption block reserves measured space, not a guessed line count.**
  `sizeCaption()` renders every caption in this timeline once at load and reserves the
  tallest, per slot, as `--cur-h` / `--prev-h`, so the block is the same height for a
  one-word caption, a wrapped one and none at all — otherwise the bars, the cores and
  the fan comments shift every time a line is typed. A fixed count was tried and was
  wrong: the longest `madcatter-tombstone` caption wraps to **three** lines in the
  374px column. It re-runs on `resize`, and **bails when the column has no width** —
  at boot before first layout, and permanently in a headless browser, a zero-width
  column wraps every caption to one word per line and reserved 510px of dead space.
  `.prev` wraps rather than ellipsing: the reservation is what stops it moving
  anything, so there is nothing to gain by cutting it off mid-word.
- **The knockout is drawn from the EVENT, and always as its own full-height mark.**
  It used to ride in on a hit's `ko` flag and fall back to the event only when no hit
  had one. Both renderings were wrong in the same way: with no `up`/`down` class the
  fallback fell to static position — the top half, which the legend labels as the
  LEFT bot — at `.t-massive`'s height, in a gold that is the same hex as
  `--hit-graze`. It read as "the left bot landed a big hit at the end", which is
  exactly what a count-out is not. On `jackpot-copperhead` and `synthfight`, where a
  hit does carry `ko`, the mark vanished onto that hit instead. A tick's colour is
  how hard the blow was; the gold full-height line is when the fight ended. Two
  facts, two marks — and the height is what carries it, never the colour.
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
- **The frame rate is data, not a constant.** `extract_frames.py` writes
  `frames/<clip>/meta.json` with the fps it actually used, and `analyze.py` reads the
  gap back from there (`seconds_per_frame()`). Frame N (1-indexed) is at
  `t = (N-1) / fps`. Default is now **2 fps**; the clips judged before that were 0.5.
  There is deliberately **no `--fps` on `analyze.py`** — one flag that can disagree
  with the frames on disk is all it takes to scale every timestamp by a constant, and
  a HUD drifting off the video reads as a frontend bug for hours. `extract()` also
  re-extracts automatically when the requested fps differs from the sidecar, so
  bumping the rate can't silently reuse old frames. Keep the gap on the 0.1s grid
  (1, 2, 2.5, 5 fps): the model round-trips timestamps as `t={:.1f}s`.
- **`BATCH` is derived, not fixed.** `BATCH_SECONDS = 3.0` means a call always covers
  ~3s of fight — 6 frames at 2 fps. That is the point of the higher rate: the model
  sees a contiguous burst it can watch a blow land *across*, rather than two stills 6s
  apart with the impact lost between them. Pinning the frame count instead would
  quadruple the call count and leave each call spanning 1.5s, where nothing is new.
- **One blow gets rated on several frames at 2 fps** — impact, debris, recoil.
  `merge_blows()` collapses same-side ratings within `MERGE_WINDOW` (1.0s) to the
  single most severe one. **max, never sum**: adding rungs together produces totals no
  rung can represent and no HUD tier can band, which is the 3–5 point drip rebuilt out
  of real ratings instead of invented ones. It is a no-op at 0.5 fps by construction,
  so it cannot regress an older timeline. It deliberately does **not** merge across
  sides — an exchange that damages both bots is two hits.
- **`validate()` runs at the very END of a 25-minute run, so anything it can assert,
  `normalize_hit()` must already have clamped.** It is the last line of defence, not
  the first — an assertion there throws away every batch you just paid for. This bit
  twice in one session: an incidental hit (`clean: false`) naming the bot that took
  *no* damage — the model emits exactly that for "Tombstone catches fire", crediting
  MaDCaTTer — and a `drain` event carrying a hit, which is legal when the winner takes
  a blow mid-count. `normalize_hit()` now coerces an incidental hit to the side that
  actually lost hp, and the drain rule only rejects a hit with no *other* damage
  behind it. Exercise `validate()` against synthetic timelines before spending a run;
  it costs nothing.
- **A failed batch is indistinguishable from a quiet one, so a broken run writes a
  plausible WRONG timeline.** `ask_openai()` swallows transport errors and returns no
  frames, which reads downstream as "nothing happened here". Half way through a
  `madcatter-tombstone` re-judge the OpenAI key started 401ing; 5 batches vanished and
  the result was a validating 43-second fight with no knockout, written straight over
  a good file. Every give-up path now returns `"failed": True` and `analyze()`
  **refuses to overwrite an existing timeline** when any batch failed. `--partial`
  overrides. Back the timeline up before a re-judge anyway — the guard only protects
  the overwrite, not a first run.
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
