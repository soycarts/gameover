# Handover — hitmarkers, hit counting, breakdown panel

> ⚠️ **Read this first: three branches are editing damage judging at once.** This
> file was written before I noticed, and it is **not** merged with the `HANDOVER.md`
> that now exists on `main`. Both are live; see "Branch collision" at the bottom.


Branch `claude/hit-counter-visibility-ui-942ff0`, worktree
`.claude/worktrees/public-repo-212b9d`. Code is committed as **b0fd604**. The only
outstanding work is finishing the timeline re-judge (below).

## What landed

**The problem.** `#hits` had three different answers: `fire()` counted
`max(dl,dr) > 0` so a both-bots exchange scored one hit; `statsCard()` counted per
side and scored two (22 vs 24 on `madcatter-tombstone`); and a backward scrub set the
counter to 0 and never recounted. Nothing said who landed anything.

**The fix.** One definition — *one hit = one bot losing armour at one moment* — in one
function, `deriveHits()` in `frontend/index.html`. It runs once at load; `fire()`, the
`#hits` readout and the breakdown all read its output. `statsCard()` is gone. Details
are in the CLAUDE.md gotchas, which was updated in the same commit.

**On screen.** Every hit throws a pixel `.hitmark` over the core that actually
drained, sized/coloured by tier (`graze 1-4 · solid 5-9 · heavy 10-19 · massive 20+`).
Heavy and up also throw the full-stage `#strike` crosshair naming attacker + weapon.
The counter now reads `HITS LANDED nn` / per-side attribution / last hit. `#over` is
three cards in the DESIGN_ARTIFACT language: **01 / DAMAGE**, **02 / BIGGEST HIT**,
**03 / HIT LOG** (every hit plotted across fight time).

**Backend.** Events gain an optional `hit` `{by, weapon, clean}` — only what the model
can see. Damage, victim and tier stay derived, never stored. `normalize_hit()` drops
anything with no damage behind it; `validate()` asserts the rest. The per-call state
reminder is now `state_reminder()`, shared by all three backends, and re-states the
hit rule (without it the model honours `hit` for a batch or two then forgets it).
`analyze.py` gained `--bots`, matching `ingest.py`.

## Verified

- `?clip=synthfight` — **zero** `hit` fields, the fallback path. 15 hits derived,
  hitmarkers/counter/breakdown all correct.
- `?demo=1` — rAF fallback clock, same result.
- Backward scrub — 30s → `09`, back to 10s → `03`, end → `15`, back to 0 → `00`.
  Every position matches its expected prefix. This was the `hits = 0` bug.
- Live total == breakdown per-bot sum (8 + 7 = 15). If those ever diverge again,
  something reintroduced local hit math.
- Reduced motion — hitmarkers hold static and visible instead of snapping to their
  faded-out end frame.
- Crosshair and hitmarker geometry confirmed by screenshot (see note below).

Not yet seen in a browser: the enriched path with **real weapon labels**, because the
timelines carrying them are still being generated.

## Outstanding — finish the re-judge

A background run is judging all three clips with pinned names. State when this was
written:

| clip | state |
|---|---|
| `manta-skorpios` | **done**, `Manta vs Skorpios`, 4 events |
| `madcatter-tombstone` | mid-run; working tree currently holds a **stale first-pass** version with `Bot A vs Bot B` |
| `jackpot-copperhead` | untouched, still the committed HEAD version |

If the run died, restart it:

```bash
cd /Users/carter/dev/gameover/.claude/worktrees/public-repo-212b9d && PY=/Users/carter/dev/gameover/.venv/bin/python && export OPENAI_MODEL=gpt-5.5 && $PY backend/analyze.py madcatter-tombstone.mp4 --backend openai --bots "MaDCaTTer,Tombstone" && $PY backend/analyze.py jackpot-copperhead.mp4 --backend openai --bots "Copperhead,Jackpot"
```

Roughly 14 + 24 batches; jackpot is the slow one (~15-20 min).

Then review `git diff timelines/` before committing:

- every `"hit"` sits on an event whose hp went down (else `validate()` would have
  aborted, but eyeball a few);
- no `hit` at `t: 0.0`;
- the KO event is still last and still carries `"ko"`;
- `hit.by` agrees with its caption — a *"left armour torn off"* caption should read
  `"by": "right"`;
- bot names are the pinned ones, not `Bot A` / `Bot B`.

Finally load `?clip=madcatter-tombstone` and confirm weapon labels appear on the
crosshair and in **02 / BIGGEST HIT**.

**Rollback if a re-judge comes back worse:** `git checkout timelines/`.

## Things worth knowing

