#!/usr/bin/env bash
# teardown.sh — delete every hosted clip asset, in one command.
#
#   bash scripts/teardown.sh --dry-run   # list what WOULD go. Default.
#   bash scripts/teardown.sh --yes       # actually delete
#
# COMPLIANCE.md, "Takedown readiness". This is the bytes half of a takedown; the
# UI half is scripts/killswitch.sh. Run both — flipping the site dark leaves the
# clips reachable by direct URL, and emptying the bucket leaves a site that 404s
# its own video.
#
# Reads CLIP_BUCKET and the S3-compatible credentials from .env (gitignored), the
# same place every other key lives. Works against Cloudflare R2 or Backblaze B2
# through the aws CLI's S3 API, which is what both providers speak.
#
#   CLIP_BUCKET=gameover-clips
#   CLIP_S3_ENDPOINT=https://<accountid>.r2.cloudflarestorage.com
#   AWS_ACCESS_KEY_ID=...
#   AWS_SECRET_ACCESS_KEY=...
#
# ---------------------------------------------------------------------------
# UNTESTED AGAINST A REAL BUCKET. As of writing, the clips are still committed to
# git and served by Vercel — the migration in COMPLIANCE.md item 1 has not
# happened — so there IS no bucket to point this at and nothing here has ever
# run for real. It defaults to --dry-run for that reason. Verify it against the
# bucket the day the clips move, not the day you need it.
#
# Until then, the actual teardown for the clips is: delete the four files, drop
# the ! exceptions from .gitignore, commit, push. That takes them off the deploy
# but NOT out of git history.
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] && set -a && . ./.env && set +a

: "${CLIP_BUCKET:?no CLIP_BUCKET in .env — nothing to tear down. If the clips are
still committed to git and served by Vercel, this script does not apply yet; see
the note at the top of the file.}"
: "${CLIP_S3_ENDPOINT:?no CLIP_S3_ENDPOINT in .env}"

command -v aws >/dev/null || { echo "aws CLI not found — brew install awscli" >&2; exit 1; }

echo "bucket:   s3://$CLIP_BUCKET"
echo "endpoint: $CLIP_S3_ENDPOINT"
echo
aws s3 ls "s3://$CLIP_BUCKET" --endpoint-url "$CLIP_S3_ENDPOINT" --recursive --human-readable

if [ "${1:---dry-run}" != "--yes" ]; then
  echo
  echo "DRY RUN — nothing deleted. Re-run with --yes to delete all of the above."
  exit 0
fi

echo
read -r -p "Delete EVERYTHING listed above? This cannot be undone. [type DELETE] " ok
[ "$ok" = "DELETE" ] || { echo "aborted"; exit 1; }

aws s3 rm "s3://$CLIP_BUCKET" --endpoint-url "$CLIP_S3_ENDPOINT" --recursive
echo
echo "bucket emptied. Now take the UI down too:  bash scripts/killswitch.sh off"
