# CLAUDE.md — gameover

Hackathon project. A vision model watches robot-combat clips and drives a retro
arcade fighting-game HUD. Read this before changing anything.

**[COMPLIANCE.md](COMPLIANCE.md) governs anything touching the footage, the Reddit
data, or where the site is hosted, and it OUTRANKS this file where the two disagree.**
They no longer disagree. This file used to record a deliberate conflict — the sharing
section said a clip must be committed to git or the public site 404s it, against
COMPLIANCE's hard rule 3 that no video may be committed at all — and the migration that
closed it ran in the order this paragraph specified: bucket → upload → point `CLIP_BASE`
at it → *then* the ignore rule. **That order was load-bearing** and remains the order to
follow if storage ever moves again; reversing it takes the site down, because a
git-connected build only sees committed files.

**No video is committed, and none ships in the deployment bundle.** The clips live in a
Cloudflare R2 bucket behind `clips.gameover.fyi`, `.gitignore` has no `!` exception for
`*.mp4`, `.vercelignore` excludes `clips/`, and `scripts/check_no_video.sh` runs as
`buildCommand` so a re-added clip fails the deploy rather than shipping quietly.

Everything in that file is implemented. The consequences worth knowing here:

- **No Reddit username is ever stored or displayed.** `crowd.author_hash()` salts and
  truncates at scrape time and refuses to run without `GAMEOVER_AUTHOR_SALT` in `.env`,
  rather than emit a hash that is reversible by hashing a candidate list. Records carry
  an opaque `by` token; `pair_exchanges()` is its only consumer. The HUD credits
  `r/battlebots`. Do not reintroduce an author field — the old attribution feature is
  gone deliberately, and it is the one item on that page with a UK GDPR flavour.
- **`serve.py` and `vercel.json` declare the same rewrites** (`/`, `/about`,
  `/takedown`) and must stay in step. A route that works in dev and 404s in production
  is how the `sprites.js` path bug survived; here it would be the takedown page.
- **`scripts/check_no_video.sh` is wired into `vercel.json` as `buildCommand`** and
  passes. It failed for its whole life until the clips moved, correctly. Note what
  wiring it cost: setting `buildCommand` switches Vercel out of zero-config static mode,
  so it then looks for an output directory named `public`, finds none, and fails the
  deploy — `"outputDirectory": "."` is what pins it back to the repo root. The guard
  itself is not a build, but Vercel cannot tell the difference. Caught on a preview
  deploy; straight to `main` it would have taken the live site down.
- **`scripts/teardown.sh` is no longer untested-in-principle** — there is a real bucket
  to point it at now (`CLIP_BUCKET=gameover-clips`). It still defaults to `--dry-run`,
  and it has still never been run for real. Verify it against the bucket on a calm day,
  not the day you need it.
- **`scripts/killswitch.sh off`** flips every route to a static offline page. It is a
  rewrite rather than the `SITE_ENABLED` env var the doc asks for, because a pure static
  deploy has nothing running at request time to read one, and giving it one would mean
  adding the build step this file rules out.

If a request conflicts with a rule in there, say so rather than quietly implementing it.
That includes requests that look purely cosmetic: putting a Reddit username on screen or
adding an `og:video` tag are both one-line changes that cross a line in that file.

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
             "at": [0.42, 0.48], "sev": "heavy"},
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
`weapon` (≤3 words or null), `clean` (false = wall, hazard, fall, self-inflicted),
**`at`**, an optional `[x, y]` impact point normalised 0–1 from the frame's top-left,
and **`sev`**, the ladder rung the model rated the frame.

Damage and victim are deliberately **not** stored — they are pure functions of two
adjacent events, and the frontend must derive them anyway for the synthetic timelines
that have no `hit` at all. Storing them twice is how the hit count ended up with three
different answers in the first place.

**`sev` is the exception, and it earned it the same way `drain` did.** Tier used to be
derived too, by banding the hp delta — which worked only while a delta *was* a rung.
Under `normalise()` a delta is a **share of the bar**, so a heavy in a busy fight is
worth ~8hp and would band as a graze; the rung is no longer a function of two adjacent
events, and a fact code cannot infer is a fact that has to be stored. It is optional,
like `at`: `validate()` takes the key set as a subset, and `tierFor()` falls back to
`tierOf(dmg)` so every pre-`sev` timeline bands exactly as it always did.

`comments/<clip>.json` is the second file the page fetches — a flat array, every
key past the first three optional so the old three-key files still work:

