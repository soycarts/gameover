#!/usr/bin/env python3
"""ingest.py <youtube_url> — ERA B: any fight video -> playable HUD, one command.

    python backend/ingest.py "https://www.youtube.com/watch?v=..."

Downloads at 720p max, caps to the first 120s, extracts frames, scrapes fan
comments for the video title, runs the vision judge, then prints the URL to open.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import extract_frames  # noqa: E402
import scrape_comments  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MAX_SECONDS = 120
PORT = 8000


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:40] or "clip").strip("-")


def probe_title(url: str) -> str:
    out = subprocess.run(["yt-dlp", "--no-warnings", "--dump-single-json", url],
                         capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"yt-dlp failed:\n{out.stderr.strip()[:400]}")
    return json.loads(out.stdout).get("title", "fight")


def download(url: str, name: str) -> Path:
    clips = ROOT / "clips"
    clips.mkdir(exist_ok=True)
    final = clips / f"{name}.mp4"
    if final.exists():
        print(f"{final.name} already downloaded")
        return final

    raw = clips / f"{name}.raw.mp4"
    print("downloading (<=720p)...")
    subprocess.run(
        ["yt-dlp", "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]",
         "--merge-output-format", "mp4", "-o", str(raw), url],
        check=True)

    # Cap length with a stream copy — much faster and more reliable than
    # yt-dlp --download-sections, which re-encodes and fails on some videos.
    print(f"capping to first {MAX_SECONDS}s...")
    subprocess.run(["ffmpeg", "-y", "-i", str(raw), "-t", str(MAX_SECONDS),
                    "-c", "copy", str(final)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    raw.unlink(missing_ok=True)
    return final


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    url = sys.argv[1]
    for tool in ("yt-dlp", "ffmpeg"):
        if not shutil.which(tool):
            sys.exit(f"{tool} not found on PATH")

    title = probe_title(url)
    name = slug(title)
    print(f"» {title}  ->  {name}")

    download(url, name)
    extract_frames.extract(f"{name}.mp4")

    import os
    comments = (scrape_comments.scrape(title) if os.environ.get("BRIGHTDATA_API_KEY")
                else scrape_comments.mock(title))
    (ROOT / "comments" / f"{name}.json").write_text(json.dumps(comments, indent=2) + "\n")
    print(f"{len(comments)} comments"
          f"{'' if os.environ.get('BRIGHTDATA_API_KEY') else ' (mock — no BRIGHTDATA_API_KEY)'}")

    import analyze
    analyze.analyze(f"{name}.mp4")

    print("\n  serve from the repo root:  python -m http.server", PORT)
    print(f"  then open:  http://localhost:{PORT}/frontend/index.html?clip={name}\n")


if __name__ == "__main__":
    main()
