#!/usr/bin/env python3
"""ingest.py <youtube_url> — ERA B: any fight video -> playable HUD, one command.

    python backend/ingest.py "https://www.youtube.com/watch?v=..."

Downloads at 720p max, cuts a window out of it, extracts frames, scrapes fan
comments, runs the vision judge, then prints the URL to open.

The download is cached under clips/.raw/, so a compilation holding several
fights costs one download and one run per fight:

    python backend/ingest.py "<url>" --name manta-skorpios \\
        --start 187 --duration 31 --bots "Manta,Skorpios"
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyze  # noqa: E402
import config  # noqa: E402
import extract_frames  # noqa: E402
import transcribe  # noqa: E402
import scrape_comments  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MAX_SECONDS = 120
PORT = 40911


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:40] or "clip").strip("-")


def tool(name: str) -> str:
    """Resolve a CLI tool, preferring this interpreter's own bin directory.

    yt-dlp is a requirements.txt dependency, so it lives in .venv/bin and is
    not on PATH unless the venv is activated. Checking PATH alone made
    `.venv/bin/python backend/ingest.py` exit with "not found" while the tool
    sat right next to the python running it.
    """
    local = Path(sys.executable).parent / name
    if local.exists():
        return str(local)
    found = shutil.which(name)
    if not found:
        sys.exit(f"{name} not found on PATH or in {local.parent}")
    return found


def probe_title(url: str) -> str:
    out = subprocess.run([tool("yt-dlp"), "--no-warnings", "--dump-single-json", url],
                         capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"yt-dlp failed:\n{out.stderr.strip()[:400]}")
    return json.loads(out.stdout).get("title", "fight")


def raw_path(source: str) -> Path:
    """The cached full download. Dotted dir: serve.py 404s dotfiles, so it is
    never served, and .gitignore's clips/* already covers it."""
    return ROOT / "clips" / ".raw" / f"{source}.mp4"


