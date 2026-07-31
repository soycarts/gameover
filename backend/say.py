#!/usr/bin/env python3
"""say.py — generate an arcade announcer line with ElevenLabs, once.

    python backend/say.py --list                     # what voices this account has
    python backend/say.py perfect "PERFECT"           # -> sfx/perfect.mp3
    python backend/say.py perfect "PERFECT" --voice Adam --style 0.9

The frontend synthesises every other sound from oscillators and ships no audio
files. This is the one exception: a spoken word cannot be faked with a square
wave, and browser speech synthesis hands you whatever voice the viewer's OS
happens to have. So the line is rendered ONCE, committed as an asset, and served
statically — no key in the browser, no API call at runtime.

The script is committed rather than run ad hoc so the asset is reproducible: it
prints the voice id, model and settings it used, and re-running with those
arguments regenerates the same character of line.
"""
import argparse
import subprocess
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.elevenlabs.io/v1"
MODEL = "eleven_multilingual_v2"
TIMEOUT = 60


def key() -> str:
    """The key, or a message naming the worktree trap that usually causes this.

    A git worktree has its own .env and config.ROOT resolves to the worktree, so
    a key added to the main checkout is invisible here. That has already cost a
    whole judging run once.
    """
    k = config.elevenlabs_key()
    if not k:
        sys.exit("no ELEVENLABS_KEY / ELEVENLABS_API_KEY found.\n"
                 f"  looked in {config.ROOT / '.env'} and the environment.\n"
                 "  a worktree has its OWN .env — a key in the main checkout "
                 "does not reach it.")
    return k


def voices() -> list[dict]:
    r = requests.get(f"{API}/voices", headers={"xi-api-key": key()}, timeout=TIMEOUT)
    if not r.ok:
        sys.exit(f"voices failed: {r.status_code} {r.text[:200]}")
    return r.json().get("voices", [])


def pick(want: str | None) -> dict:
    """Resolve --voice to one voice on the account, by id or by name.

    Falls back to the first voice rather than to a hard-coded id: voice ids are
    account-specific, and a stale default would 404 on anyone else's key.
    """
    vs = voices()
    if not vs:
        sys.exit("this account has no voices")
    if not want:
        return vs[0]
    w = want.lower().strip()
    for v in vs:
        name = v.get("name", "").lower()
        # stock voices are named "Harry - Fierce Warrior", so match the leading
        # name and any substring too — nobody types the marketing tagline
        if w in (v.get("voice_id", "").lower(), name, name.split(" - ")[0].strip()):
            return v
    for v in vs:
        if w in v.get("name", "").lower():
            return v
    names = ", ".join(v.get("name", "?") for v in vs)
    sys.exit(f"no voice matching {want!r}. this account has: {names}")


def deepen(path: Path, pitch: float, room: float) -> None:
    """Drop the pitch and put the voice in a room, in place.

    ElevenLabs will not go as low as an arena announcer on its own — the stock
    voices top out at "deep for a person". Resampling below the recorded rate
    lowers the formants as well as the pitch, which is what makes it read as a
    big voice rather than a slowed-down small one; atempo then puts the duration
    back so the cue still lands on the beat. A little echo does the rest: the
    announcer is in the building with you, not in a booth.
    """
    if pitch == 1.0 and not room:
        return
    sr = 44100
    chain = [f"asetrate={sr}*{pitch:.4f}", f"aresample={sr}", f"atempo={1 / pitch:.4f}"]
    if room:
        chain.append(f"aecho=0.9:0.85:{int(18 + room * 40)}:{room:.2f}")
    chain.append("dynaudnorm=f=200")          # even out what the echo unbalances
    tmp = path.with_suffix(".tmp.mp3")
    done = subprocess.run(["ffmpeg", "-y", "-i", str(path), "-af", ",".join(chain),
                           "-b:a", "128k", str(tmp)],
                          capture_output=True, text=True)
    if done.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        print(f"  ! ffmpeg failed, keeping the raw voice: "
              f"{done.stderr.strip()[-200:]}", file=sys.stderr)
        return
    tmp.replace(path)
    print(f"  deepened pitch={pitch} room={room}")


def render(text: str, out: Path, voice: dict, stability: float, style: float,
           boost: float) -> None:
    body = {
        "text": text,
        "model_id": MODEL,
        # Low stability + high style is what makes it declaim rather than read.
        # An announcer is the opposite of a narrator: the default settings give a
        # calm, even delivery, which lands completely flat over a knockout.
        "voice_settings": {"stability": stability, "similarity_boost": boost,
                           "style": style, "use_speaker_boost": True},
    }
    r = requests.post(f"{API}/text-to-speech/{voice['voice_id']}",
                      headers={"xi-api-key": key(), "accept": "audio/mpeg"},
                      json=body, timeout=TIMEOUT)
    if not r.ok:
        sys.exit(f"text-to-speech failed: {r.status_code} {r.text[:300]}")
    if not r.content:
        sys.exit("text-to-speech returned an empty body")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(r.content)
    print(f"wrote {out.relative_to(ROOT)} — {len(r.content) / 1024:.1f} kB\n"
          f"  voice   {voice.get('name')} ({voice['voice_id']})\n"
          f"  model   {MODEL}\n"
          f"  settings stability={stability} style={style} similarity={boost}")


def main() -> None:
    ap = argparse.ArgumentParser(description="one spoken line -> sfx/<name>.mp3")
    ap.add_argument("name", nargs="?", help="output stem, e.g. 'perfect'")
    ap.add_argument("text", nargs="?", help="what to say")
    ap.add_argument("--voice", help="voice name or id (default: first on the account)")
    ap.add_argument("--list", action="store_true", help="list this account's voices")
    ap.add_argument("--stability", type=float, default=0.30)
    ap.add_argument("--style", type=float, default=0.85)
    ap.add_argument("--similarity", type=float, default=0.80)
    ap.add_argument("--pitch", type=float, default=0.84, metavar="R",
                    help="resample ratio: <1 deepens, 1.0 leaves it alone")
    ap.add_argument("--room", type=float, default=0.28, metavar="N",
                    help="echo depth, 0 for a dry booth voice")
    args = ap.parse_args()

    if args.list:
        for v in voices():
            labels = v.get("labels") or {}
            bits = " ".join(f"{k}={x}" for k, x in labels.items())
            print(f"  {v.get('name','?'):<22} {v['voice_id']}  {bits}")
        return
    if not (args.name and args.text):
        ap.error("give a NAME and TEXT, or --list")
    out = ROOT / "sfx" / f"{args.name}.mp3"
    render(args.text, out, pick(args.voice), args.stability, args.style,
           args.similarity)
    deepen(out, args.pitch, args.room)


if __name__ == "__main__":
    main()
