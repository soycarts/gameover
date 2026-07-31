#!/usr/bin/env python3
"""roster.py — the Pro League field, scraped once and committed.

    python backend/roster.py            # writes backend/roster.json
    python backend/roster.py --force    # refetch even if the file exists
    python backend/roster.py --photos   # also cache the studio cutouts

battlebots.com/proleague/ carries the whole field in one embedded JS array,
`sourceBots`, in the server HTML — so this needs `requests` and no browser, even
though the cards themselves are built by script at runtime.

Two things this exists to stop anyone re-deriving:

**The photo URL must be scraped, never built from the name.** There is no
convention to follow. `Disarray` is `disarray-proleage.png` (misspelt), `Nemesis`
is `nemisis-right.png` (misspelt, and its slug spells it correctly, so the two
disagree), `End Game` is `end-game-right.png` while `Death Roll` is
`deathroll-right.png`, and Manta, Orbitron and The Twins are `-left` where the
other 24 are `-right`. A name-to-URL rule 404s on five of the 27.

**Which machines a side actually puts in the arena is not on the site.** It is in
MACHINES below, hand-verified, because it changes how a fight is judged: a minibot
is not a competitor, and BattleBots rule 7.5.4 counts out a multibot only when 60%
or more of its COMBINED WEIGHT is immobilised. See weight_down() and analyze.py.
"""
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "roster.json"
PROLEAGUE = "https://battlebots.com/proleague/"
ROBOT = "https://battlebots.com/robot/{slug}/"
# Dotted so serve.py 404s it, and .vercelignored: 27 cutouts is ~60MB of
# build-time reference that has no business on the public site.
PHOTOS = ROOT / "bots" / ".proleague"
UA = {"User-Agent": "Mozilla/5.0 (gameover roster scrape)"}

# Heavyweight limit. Every Pro League competitor is at the cap; minibots are
# capped at 20lb by the design rules and are listed at that cap, because the
# only thing the weight is used for is the 60% comparison and being generous to
# the minibot is the conservative direction (it makes a count-out HARDER).
HEAVYWEIGHT = 250
MINIBOT = 20

