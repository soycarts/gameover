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

The load-bearing check is the ERA one, and there are now two legitimate eras.

**Normalised** (hits carry `sev`): normalise() shares one target across every
blow in proportion to its rung, so a delta is a share of the bar and no longer a
rung. What has to hold instead is that every blow moves the bar at all, that the
rung is carried explicitly as `hit.sev`, and that the loser's blows sum to
KO_BLOW_TOTAL with the count bleeding the rest.

**Ladder** (no `sev` anywhere): the older fixed-budget pipeline, where every
non-count delta lands exactly on a SEVERITY rung of 4/12/22/35. madcatter and
manta are deliberately still here.

A judged clip in NEITHER state is stale. That is a sharper test than the ladder
check it replaces: deltas of 10, 15, 7, 6, 3 with no `sev` to explain them are
the signature of the original absolute-hp pipeline, where the model nudged the
bar down a few points a frame to signal "time passed" — a drip the HUD renders as
mush because there was no rung behind it to colour, size or shake from.

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

    sev = [e for e in hits if e["hit"].get("sev")]
    normalised = bool(sev)

    off, blows = [], {s: 0 for s in analyze.SIDES}
    for a, b in zip(ev, ev[1:]):
        for side in analyze.SIDES:
            d = a[f"{side}_hp"] - b[f"{side}_hp"]
            if not d or b.get("drain"):
                continue
            blows[side] += d
            if not normalised and d not in LADDER:
                off.append(f"t={b['t']}:{side} -{d}")

    print(f"{name:22} {len(ev):3} events  {len(drains):3} drain  {len(hits):3} hit  "
          f"{len(at):3} at  {len(weapon):3} weapon  ko={ko or 'NONE'}  "
          f"{'normalised' if normalised else 'ladder'}")

    if name in SYNTHETIC:
        print(f"{'':22} synthetic fixture — validated, parity rules not applied")
        return bad

    if normalised:
        # Reported, not asserted. The bug this era exists to fix looks like a wall
        # of captions over a frozen bar — jackpot-copperhead was 35 captions to 7
        # scoring moments, one every 20s against manta's every 9s. There is no
        # honest threshold to fail on (a fire spreading is a caption and not a
        # blow), so print the density and let a human read it.
        told = [e for e in ev if e.get("caption")]
        span = ev[-1]["t"] - ev[0]["t"] or 1
        print(f"{'':22} {len(hits)} blow(s) across {span:.0f}s — one every "
              f"{span / max(1, len(hits)):.1f}s, over {len(told)} captioned moment(s)")
        if len(sev) < len(hits):
            bad.append(f"{name}: {len(hits) - len(sev)} of {len(hits)} hits carry no "
                       f"`sev` — the HUD bands those off the hp delta, which under "
                       f"normalisation is a share of the bar and not a rung")
        # The loser's blows must sum to KO_BLOW_TOTAL; the count bleeds the rest.
        for side in ko:
            got = blows[side]
            if got != analyze.KO_BLOW_TOTAL:
                bad.append(f"{name}: the eliminated bot ({side}) lost {got}hp to blows, "
                           f"not {analyze.KO_BLOW_TOTAL} — normalise() and the count-out "
                           f"disagree about who owns the last "
                           f"{100 - analyze.KO_BLOW_TOTAL}hp")
    elif off:
        bad.append(f"{name}: {len(off)} hp delta(s) off the severity ladder and no "
                   f"`sev` to explain them ({', '.join(off[:6])}"
                   f"{'…' if len(off) > 6 else ''}) — this is the original absolute-hp "
                   f"pipeline, i.e. a stale or reverted timeline")
    if not hits:
        bad.append(f"{name}: no `hit` objects at all — judged before the hit "
                   f"contract, so no weapon labels and no crosshairs")
    if not drains:
        bad.append(f"{name}: no `drain` events — the count-out fell back to forcing "
                   f"hp to 0 on the last event, which invents a finishing blow")
    # NOT "every hit must have one". normalize_hit() REJECTS an out-of-range
    # coordinate rather than clamping it — a model answering in pixels would clamp
    # to the bottom-right corner, a confident wrong answer straight onto the HUD's
    # own bar — and the fixed 36%/64% fallback is merely approximate. So the odd
    # miss is the guard working: jackpot-copperhead's is t=21.5 "Copperhead
    # launched into air", where the contact point is genuinely off-frame. Only a
    # timeline where NO hit has one was judged before the field existed.
    if hits and not at:
        bad.append(f"{name}: not one of {len(hits)} hits carries `at` — judged "
                   f"before the impact point existed, so every crosshair falls back")
    elif len(at) < len(hits):
        print(f"{'':22} {len(hits) - len(at)}/{len(hits)} hit(s) with no `at` — "
              f"rejected as out of range, falling back to the fixed position")
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