```json
{"text": "As much as Skorpios is my goat, Manta is going to kick their ass",
 "source": "reddit", "url": "https://reddit.com/…/ovwnh4u/",
 "by": "92686393864a", "score": 15,
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
python backend/analyze.py fight1.mp4 --no-condition # skip the end-condition call
python backend/analyze.py fight1.mp4 --verify       # re-ask WHO landed each blow

# the one sampled sound. The shipping take was chosen by ear, so this REFUSES to
# overwrite sfx/perfect.mp3 without --force.
python backend/say.py --list                        # voices on the account
python backend/say.py perfect "Perfect." --voice Adam --pitch 0.82 --room 0.30 --force

# where did a blow land? probe first — writes nothing, and the frame with no
# impact in it MUST come back null before hit.at is worth paying to judge
python backend/probe_at.py manta-skorpios --at 2.0 15.5 23.0 --repeat 2

# the two free pre-flights. Both write nothing, call no model, take a second, and
# both exist because a failure they catch has already shipped once.
python backend/check_looks.py --bots "Copperhead,Jackpot" --looks "<left>|<right>"
python backend/check_timelines.py          # run after EVERY merge, before pushing

# the THIRD pre-flight, and the cheapest 20 seconds before any paid run: prove the
# key actually resolves. A worktree has its own .env, and an EMPTY exported var used
# to shadow it silently — sha256 e3b0c442 is the hash of the empty string.
python -c "import sys,hashlib;sys.path.insert(0,'backend');import config;\
k=config.openai_key() or '';print(hashlib.sha256(k.encode()).hexdigest()[:8],len(k))"

# the Pro League roster and the sprites derived from it — free, no model
python backend/roster.py                   # -> backend/roster.json (27 bots)
python backend/roster.py --force --photos  # refetch, and cache the studio cutouts
python backend/make_sprites.py --check     # -> frontend/sprites.js + a compare page

# re-run the prediction labels over a comments file already on disk. No scrape,
# no Bright Data spend, no risk to the pool — ~2 model calls.
python backend/scrape_comments.py madcatter-tombstone "q" --bots "L,R" --reclassify

# add created_utc to an existing pool. DOES scrape (Bright Data spend), but merges
# ONLY {id -> created_utc} into the records on disk — text, score and the labels are
# read off the fresh rows and thrown away, so a worse scrape cannot damage the pool
# and no fan_comment can be orphaned. Idempotent; needs no --rejoin after.
python backend/scrape_comments.py manta-skorpios "manta skorpios" \
    --bots "Manta,Skorpios" --backfill-dates

# a better comments file into an EXISTING timeline — no frames, no model, free
python backend/analyze.py manta-skorpios --rejoin --bots "Manta,Skorpios"

# re-share the SURVIVOR's bar over an existing timeline — ~1 call, not 76.
# hit.sev stores every blow's rung, so the weights normalise() shared out are
# exactly recoverable and only the end-condition reading has to be re-asked.
python backend/analyze.py jackpot-copperhead --renorm --backend openai \
    --bots "Copperhead,Jackpot" --looks "<left>|<right>"

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
`Bot A vs Bot B` the next time. Worse, an unpinned card also switches off the
closed list of machines in `identity_note()` ("The two competitors are X and Y …
use no other name"), which is the thing stopping the model captioning sponsor decals
as robots — a run with a broken `--bots` came back `Bot A vs Horizon`, and Horizon is
a sponsor. The same header is what names the minibots, so an unpinned run also loses
the only thing telling the model Ace is not a competitor.

| clip | `--start` | `--duration` | `--bots` (left,right) | `--ko` | ends on |
|---|---|---|---|---|---|
| `jackpot-copperhead`  |  23 | 149.4 | `Copperhead,Jackpot` | `right` | TAP OUT : 152sec |
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

**`jackpot-copperhead` needs `--ko right`**, and the reason is worth knowing because it
cost a whole run. The damage cross-check used to overrule the model's KO flag on **any**
margin, and here that margin was **186 vs 178 — 4.5%**, noise on two totals that both
blow past the 55/70 budgets. It moved the loser to Copperhead, put the referee count on
the winner, and wrote a timeline that contradicted itself on one screen: captions at
t=130–134 describing *Jackpot* smoking and catching fire, `t=140.5 "Jackpot taps out"`,
and `ko: left` underneath. Everything else agreed the loser is Jackpot — the commentary
(*"Copperhead done it!"* at t=145.8, and *"MY BOTS ARE BURNING, says Jeff Waters"*, who
`roster.json` confirms is **Jackpot's** builder), the `TAP OUT : 152sec` graphic, both
earlier pipeline generations, and the model's own flag. `KO_MARGIN` now requires the
damage to be *decisively* lopsided before overruling the flag; a genuine inversion is
lopsided by construction (on manta the winner came out on literally 0), so the check
still catches what it exists for. **Pinning `--ko` does not blind you** — the
`is pinned as the loser but took LESS damage` warning still fires, so the inversion
detector survives.

**`--looks` pins WHICH MACHINE is which**, where `--bots` only pins the names. Verified
by eye against the frames **and against the official Pro League studio photo**
(`bots/.proleague/<key>.png`, cached by `roster.py --photos`); pipe-separated because
the descriptions contain commas. **All three are recorded here on purpose** — a string
that lives only in shell history is one the next re-judge will guess at, and a guessed
`--looks` is worse than none, because it is stated to the model as human-verified fact:

```bash
# manta-skorpios
--looks "low blue wedge, wide yellow drum spinner|copper forked wedge, teal vertical blade, teal wheels"
# jackpot-copperhead
--looks "black low wedge with a copper front drum spinner, black top plate, black wheels|green chassis with a red vertical disc spinner, tall red forks, red and black striped wedgelets"
# madcatter-tombstone
--looks "wide low wedge painted as a red cat face with big cyan eyes, blue and red marbled flanks, blue upright spinner|black angular body with a long red horizontal bar spinner, black wheels"
```

**Run `check_looks.py` before paying for a run.** It writes nothing, calls no model and
takes a second, and it has already caught two bad strings that would have shipped:

```bash
python backend/check_looks.py --bots "Copperhead,Jackpot" --looks "<left>|<right>"
```

The two failures it exists for are both real. Copperhead's first draft said *"copper top
plate"* — but the photo shows the copper is the **front drum**, i.e. the weapon, and the
body is black; a model told to look for copper on top would have been hunting the wrong
part of the machine. And only Copperhead's string said `spinner`, so
`transcribe.weapon_owners()` handed every "spinner" in the commentary to Copperhead even
though Jackpot is a spinner too — putting the word in **both** strings gets it correctly
discounted. The rule: **a word true of both machines must appear in both strings**, or it
votes instead of being discounted.

It reports shape words (`a wedge`, `a drum`) as CHECK rather than failing them, because
whether they discriminate is a fact about the robots that the tool cannot know. On these
two fights `a wedge` correctly resolves to Copperhead and MaDCaTTer — Jackpot is a forked
vertical spinner and Tombstone is an angular bar spinner, neither is a wedge — where on
`manta-skorpios` both machines are wedges, both strings say so, and the word is correctly
discounted to nothing. One outstanding nit on the recorded manta string: `a spinner`
resolves to Manta, though Skorpios's vertical blade also spins. It has not caused a
problem and manta is not being re-judged, but add `spinner` to the Skorpios side if it
ever is.

`manta-skorpios` **needs `--ko right`**: Skorpios loses. Its KNOCKOUT graphic lands over
a crowd shot with no bot in it, so the model has nothing to read the finish off and picks
a side. This table said `left` for a long time, which is exactly backwards and would
invert the fight on any re-judge that followed it. The source video's own commentary
settles it — "Dream is already over for Skorpios in this fight, in just 24 seconds"
(clip t≈23.6s), which is now in `transcripts/manta-skorpios.json`.

Keys in the page: `space` starts the fight and then toggles play/pause · arrows change
fight on the title card and seek ∓10s once it is running — one key, two jobs, split on
`started`, and the title-screen branch sits ABOVE the `BUTTON` guard (like `esc`) so a
focused picker button cannot swallow the keys meant to move off it. `←`/`→` step the
list and wrap; `↑`/`↓` move between the rows the picker has actually WRAPPED into,
measured off the boxes in `pickMove()` rather than assumed — three buttons are one row
on a wide screen, two-then-one at 1280 and three on a phone, so a hard-coded grid would
be wrong at every width but the one it was written at ·
`esc` pause menu mid-fight (RESUME / POST MATCH / REPLAY / HOME), and on the GAME OVER card steps
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

**Send people `https://gameover.fyi`.** The LAN link only ever worked for devices on
the same wifi with `serve.py` still running; anyone off the network gets nothing, which
is not a bug you can debug locally. The `*.vercel.app` URLs still work and are fine for
testing, but the apex is the one to share — and it is the origin the R2 bucket's CORS
policy names, alongside `gameover-nine.vercel.app` and `localhost:40911`. **A new
origin needs adding to that policy**, or the video still plays (a plain `<video src>`
needs no CORS) while `sourceLink()`'s `fetch` of `<clip>.source.json` fails silently and
the attribution link vanishes with no error anywhere.

