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

## Outstanding — highest value first

### 1. Two clips are still judged by the OLD pipeline

`jackpot-copperhead` and `manta-skorpios` were **deliberately not re-judged** —
only one clip's worth of API spend was authorised. Their timelines are still
hp-number output from before the merge, so on those two:

- the winner's bar barely moves (Copperhead pinned at 100 for 140s);
- there are no `hit` fields, so no weapon labels and no attribution — the HUD
  falls back to "the other bot", which is correct but plain;
- deltas are not ladder values, so they land in tiers a bit arbitrarily.

**Lead the demo with `madcatter-tombstone`** (it is already the no-`?clip=`
default). When you do re-judge the other two:

```bash
nohup .venv/bin/python -u backend/analyze.py jackpot-copperhead.mp4 \
    --backend openai --bots "Copperhead,Jackpot" > /tmp/jc.log 2>&1 &
nohup .venv/bin/python -u backend/analyze.py manta-skorpios.mp4 \
    --backend openai --bots "Manta,Skorpios" --ko left > /tmp/ms.log 2>&1 &
```

`manta-skorpios` **must** have `--ko left` — see the CLAUDE.md fights table for why.
Jackpot is the slow one, ~24 batches. Roughly 3 minutes per 14 batches in practice.

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

### 4. Fan comments are thin on two clips

`jackpot-copperhead` has 1, `manta-skorpios` has 2. Discovery searches the whole
subreddit, so genuine moment-by-moment reactions are rare. Options: a tighter
scrape query, or raise `POSTS_FOR_COMMENTS` in `scrape_comments.py`. Do **not**
loosen `is_showable()` / `names_a_rival()` — see the content warning in CLAUDE.md.

### 5. `frontend/index.html` is ~1390 lines against a ~700 target

CLAUDE.md wants the core near 700. Cheapest trims are the `.bd-tier` pixel chips
(→ a plain `2 HEAVY · 5 SOLID` text line) and `#strikeby` (fold the weapon into
`#massive`). Not urgent; noted so it does not creep further unnoticed.

### 6. `ingest.py` cannot pass `--ko`

Its `analyze()` call still forwards only `bots`. Era B has no way to set the KO
side. Fine while nobody has watched those clips, but it is a one-line gap.

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
