#!/usr/bin/env bash
# Generates clips/synthfight.mp4 — a 45s synthetic "fight" (two moving boxes and
# a burned-in clock) paired with timelines/synthfight.json.
#
# It exists so the HUD can be developed and restyled against a REAL <video>
# element without a curated clip or an API key. The burned-in clock makes it
# obvious at a glance whether the HUD is actually synced to video time.
#
#   bash backend/make_test_clip.sh
#   -> http://localhost:40911/frontend/index.html?clip=synthfight
set -euo pipefail
cd "$(dirname "$0")/.."

ffmpeg -y -f lavfi -i color=c=0x0d1220:s=1280x720:r=30:d=45 -vf "\
drawbox=x='180+260*sin(t*0.7)':y='260+120*cos(t*1.1)':w=170:h=120:color=0x29d3ff@1:t=fill,\
drawbox=x='880+240*sin(t*0.9+2)':y='280+110*cos(t*0.8)':w=170:h=120:color=0xff7b29@1:t=fill,\
drawtext=fontfile=/System/Library/Fonts/Helvetica.ttc:text='%{pts\:hms}':x=w/2-90:y=60:fontsize=54:fontcolor=white" \
  -c:v libx264 -pix_fmt yuv420p clips/synthfight.mp4 2>/dev/null

echo "wrote clips/synthfight.mp4 ($(du -h clips/synthfight.mp4 | cut -f1))"
echo "open: http://localhost:40911/frontend/index.html?clip=synthfight"