```bash
vercel --prod        # from the repo root — prints the live URL
```

The site is a static deploy with a **guard**, not a build: no framework, no serverless
functions, no API key in the browser. Four pieces make it work, and none of them should
be "cleaned up":

- **`vercel.json`** rewrites `/` → `/frontend/index.html`, so the shared link is a bare
  domain. Vercel preserves the query string through the rewrite, so `/?demo=1` still
  arrives as `location.search`. The deploy root stays the **repo root** — `index.html`
  reaches up to `../clips/`, `../timelines/` and `../comments/`.
  **Every asset path in `index.html` must start `../`, including ones in `frontend/`
  itself.** A rewrite is not a redirect: the browser's URL stays `/`, so a
  same-directory `src="sprites.js"` resolves to `/sprites.js` and 404s on the public
  site while working perfectly in local dev, where the URL really is
  `/frontend/index.html`. `../frontend/sprites.js` resolves to `/frontend/sprites.js`
  from both bases, because `..` from `/` harmlessly stays at `/` — the same reason
  `../sfx/perfect.mp3` has always worked. This one degrades **silently**: a missing
  `sprites.js` just drops every bot back to its weapon sigil.
- **`.vercelignore`** keeps `.env`, `backend/`, `frames/`, `.venv/` and `CLAUDE.md` off
  the public site. Without it, static hosting would serve `/backend/analyze.py` as
  readable plaintext to anyone who guessed the path. Note it **replaces** `.gitignore`
  for CLI uploads rather than adding to it, which is why `.env` is listed explicitly —
  being gitignored is not enough to keep a file out of a `vercel --prod` upload.
