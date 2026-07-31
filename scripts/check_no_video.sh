#!/usr/bin/env bash
# check_no_video.sh — fail if any video would ship inside the deployment bundle.
#
#   bash scripts/check_no_video.sh
#
# COMPLIANCE.md, "Rules the code must respect": no clip files anywhere inside the
# deployment bundle. Anything in the bundle is hosted by Vercel regardless of what
# the UI links to, which defeats the whole point of hosting the clips elsewhere —
# a DMCA notice follows the file, and abuse enforcement lands on the account.
#
# It checks what would actually be UPLOADED, which is not the same as what is in
# the repo: .vercelignore governs a `vercel --prod` upload and REPLACES
# .gitignore for that purpose. So a file can be gitignored and still deploy.
#
# ---------------------------------------------------------------------------
# NOT WIRED INTO A BUILD YET, AND IT WOULD FAIL TODAY IF IT WERE. The clips are
# still committed and still served from the bundle — COMPLIANCE.md item 1. Wiring
# this in now would simply block every deploy.
#
# The moment the clips move to R2 and .vercelignore excludes clips/, add to
# vercel.json:
#
#     "buildCommand": "bash scripts/check_no_video.sh"
#
# That is a guard, not a build: the static files still deploy as they are, so it
# does not give the project a build step in the sense CLAUDE.md rules out.
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")/.."

EXTS="mp4|webm|mkv|mov|avi|ts|m4v|m2ts"

# Everything .vercelignore excludes, as prune paths. Comments and blanks dropped.
prunes=()
if [ -f .vercelignore ]; then
  while IFS= read -r line; do
    line="${line%%#*}"; line="${line//[[:space:]]/}"
    [ -z "$line" ] && continue
    prunes+=(-path "./${line%/}" -prune -o)
  done < .vercelignore
fi

found=$(find . "${prunes[@]}" -type f -regextype posix-extended \
          -iregex ".*\.($EXTS)$" -print 2>/dev/null || \
        find . "${prunes[@]}" -type f -print 2>/dev/null |
          grep -iE "\.($EXTS)$" || true)

if [ -n "$found" ]; then
  echo "FAIL — video inside the deployment bundle:" >&2
  echo "$found" | sed 's/^/  /' >&2
  echo >&2
  echo "Whoever serves these bytes receives the DMCA notice. Move them to the" >&2
  echo "clip bucket and exclude the directory in .vercelignore." >&2
  echo "See COMPLIANCE.md, 'Deployment and hosting separation'." >&2
  exit 1
fi

echo "OK — no video in the deployment bundle"
