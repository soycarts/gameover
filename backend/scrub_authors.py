#!/usr/bin/env python3
"""scrub_authors.py — replace stored Reddit usernames with opaque tokens.

    python backend/scrub_authors.py --check     # report only, writes nothing
    python backend/scrub_authors.py             # rewrite comments/*.json

COMPLIANCE.md: usernames are neither stored nor displayed. The operator is
UK-based, so a retained username is personal data under UK GDPR; dropping the
identifier is what keeps the controller obligations off the table.

This is the ONE-OFF migration for files scraped before that rule existed.
crowd.enrich() now hashes at scrape time, so nothing written from here on ever
carries a plaintext username and this script has nothing to do on a fresh pool.

It rewrites `author` -> `by`, an unsalted-hash-proof token from
crowd.author_hash(). Equality within a file survives, which is the only property
anything downstream reads: pair_exchanges() uses it to reject a reply to
yourself, and the HUD does not use it at all any more.

**Rewriting the file does not rewrite git history.** Every previous commit still
carries the usernames, and `git log -p comments/` will show them. Scrubbing the
history needs a filter-repo pass over every commit that touched comments/, which
is a separate and much more disruptive operation — recorded in COMPLIANCE.md
rather than done silently here.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import crowd

ROOT = Path(__file__).resolve().parent.parent


def scrub(path: Path, write: bool) -> tuple[int, int]:
    recs = json.loads(path.read_text())
    named = [r for r in recs if r.get("author")]
    for r in recs:
        author = r.pop("author", "")           # pop: the key must not survive
        if author and not r.get("by"):
            r["by"] = crowd.author_hash(author)
    if write and named:
        path.write_text(json.dumps(recs, indent=1, ensure_ascii=False) + "\n")
    return len(recs), len(named)


if __name__ == "__main__":
    write = "--check" not in sys.argv
    total = 0
    for p in sorted((ROOT / "comments").glob("*.json")):
        n, named = scrub(p, write)
        total += named
        state = ("scrubbed" if write else "would scrub") if named else "clean"
        print(f"  {p.name:30} {n:3} records, {named:3} with a username — {state}")
    print(f"\n{total} username(s) {'removed' if write and total else 'found'}")
    if total and not write:
        print("re-run without --check to rewrite")
    print("NOTE: git history still holds them — see COMPLIANCE.md")
