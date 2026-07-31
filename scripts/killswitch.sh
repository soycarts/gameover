#!/usr/bin/env bash
# killswitch.sh off|on — take the whole site dark, or bring it back.
#
#   bash scripts/killswitch.sh off     # every route serves the offline page
#   bash scripts/killswitch.sh on      # restore
#   bash scripts/killswitch.sh status  # which state is committed right now
#
# COMPLIANCE.md asks for "an env var such as SITE_ENABLED=false". That is not
# available here and the difference is worth understanding rather than papering
# over: this is a PURE STATIC deploy with no build step and no serverless
# functions, so nothing runs at request time that could read an env var. Giving
# it one would mean adding a build step to the project, which CLAUDE.md rules out
# as an architectural constraint.
#
# A rewrite achieves the same end state — every route serves a static offline
# page — through the one mechanism a static deploy does have. It is one command,
# it is testable locally, and unlike an env var it is visible in git, so the
# site's state is never ambiguous.
#
# The clips are NOT deleted by this. Flipping the site dark hides the UI; the
# bytes stay wherever they are hosted and are still reachable by direct URL.
# Use scripts/teardown.sh for the bytes. For a takedown, run BOTH.
set -euo pipefail
cd "$(dirname "$0")/.."

LIVE='{ "source": "/", "destination": "/frontend/index.html" }'
DARK='{ "source": "/(.*)", "destination": "/frontend/offline.html" }'

state() { grep -q 'offline.html' vercel.json && echo dark || echo live; }

case "${1:-status}" in
  off)
    [ "$(state)" = dark ] && { echo "already dark"; exit 0; }
    cp vercel.json vercel.json.live
    cat > vercel.json <<JSON
{
  "rewrites": [
    $DARK
  ]
}
JSON
    echo "vercel.json -> DARK. Deploy it:  vercel --prod"
    echo "the clips are still served from their bucket — run scripts/teardown.sh too"
    ;;
  on)
    [ "$(state)" = live ] && { echo "already live"; exit 0; }
    if [ -f vercel.json.live ]; then mv vercel.json.live vercel.json
    else
      cat > vercel.json <<JSON
{
  "rewrites": [
    $LIVE,
    { "source": "/about", "destination": "/frontend/about.html" },
    { "source": "/takedown", "destination": "/frontend/takedown.html" }
  ]
}
JSON
    fi
    echo "vercel.json -> LIVE. Deploy it:  vercel --prod"
    ;;
  status) echo "$(state)" ;;
  *) echo "usage: $0 off|on|status" >&2; exit 2 ;;
esac
