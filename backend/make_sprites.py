#!/usr/bin/env python3
"""make_sprites.py — pixel sprites derived from the official Pro League photos.

    python backend/roster.py --photos      # cache the cutouts first
    python backend/make_sprites.py         # -> frontend/sprites.js
    python backend/make_sprites.py jackpot # one bot, printed, writes nothing

The hand-drawn sprites this replaces were drawn from memory and several were
simply wrong — Jackpot was red and yellow (it is green and black with a red
vertical disc), MaDCaTTer was purple (it is a red-and-blue cat face). The
battlebots.com cutouts are 2100x1500 **8-bit RGBA**, so the silhouette comes free
from the alpha channel and the livery free from RGB. Nothing is guessed.

ffmpeg does the resampling because it is already a dependency; the quantising is
stdlib, so requirements.txt does not grow a Pillow/numpy install for 27 images.

TWO SIZES, and both are load-bearing. Measured against the CSS: `.vsart` renders
at clamp(72px, 13vw, 148px), where a 48-wide grid is ~3px per cell and reads as
pixel art. `.sigil` renders at clamp(14px, 2.1vw, 26px) — a 48-wide grid there is
half a pixel per cell and turns to mush, so the HUD name row gets its own 16x12
cut of the same image.

Hand-tuning belongs in index.html's ART table, which wins over anything here.
Editing sprites.js directly works until the next regeneration silently reverts it.
"""
import base64
import json
import subprocess
import sys
from pathlib import Path

import roster

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "sprites.js"

WORK_W = 420          # what ffmpeg hands us; big enough to area-average from
VS = (48, 36)         # the VS card
HUD = (16, 12)        # the name-row sigil
ALPHA_ON = 0.34       # a cell is solid when this much of it is opaque; low enough
                      # to keep Skorpios's thin arm linkage from breaking into speckle
COLOURS = 7           # palette entries per bot, before transparency
MIN_SEP = 62          # ... and how far apart they must be, in RGB distance
# The HUD's --bg is #07080b, which is very nearly black — so a machine that is
# actually black (Tombstone, Skorpios, Cobalt) renders as a hole in the screen.
# Every palette entry is lifted to at least this luma. It is the same reason
# arcade sprites have never drawn black as #000: on a black screen it is not a
# colour, it is absence. Raise --bg and this can come down.
LUMA_FLOOR = 54
CHARS = "abcdefghijklmnop"


def raw_rgba(png: Path, width: int) -> tuple[list, int, int]:
    """ffmpeg -> flat RGBA byte list at `width`, aspect preserved."""
    cmd = ["ffmpeg", "-v", "error", "-i", str(png),
           "-vf", f"scale={width}:-1", "-pix_fmt", "rgba", "-f", "rawvideo", "-"]
    buf = subprocess.run(cmd, check=True, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE).stdout
    h = len(buf) // (width * 4)
    return buf, width, h


def alpha_box(buf, w: int, h: int) -> tuple[int, int, int, int]:
    """Bounding box of the visible robot, so it fills the sprite instead of
    floating in whatever margin the photographer left."""
    x0, y0, x1, y1 = w, h, -1, -1
    for y in range(h):
        row = y * w * 4
        for x in range(w):
            if buf[row + x * 4 + 3] > 40:
                if x < x0: x0 = x
                if x > x1: x1 = x
                if y < y0: y0 = y
                if y > y1: y1 = y
    return (0, 0, w - 1, h - 1) if x1 < 0 else (x0, y0, x1, y1)