- **Always pass `--bots` when re-judging.** Name detection depends on whether a
  lower-third happens to be legible in the sampled frames. The first pass returned
  `Bot A vs SKORPIOS` and `Bot A vs Bot B` for clips that had resolved correctly
  before. This is now in CLAUDE.md's clip table.
- **Attribution density varies.** The first madcatter pass attributed only 4 of 13
  damaging events. Partly the model drifting off the field (fixed by
  `state_reminder()`), partly correct behaviour — that fight ends in a long fire, and
  "right bot engulfed in flames" genuinely isn't a blow. Unattributed hits still
  count and still get a hitmarker; they just fall back to "the other bot".
- **`.env` was copied into this worktree** so `backend/config.py` could find
  `OPENAI_API_KEY` (config resolves `.env` from the repo root, and a worktree has its
  own). It is gitignored. Delete it if you'd rather not have a second copy.
- **Your `serve.py` on :40911 serves the main repo, not this worktree.** I left it
  alone and used `python3 backend/serve.py 40922` for verification.
- **Verifying transients headlessly:** `tick()` never advances on its own (rAF stalls
  with no paint), so drive it by setting `video.currentTime` then calling `tick()`.
  A `.hitmark` is long gone by the time a screenshot lands — freeze it with
  `animation: none; opacity: 1` rather than trying to catch it. Slowing the animation
  does *not* work; it just stretches the fade-in so the capture arrives at
  `opacity: 0`. Both are now in CLAUDE.md.
- **Size budget.** `frontend/index.html` is ~1375 lines, up from 928. CLAUDE.md wants
  the core near 700. If you want it back down, the cheapest trims are the `.bd-tier`
  pixel chips (→ a plain `2 HEAVY · 5 SOLID` text line) and `#strikeby` (fold the
  weapon into `#massive`).

## Branch collision — resolve before anything else

Three branches forked from `419b423` and all three rewrite damage judging. Nothing
here is merged.

| branch | what it did | touches |
|---|---|---|
| `main` @ `1d6b1a9` | weapon sigils, bot sprites, captions that name the bot, "judge BOTH bots every frame" damage-balance fix, HTTP Range, **its own `HANDOVER.md`** | `analyze.py`, `prompt.txt`, `index.html`, all timelines |
| this branch @ `74ea6fb` | the `hit` contract, one hit definition, hitmarkers, breakdown panel | `analyze.py`, `prompt.txt`, `index.html`, timelines |
| `claude/vision-shake-detection-1b7ee7` @ `cf5f191` | *"Judge damage by severity word, not by nudging an hp number"* — a competing severity model, and it **removes** main's bot sprites | `analyze.py`, `prompt.txt`, `index.html`, timelines |

**The third branch is the one to reconcile first.** It replaces hp-number judging with
a severity ladder, which is the same problem my `TIERS` table solves — but mine
derives tiers from hp deltas in the frontend while it moves severity into the model.
Those two designs cannot both be right; pick one before merging either.

**`prompt.txt` is the sharpest conflict.** Mine is based on the pre-`96aa2f9` version
plus a `hit` block. Main's has since gained identity tracking, `left_look`/`right_look`,
"judge BOTH bots every frame", non-competitor exclusion, and bot-named captions. A
plain merge would silently drop those. The combined file needs main's rules **and** my
`hit` rules.

### Suggested order

1. Decide between this branch's derived tiers and `vision-shake`'s model-judged
   severity.
2. Merge `main` into the winner. Hand-reconcile `prompt.txt` (union of rules),
   `analyze.py` (main's `name_captions()` + my `normalize_hit()`/`validate()`
   assertions — they don't overlap), and `index.html` (main's sprites + my
   hitmarkers/breakdown; both edit `:root` and the bottom row).
3. **Then** re-judge, once, with the merged prompt. Not before — see below.
4. Re-join comments afterwards; main's `HANDOVER.md` §2 has the free re-join snippet
   that skips the vision model.

### What I stopped, and why

My background re-judge of `madcatter-tombstone` and `jackpot-copperhead` was killed
mid-run and the half-written `madcatter-tombstone.json` reverted to HEAD. It was
judging against **my** `prompt.txt`, which predates main's identity tracking, named
captions and non-competitor rules — so its output would have been a regression on
those axes even though it carried `hit` data. Any re-judge should wait for the merged
prompt. `manta-skorpios.json` (committed in `74ea6fb`) has the same caveat: it carries
good `hit` attribution but was judged without main's improvements, so expect to redo
it too.

Also note main's `HANDOVER.md` §1 reports that `jackpot-copperhead` and
`madcatter-tombstone` had the **winner stuck at 100 hp** for the whole fight, and that
its prompt fix for that is still UNVERIFIED. That bug is independent of this work but
would make the new breakdown panel look broken (one bot with zero damage taken), so
it is worth confirming in the same re-judge.