- **Clips are NOT committed and NOT in the bundle.** `.gitignore` is `clips/*` with one
  exception, `!clips/*.source.json` — tiny, not video, and without it `transcribe.py`
  cannot slice a source video's captions to a clip's window ever again. `.vercelignore`
  excludes `clips/` outright. A new clip goes to the **bucket**, not to git:
  upload it to `gameover-clips`, and `clipUrl()` finds it with no code change at all.
- **`"buildCommand": "bash scripts/check_no_video.sh"`** fails the deploy if any video
  reaches the bundle, and **`"outputDirectory": "."`** is what keeps a static deploy
  static once a `buildCommand` exists. Neither is optional; see the note at the top of
  this file for why the second one is there.

Pushing to `main` on the **public** GitHub repo auto-deploys. If a shared link ever
returns **401**, it is Vercel Deployment Protection, not your code — turn it off under
Project → Settings → Deployment Protection. Note previews are protected while
production is not, so an anonymous check of a preview URL returns `302` to SSO and
tells you nothing about whether the deploy is healthy.

### Where the clips actually live

Cloudflare R2, bucket `gameover-clips`, served at `https://clips.gameover.fyi`.
`frontend/config.js` is the only place that names it. Facts worth not rediscovering:

- **DNS is Cloudflare; the registrar is Porkbun.** Only the nameservers moved. Adding
  the site to Cloudflare **imports the registrar's existing records**, and Porkbun's
  defaults are actively harmful here — a parking `ALIAS`/`A`, a `www` CNAME, and a
  `*` wildcard that made `clips.gameover.fyi` resolve to a parking page and blocked the
  bucket binding outright, plus MX/SPF that conflict with Email Routing. The zone has to
  be emptied before anything is added to it.
- **A stale parking IP outlives the change.** For a while after the cutover
  `clips.gameover.fyi` still resolved to Porkbun's `207.207.210.107` from cache, which
  has no cert for that hostname — so the TLS handshake fails, the `<video>` element
  errors, `fallbackClock()` fires, and the HUD shows "DEMO ARENA — no clip loaded".
  That is a caching artifact, not a broken deploy. Check `dig +short @1.1.1.1` before
  believing a local failure.
- **`abuse@gameover.fyi` is Cloudflare Email Routing**, forwarding to a personal inbox.
  The routing API installs its own MX/SPF/DKIM records — don't hand-write them.
- **The bucket is in a personal Cloudflare account**, not the project-specific one
  COMPLIANCE.md asks for. Recorded here because it is the live deviation, and because
  abuse enforcement lands on the account rather than the bucket.

### Local dev server

Still the fastest loop for editing the HUD:

```bash
python3 backend/serve.py     # -> http://localhost:40911/frontend/index.html?clip=synthfight
```

**But it now pulls video over the network**, because `CLIP_BASE` points at R2 for every
environment — there is one config file and it is committed. `http://localhost:40911` is
in the bucket's CORS policy for that reason. Offline, the page falls back to the
placeholder arena and the rAF clock, which exercises none of the video sync; point
`CLIP_BASE` back at `../clips` locally if you need the real path without a connection
(the files are still on disk, just gitignored — **do not commit that change**).

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
- **An EMPTY exported variable is not the same as an unset one, and it used to win.**
  `load_env()` skipped any name already `in os.environ`, so a shell carrying
  `OPENAI_API_KEY=` — what a half-finished export or a launcher forwarding every name
  it knows leaves behind — shadowed a perfectly good key in `.env` and 401'd every
  call. That reads as "the key in `.env` is broken", the same wrong conclusion the
  worktree trap below produces. It now tests truthiness, matching `get()`, which
  always treated empty as absent. **Fingerprint before you spend:** `sha256` of the
  resolved key, first 8 chars — `e3b0c442` is the hash of the empty string, and
  seeing it is the whole diagnosis. Never print the key itself.
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
  machines are vertically stacked. Nothing loads them (the generated sprites win the
  portrait cascade), and they are now in `.vercelignore`. Do **not** feed them to the
  judge as reference images — they would teach the swap. The right reference is
  `bots/.proleague/<key>.png`, below.
- **The sprites are GENERATED from the official photos, and `ART` is now the override.**
  `battlebots.com/proleague/` publishes the whole field as **2100×1500 8-bit RGBA studio
  cutouts**, so `make_sprites.py` gets the silhouette free from the alpha channel and the
  livery free from RGB — nothing is guessed. The hand-drawn table it replaced was drawn
  from memory and some of it was flatly wrong: `jackpot` was red and yellow for a green
  chassis with a red vertical disc, `madcatter` was purple for a red-and-blue cat face.
  ffmpeg does the resampling (already a dependency) and the quantising is stdlib, so
  `requirements.txt` does not grow Pillow or numpy for 27 images. Points worth keeping:
  - **`ART` in `index.html` still WINS**, and is empty. That is where a hand-tuned fix
    goes; editing `frontend/sprites.js` works right up until the next regeneration
    silently reverts it.
  - **Two grids per bot, and both are needed.** `.vsart` renders at up to 148px, where
    48×36 is ~3px a cell and reads as pixel art; `.sigil` renders at **14–26px**, where a
    48-wide grid is half a pixel a cell and turns to mush — so the HUD name row gets its
    own 16×12 cut. `spriteSVG()` takes the viewBox from the rows for the same reason: the
    hard-coded `0 0 16 12` cropped every 48×36 sprite to its top-left corner.
  - **Palette entries must be `MIN_SEP` apart.** Taking the k busiest colour bins gave
    Jackpot five near-identical dark reds and one green, for a robot whose whole chassis
    is green: one big region splits across adjacent bins and crowds out every other hue.
  - **`LUMA_FLOOR` is why black machines are visible at all.** `--bg` is `#07080b`, so
    Tombstone, Skorpios and Cobalt rendered as holes in the screen. Same reason arcade
    sprites have never drawn black as `#000`. Raise `--bg` and this can come down.
  - `make_sprites.py --check` writes a page putting every sprite beside its source photo
    at both real sizes. All three problems above were invisible in the numbers and
    obvious on that page — look at it before believing a regeneration.
