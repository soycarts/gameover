# Handover — 29 Jul 2026

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
  with a damage word per bot; `SEVERITY` maps those to 4/12/22/35 points; `pay()`
  spends a fixed budget on the worst moments and zeroes the surplus.
- **The frontend owns *how it looks*.** `deriveHits()` reads hp deltas and `TIERS`
  bands them at 1/10/20/30 into graze / solid / heavy / massive.
- **They meet only at the hp delta**, and the ladder quantises every delta to
  exactly one of four values, so each rung lands squarely in one tier.

Keep the two tables in step. Move a rung on either side without the other and a
whole category of hit silently changes colour, size and whether it shakes the
screen.

`hit {by, weapon, clean}` is orthogonal to both — it carries only what the model
can see. Damage, victim and tier stay derived, never stored.

## Works and verified

- **Both health bars move.** `madcatter-tombstone` re-judged against the merged
  prompt: MaDCaTTer 100 → 92, Tombstone 100 → 0. It used to be pinned at 100 for
  all 79s, which was the top outstanding problem in the previous handover.
- **The enriched path has now been seen in a browser** — it never had been. Real
  weapon labels on both sides (MaDCaTTer "vertical spinner", Tombstone "horizontal
  bar"), 9 of 10 hits labelled, all four tiers exercised.
- **The two hit-count paths agree**: live counter, per-side split and the breakdown
  panel all read 8 + 2 = 10.
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
- **The GAME OVER exits sit above the breakdown**, not below four stacked panels.
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

### 1. One clip is still judged by the OLD pipeline

`manta-skorpios` is current (2 fps, commentary on the corrected `t0` timing,
`--regrade`, `--stop-pass`, and the count-start fix — 3 hits for Manta, count from
t=16.0).
`madcatter-tombstone` predates `--regrade`, `--stop-pass`, `--verify`, the count-start
fix and the caption-timing fix; its captions were **0.81s** early. Its `source.json` now
carries the right `t0`, so a re-transcribe (`--force`, **with `--looks`** — the garble
guard is inert without it) plus a ~14 min re-judge brings it level. Worth doing before
any demo. Scanned for the same garble class and it is clean: neither
`madcatter-tombstone` (39 cues) nor `jackpot-copperhead` (75) contains a single passive
`"<bot> got hit"` cue, so the guard is targeted rather than a broad filter and should
change nothing on either clip.
`jackpot-copperhead` has **not** been re-judged at all — only limited API spend was
authorised. It is still pre-merge output: the winner's bar barely moves (Copperhead
pinned at 100 for 140s), there are no `hit` fields so no weapon labels, and deltas
are not ladder values so they land in tiers a bit arbitrarily. Its `ko` side is
correct, so the crowd card is safe on it.

**Lead the demo with `manta-skorpios`** — it is the only clip judged by the current
pipeline end to end. When you do re-judge the other two:

```bash
nohup /Users/carter/dev/gameover/.venv/bin/python -u backend/analyze.py jackpot-copperhead.mp4 \
    --backend openai --bots "Copperhead,Jackpot" --regrade --stop-pass > /tmp/jc.log 2>&1 &
```

Extract at 2 fps first (`extract_frames.py <clip>.mp4 --fps 2`) and transcribe
(`transcribe.py <clip> --bots "..."`), or it judges on stale 0.5 fps frames with no
commentary. Jackpot's frames are also still cut to the OLD shorter clip — it was
re-cut to 149.4s and never re-extracted. It is the slow one: ~299 frames at 2 fps.

**Back the timeline up before any re-judge.** `analyze()` refuses to overwrite only
when a *batch failed*; a clean run that comes back worse still lands on the good file.

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

### 3. Jackpot's sprite is a placeholder

Still a neutral red body rather than a wrong mechanism, because nobody confirmed
what weapon Jackpot runs. Fix the rows in the `ART` table in `frontend/index.html`
— a 16x12 character grid, no rebuild. Same table is where a new bot gets added.

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

## Traps that cost time

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
