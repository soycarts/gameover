#!/usr/bin/env python3
"""check_looks.py — is this --looks string safe to spend a re-judge on?

    python backend/check_looks.py --bots "Copperhead,Jackpot" \
        --looks "black low wedge, copper front drum spinner|green chassis, red disc spinner"

Writes nothing, calls no model, runs in about a second. It exists because a bad
--looks is worse than none: the string goes verbatim into identity_note() and is
stated to the model as human-verified fact, and every guard downstream
(drop_downed_hits, immobile_from, the --ko cross-check) then agrees with it.

It checks the two things that actually go wrong, both of which it has already
caught on real strings:

  1. **A token that looks discriminating but isn't.** "wedge" appeared only in
     Copperhead's description while Jackpot has wedgelets too, so a bare "a wedge"
     resolved confidently to the wrong machine instead of returning None. Any word
     true of BOTH machines has to appear in BOTH strings to be discounted.
  2. **weapon_owners() splitting a weapon it should not.** Both these bots are
     spinners, but only one string said "spinner", so transcribe's garble guard
     believed every "spinner" in the commentary belonged to Copperhead.

A description it cannot place returns None, and that is a PASS: immobile_from()
reads None as no evidence, which is the safe answer. The failure being hunted is a
confident wrong answer.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyze
import roster
import transcribe

# CONTENTLESS — no distinctive token at all, so resolving one to a side is always
# a bug. This is the frame where the model saw something stop but could not say
# what, which is exactly the frame that must not start a referee count.
CONTENTLESS = ("the robot", "a robot", "a bot", "a machine", "it has stopped",
               "the bot is not moving", "something stopped")

# SHAPE words are a judgement call the tool cannot make. "a wedge" resolving to
# Copperhead is CORRECT when the other machine is a forked vertical spinner, and a
# BUG when both are wedges (manta-skorpios, where both looks say "wedge" and the
# word is correctly discounted). So these are reported for a human to confirm, not
# failed — an earlier version failed them and was simply wrong about two fights.
SHAPE = ("a wedge", "a spinner", "a drum", "a disc", "a bar", "a flipper")


def machines(bots: dict) -> None:
    """What each side actually puts in the arena, and what a count-out needs.

    Printed here because this is the screen someone looks at before paying for a
    re-judge, and `need` silently changing from 1 to 2 would otherwise only show
    up as a count-out that never starts.
    """
    table = roster.load()
    if not table:
        print("machines: no backend/roster.json — run `python backend/roster.py`")
        return
    for side in analyze.SIDES:
        entry = table.get(roster.bot_key(bots[side]))
        if not entry:
            print(f"machines {side:<5}: {bots[side]} is not in the Pro League roster "
                  f"— assumed a single machine")
            continue
        ms = entry["machines"]
        total = sum(m["weight"] for m in ms)
        need = roster.min_down(ms)
        listed = ", ".join(f"{m['name']} {m['weight']}lb"
                           f"{'' if m['competitor'] else ' (minibot)'}" for m in ms)
        heaviest = max(m["weight"] for m in ms) / total
        print(f"machines {side:<5}: {listed}  -> count needs {need} of {len(ms)} down "
              f"(heaviest alone is {heaviest:.0%}, rule 7.5.4 wants 60%)")


def report(bots: dict, looks: dict) -> bool:
    others = analyze.others_for(bots)
    owners = transcribe.weapon_owners(looks)
    print(f"left  ({bots['left']}): {looks['left']}")
    print(f"right ({bots['right']}): {looks['right']}")
    machines(bots)
    print(f"minibots in this fight: {', '.join(others) or 'none in the roster'}")
    print(f"weapon owners: {owners or 'none — the garble guard will be inert'}")

    ok = True
    print("\ncontentless descriptions (every one MUST be None):")
    for d in CONTENTLESS:
        got = analyze.match_look(d, looks, bots, others)
        bad = got is not None
        ok &= not bad
        print(f"  {'FAIL' if bad else 'ok  '} {d!r:32} -> {got!r}")

    print("\nshape words — confirm each of these by eye:")
    for d in SHAPE:
        got = analyze.match_look(d, looks, bots, others)
        if got is None:
            print(f"  ok   {d!r:32} -> None (shared, or in neither)")
        else:
            name = bots[got] if got in analyze.SIDES else got
            print(f"  CHECK {d!r:31} -> {name}. Right only if the OTHER machine is "
                  f"genuinely not that; if it is, put the word in both strings.")

    print("\neach machine described by its own words (must find itself):")
    for side in analyze.SIDES:
        got = analyze.match_look(looks[side], looks, bots, others)
        bad = got != side
        ok &= not bad
        print(f"  {'FAIL' if bad else 'ok  '} {side:<5} own description        -> {got!r}")

    for name, look in others.items():
        got = analyze.match_look(look, looks, bots, others)
        bad = got != analyze.NOT_COMPETITOR
        ok &= not bad
        print(f"  {'FAIL' if bad else 'ok  '} {name:<5} (minibot)              -> {got!r}")

    shared = analyze.words(looks["left"]) & analyze.words(looks["right"])
    print(f"\nshared, discounted tokens: {', '.join(sorted(shared)) or 'NONE'}")
    if not shared:
        print("  ! no shared words at all — if the two machines really do have "
              "something in common (both wedges, both spinners), say so in BOTH "
              "strings so the token is discounted rather than voting")
    return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bots", required=True, metavar='"Left,Right"')
    ap.add_argument("--looks", required=True, metavar='"left desc|right desc"')
    a = ap.parse_args()
    names = [s.strip() for s in a.bots.split(",")]
    desc = [s.strip() for s in a.looks.split("|")]
    if len(names) != 2 or len(desc) != 2:
        sys.exit('--bots needs "Left,Right" and --looks needs "left|right"')
    good = report(dict(zip(analyze.SIDES, names)), dict(zip(analyze.SIDES, desc)))
    print("\n" + ("PASS — safe to spend a re-judge on"
                  if good else "FAIL — fix the strings before paying for a run"))
    sys.exit(0 if good else 1)