- **`backend/roster.json` is the field, and the photo URL is SCRAPED, never derived.**
  The proleague page carries all 27 entries (24 competitors + 3 alternates) in one
  embedded `sourceBots` array in the **server** HTML, so `requests` is enough and no
  browser is needed. There is no filename convention to follow: `Disarray` is
  `disarray-proleage.png` and `Nemesis` is `nemisis-right.png`, **both misspelt** (and
  Nemesis's slug spells it correctly, so the two disagree); `End Game` is
  `end-game-right.png` where `Death Roll` is `deathroll-right.png`; and Manta, Orbitron
  and The Twins are `-left` where the other 24 are `-right`. A name-to-URL rule 404s on
  five bots. Each bot's own page gives `Type:` — the site's word for the weapon — which
  several entries leave **empty**, so it is sliced between known labels rather than
  lazily matched; a lazy `(.+?)` returned Disarray's weapon as "Job: Software Engineer".
- **The arena is a third combatant, and the prompt used to talk itself out of it.**
  `prompt.txt` listed hazards among the things whose state must never be assigned to a
  competitor and which must "never trigger a caption", while separately offering
  `killsaws` and `arena wall` as legal `hit.weapon` values — two rules that read as one
  instruction to ignore hazard damage. Nothing told the model that a bot thrown onto
  the screws has taken the damage you can see. On `jackpot-copperhead` all three hazard
  moments scored zero (`onto screws` t=8.5, `lifted by arena screws` t=105.5, `scrapes
  wall sparks` t=129.5) even though the commentary spells the first one out — *"getting
  thrown up on THOSE SCREWS AND GETS PUT UP ON THE UPPER DECK"*.
  The rules are now separate: do not judge a hazard **as a competitor** or caption it
  as a subject, but damage a hazard does **to** a competitor is real damage on the same
  ladder. **The contract needed nothing new** — `clean: false` with `by` naming the bot
  that TOOK it is the existing self/incidental shape, `normalize_hit()` already coerces
  to the damaged side, and `deriveHits()` already sets `h.self`. Stated in both
  `prompt.txt` and `footer()`, because a rule living only in the first drifts by the
  middle of a long clip, which is exactly where hazard throws cluster.
  **The assist is lost and that is deliberate**: when the other bot did the throwing,
  `by` is still coerced to the victim, so `showHits()` credits neither. Growing the
  contract with a `cause` field is not worth it — the screws did the damage.
- **A fight can contain more than two machines, and the prompt used to deny it.**
  `identity_note()` asserted *"the ONLY two competitors are X and Y"*. That is false for
  a third of the roster — Jackpot fields **Ace**, MaDCaTTer fields **Gassy Cat**, and
  **The Twins** is two machines — and false in the most expensive direction: a minibot is
  plainly on screen, the model has been told only two things exist, so it files it under
  whichever competitor it resembles. Ace appears in the `jackpot-copperhead` commentary
  at t=6.1 / 25.5 / 81.7 / 97.4 and in the frames, and a hit credited to the wrong
  machine is **self-consistent**, so nothing downstream can catch it. Three changes:
  - `identity_note()` still gives a **closed list** of machines (that is what stops
    sponsor decals being captioned as robots) but now names the non-competitors too and
    states that nothing they do is damage. It needs the card, so an unpinned run gets
    none — the same degradation as `--looks`, and for the same reason.
  - `match_look()` scores the minibots **in the same contest** as the two sides and
    returns `NOT_COMPETITOR`. Scoring them separately afterwards would let a minibot win
    a contest it was the only entrant in. `resolve_immobile()` maps that to `None` and
    tallies it separately, so a **stopped minibot never starts a referee count** — the
    single most damaging thing a false immobile flag can do, since `count_out()` then
    zeroes every loser-side cost from that point and erases real blows.
  - With three machines in the arena, "distinctive" had to become *appears in exactly
    one description*, not *not in both*.
  Which minibot a team brings is read from `backend/roster.json`, not from a flag — it
  is a property of the team, not of the clip, so pinning it per-run is one more thing to
  get wrong on a re-judge.
- **A knockout is 60% of a multibot's COMBINED WEIGHT, not one machine** (BattleBots
  Tournament Rules 7.5.4, unaltered since 2016). `roster.min_down()` is the whole rule
  and it is pure arithmetic: Jackpot 250lb + Ace 20lb means the heavyweight alone is
  **93%**, so one machine is enough and Ace's state is irrelevant to the count. It
  returns 1 for every ordinary bot **and** every bot with a minibot alike, so
  `immobile_from()` behaves exactly as it always has on all three demo clips — the
  branch is inert. It returns 2 only for a true multibot like The Twins, where one of
  two equal machines is 50% and under the bar. There the sighting has to say more than
  one machine is down (`PLURAL_RE`), because two identical twins have identical
  descriptions and `immobile` holds one machine at a time. **The Twins is in none of our
  clips, so that branch is exercised only synthetically** — treat it as untested against
  real footage.
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
- **Damage NORMALISES per match; it is not spent from a fixed budget.** `pay()` used
  to spend `KO_BUDGET`/`LIVE_BUDGET` on the most severe moments and zero the rest, and
  the budget was absolute while a fight's length is not. `jackpot-copperhead` is 140s
  of events against `manta-skorpios`'s 27s and got the same 55/70: both budgets came
  out **exhausted to the point** (Copperhead 52/55, Jackpot exactly 70/70) against raw
  totals of 240 and 164, so ~253 of ~404 points were struck out and **35 captioned
  moments produced 7 that move a bar** — one scoring moment every 20.1s, against 8.3
  on madcatter and 9.0 on manta. On screen that is "Jackpot throws Copperhead onto
  screws" typed over a frozen bar, which reads as a blow that did not register, and it
  is what a viewer notices first.
  `normalise()` shares one target across every surviving blow in proportion to its
  rung — largest-remainder so the parts sum **exactly**, floored at **1hp** so no blow
  is invisible, and dropping the lowest rungs with a printed warning in the impossible
  case of more blows than points. The eliminated bot loses `KO_BLOW_TOTAL` (85) to
  blows and the count bleeds the last 15; the survivor's total is `winner_target()`.
  **This is the "scaling every hit down to fit" that this file used to forbid, and the
  old warning was right about the OLD pipeline for one specific reason:** it emitted
  absolute hp with *no severity rung behind it*, so a 3-point delta could not be
  banded, coloured or shaken. Here the rung survives as **`hit.sev`**. The delta is now
  purely *how much bar*; the rung is *how hard*. Getting those two apart is the whole
  trick — do not put them back together by making the HUD band the delta again.
