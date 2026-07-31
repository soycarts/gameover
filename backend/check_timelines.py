#!/usr/bin/env python3
"""check_timelines.py — are all the timelines still current, and still valid?

    python backend/check_timelines.py            # every timeline
    python backend/check_timelines.py manta-skorpios

**Run this after every merge, before pushing.** It exists because of a specific
failure: `cf5f191` re-judged jackpot-copperhead onto the severity ladder, and
`f7f9ecb` ("Merge the severity ladder into main's identity-tracked judging") then
resolved the file in main's favour. The pre-ladder version was back at every
commit for three days and nobody noticed, because a reverted timeline still
loads, still validates and still plays — it just quietly describes a different
fight. A JSON timeline is not a file where "take theirs" is ever obviously right.

The load-bearing check is the LADDER one. The model never emits hp; it rates a
damage word, which SEVERITY turns into 0/4/12/22/35. So every hp delta that is
not a count-out has to land exactly on a rung. Deltas of 10, 15, 7, 6, 3 are the
signature of the old absolute-hp pipeline, where the model nudged the bar down a
few points per frame to signal "time passed" — a drip the HUD renders as mush and
no TIERS band can colour.

Synthetic timelines (synthfight, demo/) are hand-made fixtures that deliberately
exercise the no-`hit` fallback path, so they are validated but exempt from the
parity rules. Judged clips are the ones held to them.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyze

ROOT = Path(__file__).resolve().parent.parent
LADDER = set(analyze.SEVERITY.values()) - {0}
# Hand-made fixtures, never re-judged: they are the regression test for a
# timeline with no `hit` field at all, so they cannot meet the parity rules.
SYNTHETIC = {"synthfight"}


def norm(s: str) -> str:
    return " ".join(str(s or "").split()).lower()


def check(name: str) -> list[str]:
    tl = json.loads((ROOT / "timelines" / f"{name}.json").read_text())
    ev = tl["events"]
    bad: list[str] = []

    analyze.validate(tl)                       # shape contract; raises on failure

    hits = [e for e in ev if e.get("hit")]
    drains = [e for e in ev if e.get("drain")]
    at = [e for e in hits if e["hit"].get("at")]
    weapon = [e for e in hits if e["hit"].get("weapon")]
    ko = [e.get("ko") for e in ev if e.get("ko")]

    off = []
    for a, b in zip(ev, ev[1:]):
        for side in analyze.SIDES:
            d = a[f"{side}_hp"] - b[f"{side}_hp"]
            if d and not b.get("drain") and d not in LADDER:
                off.append(f"t={b['t']}:{side} -{d}")

    print(f"{name:22} {len(ev):3} events  {len(drains):3} drain  {len(hits):3} hit  "
          f"{len(at):3} at  {len(weapon):3} weapon  ko={ko or 'NONE'}")

    if name in SYNTHETIC:
        print(f"{'':22} synthetic fixture — validated, parity rules not applied")
        return bad

    if off:
        bad.append(f"{name}: {len(off)} hp delta(s) off the severity ladder "
                   f"({', '.join(off[:6])}{'…' if len(off) > 6 else ''}) — this is "
                   f"the pre-ladder pipeline, i.e. a stale or reverted timeline")
    if not hits:
        bad.append(f"{name}: no `hit` objects at all — judged before the hit "
                   f"contract, so no weapon labels and no crosshairs")
    if not drains:
        bad.append(f"{name}: no `drain` events — the count-out fell back to forcing "
                   f"hp to 0 on the last event, which invents a finishing blow")
    if hits and len(at) < len(hits):
        bad.append(f"{name}: {len(hits) - len(at)}/{len(hits)} hits carry no `at` — "
                   f"judged before the impact point existed")
    if not ko:
        bad.append(f"{name}: no event carries `ko` — loserSide() falls back to hp")

    # Every fan_comment must still resolve, or the HUD shows it with no author.
    cf = ROOT / "comments" / f"{name}.json"
    if cf.exists():
        pool = {norm(c["text"]) for c in json.loads(cf.read_text())}
        orphan = [e["fan_comment"] for e in ev
                  if e.get("fan_comment") and norm(e["fan_comment"]) not in pool]
        if orphan:
            bad.append(f"{name}: {len(orphan)} fan_comment(s) not in comments/"
                       f"{name}.json — run --rejoin after a re-scrape")
    return bad


if __name__ == "__main__":
    want = [a for a in sys.argv[1:] if not a.startswith("-")]
    names = want or sorted(p.stem for p in (ROOT / "timelines").glob("*.json"))
    problems: list[str] = []
    for n in names:
        try:
            problems += check(n)
        except Exception as e:
            problems.append(f"{n}: {type(e).__name__}: {e}")
    print()
    for p in problems:
        print(f"  ! {p}")
    print("PASS — every timeline is current" if not problems
          else f"FAIL — {len(problems)} problem(s)")
    sys.exit(1 if problems else 0)