def media_seconds(p: Path) -> float | None:
    if not p.exists():
        return None
    out = subprocess.run([tool("ffprobe"), "-v", "error", "-show_entries",
                          "format=duration", "-of", "csv=p=0", str(p)],
                         capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return None


def keyframe_before(src: Path, t: float, look_back: float = 12.0) -> float | None:
    """Where a stream-copy cut at `t` will ACTUALLY start: the last video
    keyframe at or before it. Only the interval around `t` is read, so this
    costs milliseconds even on a 6-minute source.

    The interval end is ABSOLUTE (`lo%hi`), not a duration (`lo%+n`): ffprobe
    measures `+n` from wherever its seek landed, which is a keyframe before
    `lo`, so the window closes early and the real answer falls outside it. That
    silently returned a keyframe 3s too early on manta-skorpios.
    """
    if not src.exists():
        return None
    lo = max(0.0, t - look_back)
    out = subprocess.run(
        [tool("ffprobe"), "-v", "error",
         "-read_intervals", f"{lo}%{t + 1}",
         "-select_streams", "v:0", "-show_entries", "packet=pts_time,flags",
         "-of", "csv=p=0", str(src)],
        capture_output=True, text=True)
    if out.returncode != 0:
        return None
    keys = []
    for line in out.stdout.splitlines():
        pts, _, flags = line.partition(",")
        if "K" not in flags:
            continue
        try:
            v = float(pts)
        except ValueError:
            continue
        if v <= t + 1e-6:
            keys.append(v)
    return max(keys) if keys else None


def cut_window(raw: Path, final: Path, start: float, duration: float) -> dict:
    """Where the cut clip TRULY sits in the source video.

    `-ss` before `-i` with `-c copy` snaps back to the nearest keyframe, and
    `-avoid_negative_ts make_zero` then rebases the segment — so clip t=0 is
    that keyframe, not `--start`, and the file runs longer than `--duration` by
    the same amount. transcribe.cut() maps every caption from this origin;
    taking it from `--start` instead put every caption ~1s early (1.02s on
    manta-skorpios), which is a real error in what the judge is shown.
    """
    span = media_seconds(final) or duration
    # Independent estimate: the output is longer than requested by exactly the
    # snap-back, so this recovers the origin to within a frame without ffprobe
    # packet parsing. It is the fallback AND the cross-check — a keyframe answer
    # that disagrees with it means the probe window missed the real keyframe.
    guess = start - max(0.0, span - duration)
    t0, how = keyframe_before(raw, start), "keyframe"
    if t0 is None:
        t0, how = guess, "duration"
    elif abs(t0 - guess) > 0.5:
        print(f"  ! keyframe probe says t0={t0:.3f} but the cut's own length says "
              f"{guess:.3f} — trusting the length", file=sys.stderr)
        t0, how = guess, "duration"
    t0 = min(t0, start)                  # a cut can only ever snap BACKWARDS
    if start - t0 > 0.005:
        print(f"  cut snapped back {start - t0:.3f}s to t={t0:.3f}s in the source "
              f"(via {how}) — captions map from there, not from --start")
    return {"t0": round(t0, 3), "span": round(span, 3)}


def download(url: str, name: str, start: float, duration: float, source: str,
             recut: bool = False) -> Path:
    clips = ROOT / "clips"
    clips.mkdir(exist_ok=True)
    final = clips / f"{name}.mp4"
    if final.exists() and not recut:
        print(f"{final.name} already cut")
        return final

    # Keep the full download around so cutting a second fight out of the same
    # video costs nothing.
    raw = raw_path(source)
    raw_dir = raw.parent
    raw_dir.mkdir(parents=True, exist_ok=True)
    if raw.exists():
        print(f"reusing cached {raw.name}")
    else:
        print("downloading (<=720p)...")
        subprocess.run(
            [tool("yt-dlp"), "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]",
             "--merge-output-format", "mp4", "-o", str(raw), url],
            check=True)

    # Cut with a stream copy — much faster and more reliable than yt-dlp
    # --download-sections, which re-encodes and fails on some videos.
    # -avoid_negative_ts make_zero rebases the segment's timestamps to 0;
    # without it currentTime keeps the source offset and the whole HUD desyncs.
    print(f"cutting {start:g}s..{start + duration:g}s")
    subprocess.run([tool("ffmpeg"), "-y", "-ss", str(start), "-i", str(raw),
                    "-t", str(duration), "-c", "copy",
                    "-avoid_negative_ts", "make_zero", str(final)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return final


def fetch_comments(query: str, card: dict | None = None,
                   pinned: list[str] | None = None) -> list[dict]:
    """Real Bright Data when a key is configured, mock otherwise.

    scrape() swallows per-source failures and can return [], so an empty list
    counts as failure too — otherwise a clip silently ships with no comments.

    `card` is what lets a comment be routed to this matchup and a prediction be
    attributed to a side; `pinned` is the episode's fight-card thread, if the
    caller knows one.
    """
    if config.brightdata_key():
        try:
            got = scrape_comments.scrape(query, card, pinned)
            if got:
                return got
            print("  ! bright data returned nothing", file=sys.stderr)
        except Exception as e:
            print(f"  ! bright data: {e}", file=sys.stderr)
    return scrape_comments.mock(query, card)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="youtube url -> clips/, frames/, comments/, timelines/")
    ap.add_argument("url")
    ap.add_argument("--name", help="clip stem (default: slug of the video title)")
    ap.add_argument("--start", type=float, default=0.0, metavar="SEC",
                    help="offset into the source video (default 0)")
    ap.add_argument("--duration", type=float, default=MAX_SECONDS, metavar="SEC",
                    help=f"length of the cut (default {MAX_SECONDS})")
    ap.add_argument("--bots", metavar='"Left,Right"',
                    help="force HUD names instead of reading them off the broadcast")
    ap.add_argument("--query", help="comment search text (default: bot names, else title)")
    ap.add_argument("--post-url", metavar="URL",
                    help="pin the episode's fight-card thread (comma-separated for several) "
                         "— pre-fight predictions, which no post-hoc search can find")
    ap.add_argument("--ko", choices=("left", "right"),
                    help="pin the losing side for a clip you have actually watched")
    ap.add_argument("--backend", default="api", choices=("api", "cli", "openai"),
                    help="which vision judge analyze.py should use (default api)")
    ap.add_argument("--fps", type=float, default=extract_frames.FPS, metavar="N",
                    help=f"frame sampling rate (default {extract_frames.FPS})")
    ap.add_argument("--ko", choices=("left", "right"),
                    help="pin the LOSING side for a clip you have watched")
    ap.add_argument("--looks", metavar='"left desc|right desc"',
                    help="pin what each machine LOOKS like — --bots pins only the names")
    ap.add_argument("--no-audio", action="store_true",
                    help="skip the commentary transcript")
    ap.add_argument("--regrade", action="store_true",
                    help="second pass re-grading each blow's severity")
    ap.add_argument("--stop-pass", action="store_true",
                    help="second pass asking when the LOSER stopped moving")
    ap.add_argument("--verify", action="store_true",
                    help="second pass re-checking WHO landed each scored blow")
    ap.add_argument("--recut", action="store_true",
                    help="re-cut an existing clip to a new --duration and stop "
                         "(no frames, no judging, no API spend)")
    args = ap.parse_args()

    bots = None
    if args.bots:
        left, _, right = args.bots.partition(",")
        if not (left.strip() and right.strip()):
            sys.exit('--bots needs two names, e.g. --bots "Jackpot,Copperhead"')
        bots = {"left": left.strip(), "right": right.strip()}

    # parsed up here, not next to the analyze() call: transcribe() needs it too, to
    # know which machine carries which weapon when it drops garbled cues
    looks = None
    if args.looks:
        left, _, right = args.looks.partition("|")
        if not (left.strip() and right.strip()):
            sys.exit('--looks needs two descriptions, e.g. --looks "blue wedge|red bar"')
        looks = {"left": left.strip(), "right": right.strip()}

    title = probe_title(args.url)
    name = args.name or slug(title)
    query = args.query or (f"{bots['left']} {bots['right']}" if bots else title)
    print(f"» {title}  ->  {name}")

    final = download(args.url, name, args.start, args.duration, slug(title), args.recut)
    source_json = ROOT / "clips" / f"{name}.source.json"

    # What the clip was cut from, so transcribe.py can slice the source video's
    # captions to this window later without re-deriving the offset by hand.
    # t0/span are where the cut LANDED; start/duration are what was asked for.
    record = {"url": args.url, "start": args.start, "duration": args.duration}
    record.update(cut_window(raw_path(slug(title)), final, args.start, args.duration))

    # --recut only lengthens the TAIL. -ss is applied before -i and is independent
    # of -t, so a longer cut is byte-identical at the front — every timestamp in an
    # existing timeline still lines up, which is the whole point of stopping here.
    # Re-extracting frames or re-judging would spend money to re-describe a
    # celebration nobody is judging.
    if args.recut:
        source_json.write_text(json.dumps(record, indent=2) + "\n")
        print(f"re-cut only — frames, transcript and timeline left alone. "
              f"{source_json.name} updated.")
        return

    extract_frames.extract(f"{name}.mp4", fps=args.fps)

    source_json.write_text(json.dumps(record, indent=2) + "\n")
    if not args.no_audio:
        try:
            transcribe.transcribe(f"{name}.mp4", bots=bots, looks=looks)
        except Exception as e:            # commentary is a bonus, never a blocker
            print(f"  ! transcription failed, judging on frames alone: "
                  f"{str(e)[:200]}", file=sys.stderr)

    pinned = [u.strip() for u in (args.post_url or "").split(",") if u.strip()] \
        or ([scrape_comments.FIGHT_CARD[name]] if name in scrape_comments.FIGHT_CARD else [])
    comments = fetch_comments(query, bots, pinned)
    (ROOT / "comments").mkdir(exist_ok=True)
    (ROOT / "comments" / f"{name}.json").write_text(json.dumps(comments, indent=2) + "\n")
    print(f"{len(comments)} comments for {query!r}")

    analyze.analyze(f"{name}.mp4", backend=args.backend, bots=bots,
                    ko=args.ko, audio=not args.no_audio, looks=looks,
                    regrade=args.regrade, stop=args.stop_pass,
                    verify_pass=args.verify)

    print("\n  serve from the repo root:  python3 backend/serve.py")
    print(f"  then open:  http://localhost:{PORT}/frontend/index.html?clip={name}\n")


if __name__ == "__main__":
    main()