- **The surviving bot's bar is half looks, half counting.** `winner_target()` blends
  `CONDITION[rung]` from `condition_pass()` — one extra call rating each bot pristine /
  scuffed / damaged / wrecked, `--no-condition` to skip it —
  with `KO_BLOW_TOTAL × min(1, intense_in(winner) / intense_in(loser))`. Neither half
  is trustworthy alone: a robot can be gutted underneath and look fine from above, and
  a count of hard blows is blind to what they achieved. The ratio is **clamped at 1**
  rather than asserted, because it really can exceed it — on `jackpot-copperhead` the
  *winner* took more raw damage (240 vs 164) and still won. With no condition reading
  the intensity half carries the whole thing, so a skipped or failed pass degrades
  instead of breaking the run.
  **`condition_pass()` must read frames near the FINISH, not the tail of the file.**
  Every clip is deliberately cut past the KO to the broadcast interstitial card, so
  the literal last frames contain no robots: reading `stamped[-6:]` got
  `"No competitors visible"` on `jackpot-copperhead`, the blind half carried the whole
  blend, and the bot that **drives away** finished on 15hp. It now samples
  `CONDITION_FRAMES` evenly back over `CONDITION_WINDOW` from the finish, spread rather
  than adjacent so one crowd shot cannot blind it. Both bots are asked though only the
  winner's answer is used — the loser's is a free cross-check, and on jackpot
  *"Jackpot smoking burning; Copperhead mostly intact"* is an independent confirmation
  of identity on the one clip where getting that wrong has already cost a run.
- **`--renorm` re-shares the survivor's bar without re-judging.** ~1 model call against
  76. `hit.sev` stores every blow's rung, so `SEVERITY[sev]` recovers the exact weights
  `normalise()` shared out and only the condition reading has to be re-asked — verified
  by running it with `--no-condition` and reproducing the original run's 85/15 and its
  `12v9` intensity to the point. It rebuilds **both** sides' weights even though it
  only rewrites the winner's: the loser's hard-blow count is the ratio's denominator,
  and leaving it empty pins that ratio at its clamp, which looks plausible while
  meaning nothing. The loser is never rewritten — its total is pinned by the fight and
  its count-out is already scheduled.
