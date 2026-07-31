# Handover — 31 Jul 2026

State of play, what is trustworthy, and what to pick up next. Read
[CLAUDE.md](CLAUDE.md) first for architecture and commands; this file is only the
open loops.

**This replaces three competing HANDOVER.md files.** Three branches forked from
`419b423` and all three rewrote damage judging, each with its own handover warning
about the other two. They are now merged and those branches are gone. If you find
a reference to a "three-way collision", it is stale — it is resolved.

## The design, now that it is one design

Two of the three handovers claimed the severity ladder and the frontend tier table
were rival designs and that someone had to pick one. That was wrong, and it is
worth understanding why, because the shape matters:

- **The backend owns *how much*.** The model never emits hp. It rates each frame
  with a damage word per bot; `SEVERITY` maps those to relative weights;
  `normalise()` shares one target across every surviving blow in proportion.
- **The frontend owns *how it looks*.** `deriveHits()` reads `hit.sev` and `TIERS`
  bands it into graze / solid / heavy / massive.
- **They meet at `hit.sev`, not at the hp delta.** That changed on 31 Jul and it
  is the single most important thing on this page.

**Why it changed.** `pay()` spent a fixed budget (55 live / 70 ko) on the worst
moments and zeroed the rest. The budget was absolute while a fight's length is
not, so `jackpot-copperhead` — 140s of events — got the same allowance as
`manta-skorpios`'s 27s and came out with both budgets exhausted to the point
(Copperhead 52/55, Jackpot exactly 70/70) against raw totals of 240 and 164.
**Thirty-five captioned moments, seven that move a bar.** On screen that is
"Jackpot throws Copperhead onto screws" typed over a frozen health bar, and it is
what a viewer notices before anything else on the page.

**Why it is safe.** CLAUDE.md used to forbid exactly this — "do not fix it by
scaling every hit down to fit; that reconstructs the 3–5 point drip". That warning
was right about the *original* pipeline for one specific reason: it emitted
absolute hp with **no rung behind it**, so a 3-point delta could not be banded,
coloured or shaken. Here the rung survives as `hit.sev`. The delta is now purely
*how much bar*; the rung is *how hard*. **Do not put those back together.** If you
ever find yourself writing `dmg >= 10` in the HUD, that is the regression —
`SHAKE_AT`/`MASSIVE_AT` were exactly that and are now `SHAKE_TIERS`/`HARD_TIERS`.

`hit {by, weapon, clean, at, sev}` still carries only what the model can see.
Damage and victim stay derived. `sev` is stored for the same reason `drain` is:
under normalisation it is no longer a function of two adjacent events.

## Works and verified

- **Both health bars move on every clip.** `madcatter-tombstone` finishes
  MaDCaTTer 100 → 46 against Tombstone 100 → 0, and `jackpot-copperhead`
  Copperhead 100 → 52 against Jackpot 100 → 0. Both used to have the winner pinned
  at 100 for the whole fight, which was the top outstanding problem in the previous
  two handovers.