# Hand-verified, and not available anywhere on battlebots.com. `competitor:
# False` means "legitimately in the arena, but not a bot that can win or lose the
# fight" — a minibot deals no scored damage and its immobility never starts a
# count. Two equal machines both marked True is a true multibot (The Twins),
# where 7.5.4 means BOTH have to stop.
MACHINES = {
    "jackpot":   [("Jackpot", HEAVYWEIGHT, True), ("Ace", MINIBOT, False)],
    "madcatter": [("MaDCaTTer", HEAVYWEIGHT, True), ("Gassy Cat", MINIBOT, False)],
    "thetwins":  [("Twin A", HEAVYWEIGHT // 2, True),
                  ("Twin B", HEAVYWEIGHT // 2, True)],
}

# What each minibot looks like, so identity_note() can name it and match_look()
# can recognise a description of it instead of forcing it onto a competitor.
MINIBOT_LOOKS = {
    "ace": "small white minibot with red wheels and low forks",
    "gassycat": "small minibot with a flame jet",
}


def bot_key(name: str) -> str:
    """Byte-identical to crowd.bot_key() and the frontend's botKey(). Keep it so."""
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def parse_source_bots(html: str) -> list[dict]:
    """Pull the `sourceBots` array out of the page's inline script.

    Matched per-object rather than by slicing the array literal: the array is
    inside a template that also contains `}` in JS expressions, so anything that
    tries to find the closing bracket gets it wrong.
    """
    pat = re.compile(
        r'\{\s*name:\s*"([^"]+)",\s*slug:\s*"([^"]+)",\s*url:\s*"([^"]+)"(.*?)\}',
        re.S)
    out = []
    for name, slug, url, rest in pat.findall(html):
        grab = lambda k: (re.search(rf'{k}:\s*"([^"]*)"', rest) or [None, ""])[1]
        out.append({"name": name, "slug": slug, "photo": url,
                    "country": grab("country"), "team": grab("teamName"),
                    "team_photo": grab("teamPhoto")})
    return out


LABELS = ("Robot", "Builder", "Type", "Job", "Team", "Years competing",
          "Hometown", "Favorite")


def parse_type(page: str) -> str:
    """The robot page's `Type:` line — "Disc spinner (vertical)" and friends.

    Sliced between known labels rather than matched with a lazy `(.+?)`: several
    pages leave Type EMPTY (Manta, Disarray, The Twins all do), and a lazy match
    happily runs on and returns the next field, which is how this first reported
    Disarray's weapon as "Job: Software Engineer".

    Entities are unescaped first — the block is full of &nbsp;, which is not
    whitespace to a regex and leaks into the value.
    """
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text)).replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    m = re.search(r"\bType:\s*(.*?)\s*\b(?:" + "|".join(LABELS) + r"):", text)
    return m.group(1).strip() if m else ""


def machines_for(key: str, name: str) -> list[dict]:
    """Every machine this side brings. One entry for an ordinary bot, so callers
    never branch on "is this a multibot" — they just sum the list."""
    rows = MACHINES.get(key) or [(name, HEAVYWEIGHT, True)]
    return [{"name": n, "weight": w, "competitor": c} for n, w, c in rows]


# BattleBots Tournament Rules 7.5.4: a multibot is counted out when 60% or more of
# its COMBINED weight is immobilised. Unaltered since 2016.
KO_FRACTION = 0.60


def min_down(machines: list[dict]) -> int:
    """How many of a side's machines must stop before a count can start.

    Heaviest-first, because that is the order a count actually happens in: the
    heavyweight is what gets attacked. Jackpot 250 + Ace 20 -> 250/270 = 93%, so
    ONE machine is enough and Ace's state is irrelevant to the count — which is
    the case that matters for our clips, and the reason this returns 1 for every
    ordinary bot and every bot with a minibot alike.

    The Twins, two equal machines -> one is 50%, under the threshold, so it
    returns 2 and BOTH have to stop. That is the whole behavioural difference
    between a minibot and a true multibot, and it falls out of the arithmetic
    rather than out of a flag someone has to remember to set.
    """
    total = sum(m["weight"] for m in machines) or 1
    down = 0.0
    for i, m in enumerate(sorted(machines, key=lambda m: -m["weight"]), 1):
        down += m["weight"]
        if down / total >= KO_FRACTION:
            return i
    return len(machines)


def minibots(entry: dict | None) -> list[dict]:
    """The machines on this side that cannot win or lose the fight."""
    return [m for m in (entry or {}).get("machines", []) if not m["competitor"]]


def minibot_look(name: str) -> str:
    return MINIBOT_LOOKS.get(bot_key(name), "")


def build(force: bool = False) -> list[dict]:
    if OUT.exists() and not force:
        print(f"{len(json.loads(OUT.read_text())['bots'])} bots already in {OUT} "
              f"(use --force to refetch)")
        return json.loads(OUT.read_text())["bots"]

    print(f"fetching {PROLEAGUE}")
    bots = parse_source_bots(fetch(PROLEAGUE))
    if not bots:
        sys.exit("! no bots parsed — the page's sourceBots array moved or changed shape")

    for i, b in enumerate(bots, 1):
        b["seed"] = i if i <= 24 else 0        # 25-27 are the alternates
        b["key"] = bot_key(b["name"])
        b["machines"] = machines_for(b["key"], b["name"])
        try:
            b["weapon"] = parse_type(fetch(ROBOT.format(slug=b["slug"])))
        except Exception as e:                  # a missing page is not fatal
            print(f"  ! {b['name']}: robot page failed ({e})")
            b["weapon"] = ""
        multi = "" if len(b["machines"]) == 1 else \
            "  +" + ", ".join(m["name"] for m in b["machines"][1:])
        print(f"  {b['seed'] or '--':>2} {b['name']:<14} {b['weapon'] or '?'}{multi}")

    OUT.write_text(json.dumps(
        {"source": PROLEAGUE, "bots": bots}, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {len(bots)} bots -> {OUT}")
    return bots


def cache_photos(bots: list[dict]) -> None:
    """Pull the studio cutouts down for make_sprites.py. ~60MB, gitignored."""
    PHOTOS.mkdir(parents=True, exist_ok=True)
    for b in bots:
        dst = PHOTOS / f"{b['key']}.png"
        if dst.exists():
            continue
        req = urllib.request.Request(b["photo"], headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            dst.write_bytes(r.read())
        print(f"  cached {dst.name} ({dst.stat().st_size // 1024}kB)")
    print(f"{len(list(PHOTOS.glob('*.png')))} photos in {PHOTOS}")


def load() -> dict:
    """Roster keyed by bot_key, for analyze.py. {} when it hasn't been scraped."""
    try:
        return {b["key"]: b for b in json.loads(OUT.read_text())["bots"]}
    except (OSError, ValueError, KeyError):
        return {}


if __name__ == "__main__":
    got = build(force="--force" in sys.argv)
    if "--photos" in sys.argv:
        cache_photos(got)