- **The ladder and the HUD's `TIERS` table are one design in two halves.** `SEVERITY`
  rates glance / solid / heavy / catastrophic and `TIERS` in `index.html` bands the
  same four. They no longer meet at the hp delta — they meet at **`hit.sev`**, mapped
  through `TIER_BY_SEV`. The backend owns *how much* damage, the frontend owns *how it
  looks*. Rename a rung on either side without the other and a whole category of hit
  silently changes colour, size and whether it shakes the screen.
  `tierOf(dmg)` survives as the fallback for `synthfight`, `demo/` and any timeline
  judged before `sev` existed — all of them on the fixed-budget pipeline where a delta
  really *is* a rung, so the fallback is exact rather than approximate. **Nothing in
  the HUD may compare a raw hp number to a threshold again.** `SHAKE_AT`/`MASSIVE_AT`
  were exactly that (`dmg >= 10` / `>= 20`) and are now `SHAKE_TIERS`/`HARD_TIERS`; a
  heavy sharing 85 points with ten other blows is worth ~8hp and every one of those
  comparisons would have quietly demoted a long fight's entire vocabulary to GRAZE.
  BEST BLOW and `scheduleExchanges()` sort by rung with the delta only breaking ties,
  for the same reason.
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
- **`check_timelines.py` is two-era aware, and a clip in neither era is stale.**
  A timeline whose hits carry `sev` is **normalised**: every non-count delta must be
  ≥1, every hit must carry a `sev` in `SEVERITY`, and the eliminated bot's blows must
  sum to `KO_BLOW_TOTAL` exactly (which is why `normalise()` uses largest-remainder
  rather than plain rounding). One with no `sev` anywhere is **ladder**: the old
  fixed-budget pipeline, where every non-count delta lands on a `SEVERITY` rung — and
  `madcatter-tombstone` and `manta-skorpios` are deliberately still there, so both
  branches are live and neither is dead code. Neither shape means the original
  absolute-hp pipeline, which is a sharper `f7f9ecb` detector than the ladder check
  alone was: deltas off the rungs *with no `sev` to explain them*. It also prints the
  blow density (one every N seconds) because the failure this era exists to fix has no
  honest threshold — a fire spreading is a caption and not a blow — so a human reads it.
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
  It is no longer a manta-only feature: every judged clip now carries `at` on every
  hit, and `check_timelines.py` asserts it. It stays **optional in the contract**
  regardless — `synthfight` has no `hit` field at all and must keep loading.
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
- **`.hitmark.arena` is coloured by SIDE; the on-bar `.hitmark` is coloured by TIER.**
  That is not an inconsistency, it is the same rule applied to two different contexts:
  out on the video nothing else says who landed the blow, so colour has to carry it
  (from `h.by`, the identical value the scrubber and end-card ticks split on); down on
  the bar the panel already carries a name and a coloured bar, so colour is free to
  carry the tier. Size carries the tier in both.
  For its whole life `.hitmark.arena` had **no CSS rule at all** — the class was a bare
  hook, so the on-video mark rendered identically to the on-bar one: `--hm-life` 420ms
  with ~139ms at full opacity, tier-orange, over moving footage. Six of those across
  `jackpot-copperhead`'s 149 seconds is not a subtle marker, it is an invisible one.
  It now has `--arena-scale` (1.45×) and `--arena-life` (900ms, holding full opacity
  for over half of it). `--hit-self` grey still wins over the side colour, because a
  hazard is neither bot's work.
- **`#strike` and `.hitmark` must agree about the same blow.** `#strike` had no `.self`
  rule, so an incidental hit painted the bar burst grey and the crosshair heavy-orange
  simultaneously. And `SELF / ARENA` was one label for two different things the
  contract cannot distinguish — `clean: false` with `by` on the victim means both "the
  screws did it" and "the bot cooked itself". `blameFor()` reads the blame off the
  weapon string, which is the one field that does know, and says `ARENA` when the
  weapon names one.
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
  the source, the prediction label and the opaque `by` token. That indirection is
  the whole reason the pre-fight `#preds` block and the `04 / CROWD` card cost
  no re-judge — the contract never had to grow a field. It also means a re-scrape
  that drops a string a timeline still references degrades that one comment to
  an unresolved lookup; run `--rejoin` straight after a scrape. `check_timelines.py` asserts
  every `fan_comment` still resolves, so that degradation is now caught rather than
  noticed in a demo.
- **One side can legitimately have NO showable quote, and the grid has to cope.**
  `crowdCall()` filters `!c.rival`, and on `madcatter-tombstone` the only `tombstone`
  pick is a rival comment — so `loudest('R')` is `null`. Hiding the empty
  `<blockquote>` was not enough: `.pq` is `1fr 1fr`, so it rendered one quote against
  a blank half, and one take BESIDE the opposing one is the entire point of the card.
  `.pq.solo` goes full width instead. Do **not** reach for the other fix and show the
  rival pick — a rival comment counts in the tally and is never displayed.
  The pool genuinely cannot fill that quote: the one latent Tombstone vote says
  *"still rooting for the king of kinetic energy"* and never names Tombstone, so
  `void_flips()` voids the pick, correctly. `--reclassify` was tried and re-labelled
  two comments `banter` → `prediction` without changing that, which is the honest
  answer, not a failure.
- **`--reclassify` re-runs the labels over a pool already on disk, with no scrape.**
  `crowd.classify()` only ever ran inside `scrape()`, so improving a label used to
  mean paying Bright Data again — and re-scraping the same pinned thread can quietly
  return a *worse* set, which the zero-rows guard does not catch because it only
  fires on nothing at all. It touches `pick`/`phase`/`kind` and never `text`, so it
  cannot orphan a `fan_comment` and needs no `--rejoin`. It is non-deterministic and
  re-runs `pair_exchanges()`, so the `ex` pairs can shuffle: diff before committing.
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
- **That same `z-index: 8` also lifts the badge over the FIGHT CARD, so PERFECT read
  twice** — once beside the winner's dimmed HUD panel and again in the card's DAMAGE
  panel. `.screen` is `z-index: 5`, so anything that beats the fireball beats the card
  as well. Containing `#hud` in its own stacking context fixes it and re-breaks the
  fireball ordering, which is the whole reason the 8 is there; `body.over .perfect`
  costs one class, set in `finish()` and cleared in `showFight()` and `reset()`. The
  badge deliberately comes back on a rewind — the fight really did end that way.
