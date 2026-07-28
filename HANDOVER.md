# Handover — 28 Jul 2026

State of play, what is trustworthy, and what to pick up next. Read
[CLAUDE.md](CLAUDE.md) first for architecture and commands; this file is only
the open loops.

## Works and verified

- HUD renders end to end on all three fights (title → VS card → fight → KO).
- Hand-drawn pixel sprites for all six bots, large on the VS card, small beside
  each name in-fight. Cascade is sprite → footage crop → weapon sigil.
- Captions name the bot ("Tombstone rear on fire") rather than a screen side.
- Real Reddit threaded comments, filtered for explicit content and for comments
  naming bots that are not in the fight.
- `serve.py` now implements HTTP Range, so the clip can be scrubbed locally.

## Outstanding — highest value first

### 1. Re-judge two clips: the winner's health bar never moves

**This is the most visible problem.** `jackpot-copperhead` has Copperhead pinned
at 100 for the whole 140s, and `madcatter-tombstone` has MaDCaTTer at 100 for
79s. Half the HUD is therefore dead on screen for most of the demo, and a
BattleBots fight where the winner takes zero damage is not credible.

Cause: the identity-tracking instruction added to `prompt.txt` told the model to
"report no change" when unsure which bot it was looking at, and it generalised
that into ignoring damage it could plainly see.

**`prompt.txt` is already fixed** (it now says to judge both bots every frame and
that a bot never losing a single hp is almost always a mis-read) — but the fix
is UNVERIFIED. A re-judge was started and killed by a tool timeout at batch
12/24. Nothing has been judged with the corrected prompt yet.

```bash
nohup .venv/bin/python -u backend/analyze.py jackpot-copperhead.mp4 \
    --backend openai --bots "Copperhead,Jackpot" > /tmp/jc.log 2>&1 &
nohup .venv/bin/python -u backend/analyze.py madcatter-tombstone.mp4 \
    --backend openai --bots "MaDCaTTer,Tombstone" > /tmp/mt.log 2>&1 &
```

Roughly 30 min and 15 min respectively. Then re-join comments (below). If the
winner still ends on 100, the prompt needs stronger wording rather than another
identical run.

### 2. Re-join comments after any re-judge

Re-judging rewrites the timeline and drops `fan_comment`. This is free and takes
seconds — it never re-runs the vision model:

```python
import sys, json; sys.path.insert(0, 'backend')
from pathlib import Path
import analyze
for tl in sorted(Path('timelines').glob('*.json')):
    cf = Path('comments', tl.stem + '.json')
    if not cf.exists(): continue
    d = json.loads(tl.read_text())
    analyze.name_captions(d['events'], d['bots'])
    for e in d['events']: e.pop('fan_comment', None)
    analyze.join_comments(d['events'], json.loads(cf.read_text()), d['bots'])
    tl.write_text(json.dumps(d, indent=2) + '\n')
```

### 3. `manta-skorpios` is too sparse to demo

4 events across 31s, so the HUD barely moves. It was judged before both the
sponsor-name and balanced-damage prompt fixes. Re-judge it with
`--bots "Manta,Skorpios"`; if it stays thin, drop it from the demo rotation and
lead with `madcatter-tombstone`.

### 4. Jackpot's sprite is a placeholder

I could not confirm what weapon Jackpot runs, so it is a neutral red body rather
than a wrong mechanism. Fix the rows in the `ART` table in
`frontend/index.html` — it is a 16x12 character grid, no rebuild needed. Same
table is where a new bot gets added.

### 5. Fan comments are thin on two clips

`jackpot-copperhead` has 1, `manta-skorpios` has 2. Discovery searches the whole
subreddit, so genuine moment-by-moment reactions are rare and much of what comes
back is season chatter. Options: scrape with a tighter query, raise
`POSTS_FOR_COMMENTS` in `scrape_comments.py` to expand more threads, or accept
it. Do NOT loosen `is_showable()` / `names_a_rival()` to get more volume — see
the content warning in CLAUDE.md.

## Traps that cost time today

- **macOS has no `setsid`.** Launch long jobs with `nohup … &` and poll the log;
  a long foreground wait gets killed by the tool timeout and takes the job with
  it, leaving a half-written timeline.
- **Headless DOM reads go stale.** Transitions and rAF do not advance without a
  paint, so `getComputedStyle` lies between JS calls. Take a screenshot first —
  this cost an hour chasing a health-core "bug" that did not exist.
- **A real `analyze.py` run overwrites the committed fixture** for whichever clip
  you name. `timelines/synthfight.json` is a hand-made demo fixture, not model
  output; re-judging `synthfight` will wreck the deployed demo page.
- **Bright Data's "Synchronous (Real-time)" mode is not synchronous** — it still
  returns 202 and a snapshot id to poll. Jobs took 1–6 minutes.
