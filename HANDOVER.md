# Handover — decisive-hit judging (branch `claude/vision-shake-detection-1b7ee7`)

> ⚠️ **Three branches are rewriting damage judging at once, and this is the third
> `HANDOVER.md`.** The other two are on `main` and on
> `claude/hit-counter-visibility-ui-942ff0` (whose "Branch collision" section names this
> branch and commit `cf5f191`). Read all three before merging anything. This branch is
> **4 commits behind `main`** — see "Collision" at the bottom for exactly what that costs.

Committed: `bc1cf74` "Judge damage by severity word, not by nudging an hp number".
Working tree clean apart from the untracked `frames` symlink (now gitignored).

## What changed

The model no longer emits hp. `backend/prompt.txt` asks for a damage word per bot per
frame (`none`/`glance`/`solid`/`heavy`/`catastrophic`) plus a `finish` flag; `SEVERITY`
in `backend/analyze.py` maps those to 0/4/12/22/35. A 3-point delta is not
representable, which is what killed the drift. The `timelines/<clip>.json` contract is
unchanged.

Supporting changes, each earned by an observed failure:
- 1-frame batch overlap + last-two-hits in the footer (`context_note()`, `footer()`) —
  fixes the model narrating one fire as fresh damage on 14 consecutive frames.
- `pay()` — spends a fixed budget (`KO_BUDGET` 70 / `LIVE_BUDGET` 55) on the most
  severe moments, zeroes the rest. Budgets under 100 so only the `finish` flag reaches 0.
- `--bots` and `--ko` CLI flags on `analyze.py`; the card is pinned into every call, and
  the KO side is cross-checked against accumulated damage.
- `thin()` now drops a caption that repeats the previous one.
- Frontend: `SHAKE_AT` 15 → 10, `sfx('hit')` decoupled from the shake gate, two-tier
  shake (`shake(drop >= MASSIVE_AT)`), `ended` listener as a GAME OVER backstop.

## Results

| clip | before (≥10 / ≥20 / deltas in 1–3) | after |
|---|---|---|
| madcatter-tombstone | 5 / 1 / four | **6 / 2 / none** (11 events, ko=right ✓) |
| manta-skorpios | 1 / 1 / none | 2 / 1 / none (4 events, ko=left ✓) |
| jackpot-copperhead | 3 / 1 / **fourteen** | **6 / 3 / none** (16 events, ko=right ✓) |

`jackpot-copperhead` is the only clip long enough for `pay()` to bind: Jackpot bills 68
of its 70-point budget, so the surplus is zeroed and the five real hits keep full size.

## Outstanding

1. **All three clips are re-judged and committed** (`cf5f191` finished jackpot). One
   caveat: the jackpot run started a few minutes before the KO cross-check block was
   restructured and `--ko` was added, so it ran on marginally older code. It is not
   worth ~24 batches to redo — neither changed path is reachable for that input
   (`--ko` was not passed, and Jackpot took 100 damage to Copperhead's 28, so the
   damage cross-check does not fire under either ordering) — but if you want a
   byte-exact idempotency check, that is the one run to repeat.

2. **Nothing has been checked in the browser.** All verification so far is on the JSON.
   The acceptance criterion is 4–7 non-KO shakes across a fight, counted by eye:
   ```bash
   python3 backend/serve.py
   ```
   → `http://localhost:40911/frontend/index.html?clip=madcatter-tombstone` (run the
   server from a human terminal, not an agent task).

3. **`manta-skorpios` needed `--ko left` to get the winner right.** ~6 of its 16 frames
   are crowd shots and Manta is flat on the floor from t≈4s, so the model reads the
   sides backwards and does it *consistently* — the damage cross-check agreed with the
   wrong answer, so only the explicit flag fixes it. Verified against the footage:
   frame 0008 shows SKORPIOS labelled and mobile beside a dead Manta. If these clips get
   re-judged again, that flag must be passed. Consider recording the known card and KO
   side per clip in the CLAUDE.md fights table so this is not re-derived each time.

4. **A 22-second caption gap remains** on madcatter-tombstone (t=32 → t=54). The
   anti-repeat rule silences a burning bot almost completely. The "worsening counts as
   `glance`" line in the prompt was added to soften this and helped, but did not close
   it. Only worth touching if the HUD looks dead there.

5. **`ingest.py` was not updated** to pass `--ko` through, and its `analyze()` call
   still only forwards `bots`. Era B (any YouTube URL) has no way to set the KO side —
   fine, since nobody has watched those clips, but worth knowing.

6. **`frames` symlink**: the worktree has no `frames/`. Recreate with
   `ln -sfn /Users/carter/dev/gameover/frames frames`. `.gitignore` now covers it.

## Collision with `main` and `claude/hit-counter-visibility-ui-942ff0`

This branch forked from `419b423` and never picked up `96aa2f9`, `1688a1f`, `0ae024c`,
`1d6b1a9`. `backend/prompt.txt` here was rewritten from the **pre-`96aa2f9`** version, so
merging it as-is silently drops every rule `main` added:

- `left`/`right` as FIXED IDENTITIES tracked by appearance, with `left_look` /
  `right_look` carried across calls
- "judge BOTH bots in every frame — a fight where one bot never loses a single hp is
  almost always a mis-read"
- non-competitor exclusion (referee and crew, killsaws and hazards, tender bots)
- captions that name the bot, plus `name_captions()` in `analyze.py`, absent here

The `footer()` change on this branch ("identify them by how they look, not by where they
are in the frame") is an independent, weaker re-derivation of `main`'s identity rule,
added after the KO side flipped between two runs of madcatter-tombstone. `main`'s version
is better — it lives in the prompt and persists appearance notes. Keep `main`'s; the
`footer()` card pin is still worth having on top of it, since it also anchors the
`--bots` card the model would otherwise have to read off broadcast graphics.

The three timelines committed here were judged **without** any of those rules, so they
need re-judging against a merged prompt before they can be trusted — not because the
severity ladder is wrong, but because the identity and non-competitor rules were missing.

### The design decision to make first

`claude/hit-counter-visibility-ui-942ff0` derives damage tiers from hp deltas in the
frontend (`TIERS`). This branch moves severity into the model and has Python own the hp
numbers. **Both solve the same problem and only one should survive.** Nothing else should
be merged until that is settled, and the re-judge should happen exactly once afterwards.

Point in this branch's favour: `main`'s HANDOVER.md §1 lists "the winner's health bar
never moves" as the top outstanding problem (Copperhead pinned at 100 for 140s). The
severity ladder fixes it — Copperhead now moves 100 -> 72, MaDCaTTer 100 -> 60.

Point against: it costs `main`'s sprites, footage crops and weapon sigils until merged,
and its re-judge spent API calls that a merged prompt will have to spend again.