- **The GAME OVER exits live ABOVE the breakdown; the key list stays at the bottom.**
  Four stacked panels put the last of them below the fold on a laptop, so BACK TO FIGHT /
  REPLAY / HOME parked underneath could only be reached by scrolling past everything you
  might want to skip. The `.hint` line is reference, not an exit, so it reads last.
- **A key that HAS a button is printed on it; only keys with no button are left to the
  hint.** `#pmenu`/`#omenu` buttons carry an `<i class="k">` cap, so the fight card's hint
  is down to `C — CRT` and the pause menu's to the transport keys. The cap is
  `pointer-events: none` — `menuClick()` reads `data-act` off `e.target`, and a click
  landing on the cap would otherwise hit an element that has none. POST MATCH is the one
  button with no cap, because it is the one action with no key behind it.
- **POST MATCH seeks, it does not jump to `finish()`.** The pause menu's skip-to-the-end
  goes through `pbSeek(lastEvent.t + 0.2)` (which already handles both clocks) and then
  calls `tick()` **by hand**, so `reseat()` re-derives the bars, the caption and the hit
  count for that moment and re-applies the knockout **quietly** — the fireball, the shake
  and the announcer belong to the instant the KO is crossed, and this is the one path
  that deliberately skips it. Calling `tick()` inline matters: left to the next frame,
  `finish()` would already have read the state `reseat()` was meant to produce. BACK TO
  FIGHT off a skipped card lands at the end of the clip and rewinds normally.
- **One sampled sound, and one only.** Everything else is oscillators; `sfx/perfect.mp3`
  is an announcer line. **The shipping take was picked by ear in the ElevenLabs studio**
  (a voice clone the API's voice list does not offer) and dropped in whole — it is not
  the output of `backend/say.py`, which exists to make the asset reproducible and can
  only approximate it. That is why `say.py` now **refuses to overwrite an existing
  `sfx/<name>.mp3` without `--force`**: nothing downstream could tell a chosen take from
  a regenerated one, since the frontend only ever checks that the file decodes. Its
  `deepen()` (ffmpeg resample + echo — dropping the formants with the pitch is what
  reads as a big voice rather than a slowed-down small one) is still there for a fresh
  line. It is committed and served statically: no key in the browser, no API call at runtime. It decodes through
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
- **…but reserving heights could never finish the job, because `#preds` is the thing
  that moves and its presence is not knowable in advance.** Measured with the JSON
  fetches lagged 400ms: the crowd block goes 0 → **195px**, and `.screen` is
  `justify-content: center`, so the h1 rose 110px and the picker fell 111px *long after*
  the card looked settled. A `min-height` on the block is wrong on exactly the clips
  that have no picks — `synthfight`, `?demo=1`, anything whose comments file 404s — and
  which those are is only known once the file lands. So the card is now laid out but
  **held at `visibility: hidden` (`.screen.staging`) until every part of it has arrived**,
  then shown in one paint: `showTitle()`, racing the comments *and* the picker's other
  two timelines against `TITLE_WAIT_MS` so a hanging fetch cannot leave the screen
  blank. `visibility`, not `opacity` — layout has to happen underneath, because
  `sizeCaption()` and the picker both measure during that window. Two consequences worth
  keeping: the NO TIMELINE error path must call `showTitle()` itself or the one screen
  that explains the failure never appears, and `start()` is gated on `booted` so a click
  landing in the staging window cannot start a fight nobody can see yet.
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
  adding a clip is a one-line change. Any clip in that array must exist in the **R2
  bucket** (`gameover-clips`) or the public site will 404 it — it is no longer a git
  question, and a clip added to `clips/` on disk is now invisible to the deploy.
  `synthfight` is still reachable at `?clip=synthfight`.
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
  `t = (N-1) / fps`. Default is now **2 fps**, and all three demo clips are extracted
  and judged at it — `jackpot-copperhead` was the last one still on 0.5 (72 frames,
  and no `meta.json`, which `extract()` correctly treats as stale) and is now 299.
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

**The title card does not fit a 720p viewport with the crowd call in it.** Measured
at 1280×720 it is 744px, and `.screen` is `justify-content: center`, so the overflow
clips at BOTH ends — the GAMEOVER title off the top and the era B input off the
bottom. `@media (max-height: 760px) { #preds { display: none } }` is the release
valve, and its comment states the intent: *drop the predictions rather than clip the
card*. It was set at 700px, which is below the most common laptop viewport there is,
so it never fired on the screens it was written for. Without `#preds` the card is
591px. Anything added to the title card must be checked against this — and the fight
picker's key hint is `position: absolute` at the bottom precisely so it does not
count, because in the flow it would have pushed the card 45px further over.

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