def sample(buf, w: int, box, gw: int, gh: int) -> list:
    """Area-average the cropped image into a gw x gh grid.

    Aspect is preserved and the result centred, so a long low wedge stays long and
    low rather than being stretched to fill the cell grid. RGB is weighted by
    alpha — averaging a transparent pixel in unweighted drags every edge toward
    black and gives every robot a dark halo.
    """
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    scale = min(gw / bw, gh / bh)
    dw, dh = max(1, round(bw * scale)), max(1, round(bh * scale))
    ox, oy = (gw - dw) // 2, (gh - dh) // 2

    cells = [None] * (gw * gh)
    for cy in range(dh):
        sy0, sy1 = y0 + int(cy * bh / dh), y0 + max(int((cy + 1) * bh / dh),
                                                    int(cy * bh / dh) + 1)
        for cx in range(dw):
            sx0, sx1 = x0 + int(cx * bw / dw), x0 + max(int((cx + 1) * bw / dw),
                                                        int(cx * bw / dw) + 1)
            r = g = b = a = n = 0
            for sy in range(sy0, min(sy1, y1 + 1)):
                base = sy * w * 4
                for sx in range(sx0, min(sx1, x1 + 1)):
                    i = base + sx * 4
                    av = buf[i + 3]
                    r += buf[i] * av; g += buf[i + 1] * av; b += buf[i + 2] * av
                    a += av; n += 1
            if not n:
                continue
            cells[(cy + oy) * gw + (cx + ox)] = (
                (r // a, g // a, b // a, a / (n * 255)) if a else (0, 0, 0, 0.0))
    return cells


def palette(cells, k: int) -> list:
    """The bot's own dominant colours, not a fixed global ramp.

    Colours are counted in coarse bins so Copperhead's brass and MaDCaTTer's cyan
    eyes survive instead of being flattened into a shared grey. A global palette
    was the obvious first idea and it turns every machine into the same machine.

    Taking the k busiest bins was the second idea and it is nearly as bad: on
    Jackpot it returned five near-identical dark reds and exactly one green, for a
    robot whose whole chassis is green — a big region of one hue splits across
    several adjacent bins and crowds every other colour off the list.

    So entries are accepted busiest-first but only when they are at least MIN_SEP
    away from everything already chosen. That spends the palette on the hues the
    machine actually has rather than on shades of its largest one. If the
    separation cannot be met the remaining slots are simply not used — a machine
    that really is one colour gets a short palette, which is correct.
    """
    bins = {}
    for c in cells:
        if not c or c[3] < ALPHA_ON:
            continue
        key = (c[0] // 26, c[1] // 26, c[2] // 26)
        acc = bins.setdefault(key, [0, 0, 0, 0])
        acc[0] += c[0]; acc[1] += c[1]; acc[2] += c[2]; acc[3] += 1
    ranked = [(a[0] // a[3], a[1] // a[3], a[2] // a[3])
              for a in sorted(bins.values(), key=lambda a: -a[3])]
    out: list = []
    for c in ranked:
        if len(out) >= k:
            break
        if all(sum((c[i] - p[i]) ** 2 for i in range(3)) >= MIN_SEP ** 2 for p in out):
            out.append(c)
    return [lift(c) for c in out]


def lift(c: tuple) -> tuple:
    """Raise a colour to LUMA_FLOOR, keeping its hue.

    Added rather than scaled, because scaling cannot lift pure black at all —
    Tombstone's body is very close to it — and a machine that vanishes into the
    background is worse than one rendered a shade lighter than the photo.
    """
    luma = 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    if luma >= LUMA_FLOOR:
        return c
    add = int(LUMA_FLOOR - luma)
    return tuple(min(255, v + add) for v in c)


def render(cells, gw: int, gh: int, pal: list) -> list[str]:
    rows = []
    for y in range(gh):
        row = ""
        for x in range(gw):
            c = cells[y * gw + x]
            if not c or c[3] < ALPHA_ON:
                row += "."
                continue
            best = min(range(len(pal)), key=lambda i: (
                (pal[i][0] - c[0]) ** 2 + (pal[i][1] - c[1]) ** 2
                + (pal[i][2] - c[2]) ** 2))
            row += CHARS[best]
        rows.append(row)
    return rows


def used(rows: list[str], pal: list) -> dict:
    """Only the chars that actually appear — an unused palette entry is bytes
    shipped to every visitor for a colour nothing is drawn in."""
    seen = {ch for r in rows for ch in r if ch != "."}
    return {ch: "#%02x%02x%02x" % pal[CHARS.index(ch)] for ch in CHARS if ch in seen}


def sprite(png: Path) -> dict:
    buf, w, h = raw_rgba(png, WORK_W)
    box = alpha_box(buf, w, h)
    big = sample(buf, w, box, *VS)
    pal = palette(big, COLOURS)
    if not pal:
        return {}
    vs = render(big, *VS, pal)
    hud = render(sample(buf, w, box, *HUD), *HUD, pal)
    # One palette for both cuts, so the two sizes cannot disagree about the
    # bot's colours, and the smaller one costs no extra entries.
    return {"pal": used(vs, pal) | used(hud, pal), "vs": vs, "hud": hud}


def build(only: str | None = None) -> dict:
    bots = roster.load()
    if not bots:
        sys.exit("no backend/roster.json — run: python backend/roster.py")
    out = {}
    for key, b in sorted(bots.items()):
        if only and key != only:
            continue
        png = roster.PHOTOS / f"{key}.png"
        if not png.exists():
            print(f"  ! no photo for {b['name']} — run roster.py --photos")
            continue
        s = sprite(png)
        if not s:
            print(f"  ! {b['name']}: nothing opaque in the cutout")
            continue
        out[key] = s
        print(f"  {b['name']:<14} {len(s['pal'])} colours  "
              f"{sum(c != '.' for r in s['vs'] for c in r):4d}/{VS[0] * VS[1]} cells")
    return out


def write(sprites: dict) -> None:
    lines = ["/* GENERATED by backend/make_sprites.py from the official Pro League",
             "   photos — do not hand-edit, it is overwritten. To tune a sprite, add",
             "   it to the ART table in index.html, which wins over anything here.",
             f"   {VS[0]}x{VS[1]} for the VS card, {HUD[0]}x{HUD[1]} for the HUD name row. */",
             "window.SPRITES = {"]
    for key, s in sprites.items():
        pal = ", ".join(f"{c}:'{v}'" for c, v in s["pal"].items())
        lines.append(f"  {key}: {{ pal: {{ {pal} }},")
        lines.append("    vs: [" + ",".join(f"'{r}'" for r in s["vs"]) + "],")
        lines.append("    hud: [" + ",".join(f"'{r}'" for r in s["hud"]) + "] },")
    lines.append("};")
    OUT.write_text("\n".join(lines) + "\n")
    print(f"wrote {len(sprites)} sprites -> {OUT} ({OUT.stat().st_size // 1024}kB)")


CHECK = ROOT / "frontend" / "_spritecheck.html"


def check_page(sprites: dict) -> None:
    """Every sprite beside its source photo, on the real --bg, at both real sizes.

    Auto-derived pixel art can be numerically fine and still look like a smudge,
    and the two failures found this way were both invisible in the numbers: a
    palette of five near-identical reds, and every dark machine vanishing into a
    #07080b background. Gitignored — it embeds the photos as data URIs and is a
    few MB.
    """
    bots = roster.load()
    rows = []
    for key, s in sprites.items():
        thumb = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(roster.PHOTOS / f"{key}.png"),
             "-vf", "scale=160:-1", "-f", "image2pipe", "-vcodec", "png", "-"],
            check=True, stdout=subprocess.PIPE).stdout
        img = base64.b64encode(thumb).decode()
        cells = "".join(
            f"<td>{svg_of(s['pal'], s[k], px)}</td>"
            for k, px in (("vs", 148), ("vs", 72), ("hud", 26), ("hud", 60)))
        rows.append(f"<tr><td><b>{bots[key]['name']}</b><br><small>"
                    f"{bots[key]['weapon'] or '?'}</small></td>"
                    f"<td><img src='data:image/png;base64,{img}' "
                    f"style='height:74px;background:#2a2e35'></td>{cells}</tr>")
    CHECK.write_text(
        "<style>body{background:#07080b;color:#ddd;font:13px system-ui;margin:0}"
        "table{border-collapse:collapse;width:100%}td{padding:5px;"
        "border-bottom:1px solid #1c1f26;vertical-align:middle}"
        "th{font:11px system-ui;color:#6f7987;text-align:left;padding:5px}</style>"
        "<table><tr><th>bot</th><th>official photo</th><th>48x36 @148px (VS)</th>"
        "<th>@72px</th><th>16x12 @26px (HUD)</th><th>@60px</th></tr>"
        + "".join(rows) + "</table>")
    print(f"wrote {CHECK} — open it at "
          f"http://localhost:40911/frontend/_spritecheck.html")


def svg_of(pal: dict, rows: list[str], px: int) -> str:
    w, h = len(rows[0]), len(rows)
    r = "".join(f'<rect x="{x}" y="{y}" width="1" height="1" fill="{pal[c]}"/>'
                for y, row in enumerate(rows) for x, c in enumerate(row) if c != ".")
    return (f'<svg viewBox="0 0 {w} {h}" width="{px}" height="{px * h // w}" '
            f'style="image-rendering:pixelated">{r}</svg>')


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args:
        s = sprite(roster.PHOTOS / f"{roster.bot_key(args[0])}.png")
        print("\n".join(s["vs"]))
        print(json.dumps(s["pal"], indent=1))
    else:
        got = build()
        write(got)
        if "--check" in sys.argv:
            check_page(got)