- **The enriched path has now been seen in a browser** — it never had been. Real
  weapon labels on both sides (MaDCaTTer "vertical spinner", Tombstone "horizontal
  bar"), 9 of 10 hits labelled, all four tiers exercised.
- **The two hit-count paths agree**: on madcatter the live counter, per-side split
  and breakdown panel all read 4 + 5 = 9; on jackpot 4 + 3 = 7.
- **The fallback path still works.** `?clip=synthfight` carries no `hit` fields at
  all and still derives 15 hits with correct tiers — that is the regression test
  for era B and the demo timeline, so keep it that way.
- **Backward scrub recounts** rather than zeroing: 00 → 09 → 03 → 15 → 00.
- Sprites, footage crops, weapon sigils, bot-named captions, the fight picker,
  HTTP Range and the filtered Reddit comments all survived the merge intact
  (audited file by file against each branch).

- **The clips now play through to the BattleBots card.** `koSequence()` no longer
  pauses on the K.O. stamp; it plays over the live celebration and GAME OVER waits
  for the video to run out. `manta-skorpios` and `jackpot-copperhead` were re-cut
  longer to reach the card (`madcatter-tombstone` has none — it is last in the
  compilation and runs into a YouTube outro). **The re-cut needed no re-judge**:
  `-ss` is independent of `-t`, so the clips are byte-identical at the front and
  every timeline timestamp still lines up — verified by single-frame MD5s.
- **The count-out reads as a count.** `COUNT 1`…`COUNT 10` in the loser's status
  line, derived from the `drain` run, filling the ten seconds that used to be
  twelve events with empty captions.

- **Manta's third hit is back.** The count window zeroes every loser-side cost from
  its start, so *"Manta launches Skorpios airborne"* at t=15.5 scored nothing and
  landed as a caption over a frozen bar. `immobile_from()` now breaks its backward
  walk when the loser TAKES damage, not only when it lands a blow, bounded by
  `MIN_COUNT_SECONDS`. Re-judged: the count starts at t=16.0 instead of t=14.0 (11s,
  against the broadcast's own ~10s) and **Manta finishes 3 hits / 66 dealt** against
  Skorpios' 2 / 16. Verified end to end in a browser.
- **Playback controls.** A hover-revealed bar (play/pause, ∓10s, a scrubber marked
  with every hit and the KO, a clock, mute) and an Esc pause menu with
  RESUME / REPLAY / HOME. `replay()` was split into `reset()` + `start()` so HOME
  reuses the proven teardown. Works on the virtual clock too, so `?demo=1` keeps the
  same controls.
- **Seeking is safe.** A forward jump used to fire every crossed event in one frame.
  See the catch-up rule and the `userPaused` watchdog note in CLAUDE.md — both were
  latent bugs the scrub bar merely exposed.
- **The summary screen says one thing once**: `DAMAGE` / `BEST BLOW` / `HIT LOG`, no
  numbered eyebrows, and the KO is a full-height gold line rather than a tick that
  read as a left-side hit.
- **A long caption no longer resizes the HUD.** It was squeezing the health cores
  from 69px to 27px and rewrapping the fan comments; the caption now keeps its
  previous line faded above the current one.

- **The caption offset is fixed** (was item 0 here). `ingest.cut_window()` records
  the keyframe the cut actually landed on as `t0` in `source.json` and
  `transcribe()` maps cues from it, so the judge no longer sees commentary ~1s
  ahead of the frames. Verified before spending anything: every manta cue moved
  **+1.02s** and "Dream is already over for Skorpios" now lands at 24.6s against
  the broadcast's own `KNOCKOUT : 24sec`. `manta-skorpios` was re-judged on the
  corrected transcript — same winner, Manta still 3 hits, count still from t=16.0.
- **GAME OVER is no longer a dead end.** Esc steps back into the fight (paused, so
  it can be rewound) and the card carries BACK TO FIGHT / REPLAY / HOME.
- **Hit ticks read as bot identity** — blue/orange on both strips, tier as height.
- **Space starts the fight**, not any key. `h` goes home from the fight card.
- **PERFECT.** A bot that finishes on zero damage taken gets an arcade badge beside its
  HUD panel at the K.O. and on the fight card, with a spoken announcer line
  (`sfx/perfect.mp3`, the repo's only audio asset — a take chosen by ear, which is why
  `backend/say.py` will not overwrite it without `--force`). It fires on
  `manta-skorpios` only; on the other three both bots take damage, which is what makes
  the shutout worth marking. The HUD badge stands down while the fight card is up
  (`body.over`) so PERFECT is only ever on screen once, and comes back on a rewind.
- **The GAME OVER exits sit above the breakdown**, not below four stacked panels; the
  key list stays at the bottom, where reference belongs.
- **POST MATCH** in the pause menu skips to the fight card without watching the rest of
  the clip — it seeks and lets `reseat()` land the end state quietly, so BACK TO FIGHT
  off it still rewinds normally.
- **The title card is held until it is complete, then shown in one paint.** Reserving
  heights was not enough: measured with the fetches lagged, `#preds` goes 0 → 195px and
  re-centres the whole card, and whether it appears at all is unknowable until the
  comments file lands. `.screen.staging` holds it at `visibility: hidden`; `showTitle()`
  reveals it. Fixing the earlier round also uncovered that `#preds` could never be
  hidden at all, so every clip painted an empty CROWD CALL header.
- **Three false hits on Manta are gone.** Two were reported by eye (t=7.5 "Skorpios
  forks lift Manta" and t=14.5 "Skorpios nudges stuck Manta" — the frames show
  Skorpios settling after being lifted, and both machines apart and still); a third
  at t=5.5 had the same cause and had not been noticed. All three were the
  `"Manta got hit by that / huge drum spinner"` auto-caption garble read literally,
  charging the winner 20 hp across three frames — the exact signature this file and
  CLAUDE.md already record. Three independent guards now stand between that garble
  and the timeline: `drop_own_weapon_garbles()`, `drop_downed_hits()` and `--verify`.
  See the attribution entry in [CLAUDE.md](CLAUDE.md) for why nothing older could
  catch it.
  **The honest result is a shutout, and it shows.** `manta-skorpios` now reads Manta
  3 hits / 66 dealt / **0 taken**, Skorpios 0 — which is what a 24-second knockout of
  a bot that died around t=8 actually looks like, and it matches what the owner sees
  in the footage. The cost is that the winner's health bar never moves, so the run
  ends on the `! SHUTOUT: Manta takes no damage` warning. That warning is doing its
  job; do not "fix" it by loosening the guards, and do not re-run `repass()` on it —
  that is exactly the mistake described below.
- **`manta-skorpios` t=12–21.5 is NOT a replay**, whatever this repo said before. The
  match clock is genuinely absent t=11.0–22.0, but that is a camera change (driver
  booth, then a low ringside angle), not slow motion. Corrected in CLAUDE.md.

## Outstanding — highest value first

### 1. All three clips are on the current pipeline — done

Every clip is now 2 fps, judged with `--bots`, `--looks`, `--regrade` and
`--stop-pass`, on commentary remapped through the corrected `t0`, and all three pass
`python backend/check_timelines.py`:

| clip | events | drain | hits | `at` | deltas | result |
|---|---|---|---|---|---|---|
| `manta-skorpios`      | 17 | 12 | 3 | 3/3 | 22,22,22 | KO, Skorpios |
| `madcatter-tombstone` | 31 | 16 | 9 | 9/9 | 4,12,22  | KO, Tombstone |
| `jackpot-copperhead`  | 38 |  5 | 7 | 6/7 | 4,22     | TAP OUT, Jackpot |

**`jackpot-copperhead` had silently regressed.** `cf5f191` re-judged it onto the
severity ladder; `f7f9ecb` then took *main's* side of the file in a merge and the
pre-ladder version was back at every commit for three days. Nobody noticed, because a
reverted timeline still loads, still validates and still plays. That is what
`check_timelines.py` now exists to catch. **Run it after every merge, before
pushing.**

It is now **two-era aware**, because the clips are deliberately in two states. A
timeline whose hits carry `sev` is *normalised*: every non-count delta ≥1, `sev` on
every hit, and the eliminated bot's blows summing to `KO_BLOW_TOTAL` (85) exactly.
One with no `sev` anywhere is *ladder*: the old fixed-budget pipeline, where every
non-count delta lands on a `SEVERITY` rung. **A judged clip in neither state is
stale** — deltas off the rungs *with no `sev` to explain them* is a sharper
`f7f9ecb` detector than the ladder check alone was. Only `jackpot-copperhead` was
re-judged onto normalisation; madcatter and manta stay on the ladder, which is why
both branches are live and neither is dead code.

**`jackpot-copperhead` needs `--ko right`, and the reason is worth reading.**
Copperhead took *more* raw damage than Jackpot (240 vs 164) and still won. The damage
cross-check's "the more-damaged bot loses" rule is simply wrong for a fight decided by
immobilisation rather than damage, and on the first attempt it inverted the whole
fight — putting the referee count on the winner and writing a timeline whose own last
caption read "Jackpot taps out" above `ko: left`. `KO_MARGIN` now stops it overruling
the model's flag on anything less than a decisive margin (it did this on 4.5%), but the
pin is still the right call here.

Pinning trips the "may be inverted — check --looks" warning, so it was checked against
the footage rather than assumed: frames 263 and 281 both show the green chassis with
red forks and the RAPID AXIS / makerX decals — Jackpot — smoking, a wheel gone,
immobile at the wall, and the celebration shot at t=140 is a kid in a COPPERHEAD
shirt. Identity is correct. Do not "fix" this by flipping the sides.

**Known cosmetic inaccuracy on this clip:** the HUD writes `COUNT 1…10` into the
loser's status line for any run of `drain` events, and the fight card prints FINISHED
BY COUNT-OUT — but jackpot ends on a **TAP OUT** graphic, which is a team conceding,
not a referee count. The contract has no field distinguishing the two, and this only
became visible now that the clip has `drain` events at all. The bar drain itself is
right; only the label is imprecise. Fixing it means growing the contract, so it is
left as a deliberate, recorded inaccuracy.

**Not a bug: `~ dropped unusable hit at t=5.5s` on manta.** "Manta drum sparks
Skorpios wedge" sits exactly `MERGE_WINDOW` (1.0s) from the solid at t=6.5 and the
comparison is inclusive, so `merge_blows()` folds them into one blow with a
follow-through. That is the function doing its job — the caption survives, the second
hp drop does not. Do not chase it.

`analyze()` runs the comment join itself, so a re-judge needs no follow-up
`--rejoin`; only a re-*scrape* does.

### 1a. `manta-skorpios` was re-judged `--ko left` on a branch. That is backwards.

**Do not repeat it.** A branch merged here re-judged the clip with `--ko left`,
producing `Manta 0 / Skorpios 78` — Manta losing — and wrote a handover asserting
the committed `ko: right` had been "the KO on the wrong robot". It is the other way
round, and three independent sources agree:

- **The footage.** `frames/manta-skorpios/0041.jpg` (t=20) and `0051.jpg` (t=25)
  are the same machine in the same spot, motionless: a copper forked wedge with a
  teal vertical blade and teal wheels. That is *Skorpios*, matching the verified
  `--looks` string. Manta is the low blue wedge with the yellow drum.
- **The commentary.** t≈23.6s: "Dream is already over for Skorpios in this fight,
  in just 24 seconds", against the burned-in `KNOCKOUT : 24sec`.
- **The crowd.** `comments/manta-skorpios.json` has 10 pre-fight picks for Manta
  against 4 for Skorpios. With the inverted timeline the new crowd card would have
  told visitors the crowd called it wrong.

`--ko` names the **LOSER**, and Skorpios loses, so it is `--ko right`. The
`! KO flagged on right, but --ko says left` line that run logged was the model
being right and the flag being wrong — the cross-check firing is a reason to check
the frames, not proof the flag wins. The resolved timeline here is the `--ko right`
re-judge, verified frame by frame.


### 2. A 30-second caption gap on madcatter-tombstone

Events jump t=32 → t=62 → t=74. The anti-repeat rule in `thin()` silences a
burning bot almost completely, and the "worsening counts as `glance`" line in the
prompt softened it without closing it. The HUD types nothing for half a minute.
Only worth touching if it reads as dead on the big screen — the fan comments and
the hit counter still animate through it.

The KO event also has an empty caption, so the finish lands on GAME OVER with no
line of text. Fixable in the prompt (`finish` frames currently tend to rate both
bots `none`, which forces `caption: ""`).

### 3. Sprites — done, and no longer hand-drawn

Every sprite is now **generated from the official Pro League studio photo** by
`backend/make_sprites.py` into `frontend/sprites.js`, for all 27 roster entries.
Jackpot's placeholder is gone and the question behind it is settled: it is a
**vertical disc spinner** — green chassis, tall red disc, red forks, red-and-black
striped wedgelets, confirmed against both the photo and the team booth at t=56.0.
The old hand-drawn `madcatter` was purple; the machine is a red-and-blue cat face.

`ART` in `index.html` is now **empty and is the override** — it still wins over the
generated sprite, so that is where a hand-tuned fix belongs. Editing `sprites.js`
works until the next regeneration silently reverts it. Adding a bot outside the Pro
League roster is still an `ART` entry.

Run `make_sprites.py --check` and actually look at the page before believing a
regeneration: all three problems found so far (a palette of near-identical reds,
black machines vanishing into the background, a thin linkage breaking into speckle)
were invisible in the numbers and obvious on that page.

### 4. Fan comments — fixed, with one thing left

The thin pools are gone. The episode's fight-card thread is now **pinned** per
clip (`FIGHT_CARD` in `scrape_comments.py`), replies are flattened out of the
nested `replies` field, and a comment covering all three matchups is routed to
the right one by `focus_segment()` rather than dropped. `madcatter-tombstone`
went from *zero* episode comments (14 rows of "Season 7 Rumor Mill" plus an old
SawBlaze thread) to the real thread, and records now carry author, score and
reply structure.

What is still thin is genuine **moment-by-moment reaction** — a fight card is
pre-fight by construction, so `jackpot-copperhead`'s in-fight quotes are all
predictions shown during the fight. `join_comments()` ranks `phase: "post"` above
`"pre"` for exactly this reason, but there is nothing post-fight in that pool to
rank. A post-episode discussion thread pinned alongside the card would close it.

**`jackpot-copperhead` has 0 exchange pairs, and that is a pool fact, not a bug.**
All 9 of its records have `parent: ""` — the reply chains in EP2 are about the
other two matchups, and `focus_segment()` routes by which robots a span names.
`scheduleExchanges()` returns `{}` and degrades gracefully; nothing is broken.
The same pinned thread gives manta 27 comments with 3 pairs and madcatter 22 with
1. Do **not** re-scrape the same thread hoping for more: it is near-certain to
return the same 9 records, and the zero-rows guard only protects against nothing
coming back, not against a *worse* pool. The only thing that closes this is a
second, post-episode thread via `--post-url`, which is a discovery problem.

Do **not** loosen `is_showable()` / `names_a_rival()` — see the content warning in
CLAUDE.md. ~80% filtering on a fight-card scrape is expected, because one card
covers three fights.

### 5. `frontend/index.html` is ~1390 lines against a ~700 target

CLAUDE.md wants the core near 700. Cheapest trims are the `.bd-tier` pixel chips
(→ a plain `2 HEAVY · 5 SOLID` text line) and `#strikeby` (fold the weapon into
`#massive`). Not urgent; noted so it does not creep further unnoticed.

### 6. ~~`ingest.py` cannot pass `--ko`~~ — done

It forwards `ko`, `looks`, `regrade` and `stop_pass` now, so era B can set every
judging flag era A uses.

### 7. Known wart of normalisation: the readout can print `HEAVY −6` next to `SOLID −8`

Within one side a bigger rung always takes more bar — `normalise()`'s share is
proportional to the rung, so it is monotonic. **Across sides it is not**, because
the two bots have different targets and different blow counts, so the eliminated
bot's `solid` can cost more hp than the survivor's `heavy`. Both numbers are
honest — the tier says how hard, the number says what happened to that bar — and
they are only ever juxtaposed by a viewer comparing two different moments. Left
alone deliberately; dropping the number would lose the more useful of the two.

## Traps that cost time

- **An EMPTY exported variable shadowed the key in `.env` and 401'd everything.**
  `load_env()` skipped any name already `in os.environ`, and this shell carried
  `OPENAI_API_KEY=` with no value — so the good key in `.env` was never read. It
  reads exactly like "the key in `.env` is broken", which is the same wrong
  conclusion the worktree-`.env` trap produces. Fixed in `config.py` (it now tests
  truthiness, matching `get()`), but the habit is the real fix: **fingerprint the
  resolved key before any paid run.** `sha256`, first 8 chars — `e3b0c442` is the
  hash of the empty string, and seeing it is the whole diagnosis. Never print the
  key itself. The one-liner is in CLAUDE.md's commands block.
- **`python … > log 2>&1` block-buffers, so a long run's log stays 0 bytes.** It
  looks exactly like a hung process. Use `python -u`, or check `ps -o etime=` on
  the pid rather than the log, before concluding anything is wrong.
- **A three-way merge can duplicate a whole code block without conflicting.** The
  merged `analyze.py` ended up with *both* branches' `--bots` parsers: the first
  parsed the flag and deleted it from `argv`, the second reset `bots = None` and
  could never re-fire. Every re-judge silently ran with no card. It cost a full
  14-batch run that came back `Bot A vs Horizon` — *Horizon* is a sponsor decal,
  which is exactly what `identity_note()`'s competitor-pinning header exists to
  prevent. **After any merge, run the CLI end to end before spending API calls.**
- **macOS has no `setsid`.** Launch long jobs with `nohup … &` and poll the log; a
  long foreground wait gets killed by the tool timeout and takes the job with it,
  leaving a half-written timeline.
- **Check which worktree your dev server is serving.** Ports 40911 and 40922 were
  already occupied by servers from earlier sessions pointed at *other* worktrees,
  and both answered 200 — so a page that looked merged was not. Grep the served
  HTML for something you just changed before trusting it.
- **Headless DOM reads go stale.** rAF and transitions do not advance without a
  paint. Drive the clock by setting `video.currentTime` then calling `tick()`, and
  screenshot before trusting a computed style. Freeze a `.hitmark` with
  `animation: none; opacity: 1` rather than trying to catch it mid-fade.
- **A real `analyze.py` run overwrites the committed fixture** for whichever clip
  you name. `timelines/synthfight.json` is hand-made, not model output; re-judging
  `synthfight` would wreck both the deployed demo and the fallback-path test.
- **Bright Data's "Synchronous (Real-time)" mode is not synchronous** — it still
  returns 202 and a snapshot id to poll. Jobs took 1–6 minutes.
