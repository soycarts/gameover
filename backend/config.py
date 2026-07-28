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


def load_env(path: Path | None = None) -> None:
    """Read .env into os.environ without clobbering real env vars."""
    env = path or (ROOT / ".env")
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
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
