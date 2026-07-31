#!/usr/bin/env python3
"""Shared config: loads .env and normalises key names.

Nothing here depends on python-dotenv — it's a dozen lines and one less install.
Real environment variables always win over .env, so `export FOO=x` overrides the
file for a one-off run.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Accept either spelling so a .env written from memory still works.
BRIGHTDATA_NAMES = ("BRIGHTDATA_API_KEY", "BRIGHTDATA_KEY")
ANTHROPIC_NAMES = ("ANTHROPIC_API_KEY", "ANTHROPIC_KEY")
OPENAI_NAMES = ("OPENAI_API_KEY", "OPENAI_KEY")
ELEVENLABS_NAMES = ("ELEVENLABS_API_KEY", "ELEVENLABS_KEY")


def load_env(path: Path | None = None) -> None:
    """Read .env into os.environ without clobbering real env vars.

    An EMPTY environment variable does not count as set. This was `key not in
    os.environ`, and a shell with `OPENAI_API_KEY=` exported — which is what you
    get from a half-finished export, a sourced script, or a launcher that
    forwards every name it knows — silently shadowed a perfectly good key in
    .env and 401'd every call. It reads as "the key in .env is broken", which is
    the same wrong conclusion the worktree-.env trap produces, and it cost a
    pre-flight here. get() below has always treated empty as absent; this makes
    the two agree, so there is no value of the variable that loads here and
    fails there.
    """
    env = path or (ROOT / ".env")
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and not os.environ.get(key):
            os.environ[key] = value


def get(names: tuple[str, ...]) -> str | None:
    load_env()
    for n in names:
        if os.environ.get(n):
            return os.environ[n]
    return None


def brightdata_key() -> str | None:
    return get(BRIGHTDATA_NAMES)


def anthropic_key() -> str | None:
    return get(ANTHROPIC_NAMES)


def openai_key() -> str | None:
    return get(OPENAI_NAMES)


def elevenlabs_key() -> str | None:
    return get(ELEVENLABS_NAMES)
