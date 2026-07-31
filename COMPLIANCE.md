# gameover: legal posture and implementation rules

## Context for the agent

This project self-hosts short clips of BattleBots footage and overlays derived
analytics (hit markers, health bars, aggression scores) plus aggregated Reddit
sentiment. The clips are the one unlicensed element and cannot be made safe, only made
low-profile. Every rule below exists to keep the project's realistic worst case at
"DMCA takedown, site goes down, project survives" instead of anything sharper.

Treat these as hard constraints. If a feature request conflicts with one, flag the
conflict instead of silently implementing it.

## Hard rules

1. No monetization of any kind. No ads, no affiliate links, no donation button, no paid
   tier, no crypto.
2. No account system, signup wall, email capture, or paywall. The site is anonymous and
   fully open.
3. No video files committed to git. Add `*.mp4`, `*.webm`, `*.mkv`, `*.ts`, `clips/`,
   `raw/` to `.gitignore` before the first clip lands.

## Clip handling

- Store a `source_video_id`, `source_url`, `start_seconds`, and `end_seconds` on every
  clip record. These are needed for attribution and for responding to a complaint.

## Attribution

Build a reusable `<SourceAttribution />` component and render it on every surface that
shows a clip.

- Visible credit line: "Footage © BattleBots Inc. Used here for fan analysis."
- A visible link on every clip back to the original video at its start timestamp
  (`https://www.youtube.com/watch?v={id}&t={start}s`).
- A persistent site footer stating the project is an unaffiliated fan analytics tool
  with no endorsement by or affiliation with BattleBots Inc.
- An `/about` page describing what the tool does, that it links back to official
  sources, and how to contact the maintainer.

## Search visibility

The goal is discoverable by people you send there, not by people searching for
BattleBots.

- `<meta name="robots" content="noindex, nofollow">` on every page.
- `robots.txt` with `Disallow: /` for all user agents.
- No sitemap, no structured data markup, no Open Graph video tags (`og:video` in
  particular). A plain `og:image` of your own UI is fine for the Reddit post preview.
- Do not submit to Google Search Console or any indexing service.

## Reddit and social data

- Bright Data's terms govern how you collect. Read and follow their acceptable use
  policy; their partnerships convey nothing about republishing BattleBots content.
- Store comment records as: `comment_id`, `permalink`, `created_utc`, `score`, `derived
  sentiment`, `derived topic tags`. Do not store the full comment body in the production
  database beyond what the UI displays.
- Do not store or display Reddit usernames. Hash them if you need per-author
  deduplication, and hash with a salt held outside the repo.
- UK GDPR applies since the operator is UK-based. Dropping identifiers is what keeps the
  controller obligations off the table. If any identifier is retained, a lawful-basis
  assessment and an Article 14 privacy notice become necessary.

## Takedown readiness

- Add a clear contact route: an email address on `/about` and a `/takedown` page with a
  one-line "email this address and content will be removed within 24 hours" commitment.
  Honour it.
- Implement a kill switch: an env var such as `SITE_ENABLED=false` that serves a static
  "offline" page across all routes. Test that it works before launch.
- Write `scripts/teardown.sh` that deletes all hosted clip assets from the storage
  bucket in one command.
- Host clips on storage that is separate from anything else you own. See "Deployment and
  hosting separation" for the required setup.
- Keep the analytics layer functional without the clips. The metadata, models, and
  dashboards are yours and should survive a video takedown intact. Structure the code so
  clips are a pluggable presentation layer rather than a dependency of the pipeline.

## Deployment and hosting separation

The governing principle: a DMCA notice follows the file. Whoever serves the video bytes
receives the complaint, and abuse enforcement lands on the account, not on the
individual asset. Keep the clips off any account that hosts other work.

### Required architecture

- **Clips:** a dedicated Cloudflare R2 bucket (or Backblaze B2), under an account
  created with a project-specific email and used for nothing else. R2 is preferred for
  zero egress fees, which matters when a Reddit post spikes traffic.
- **App:** the existing Vercel project is fine. It serves the UI, the timeline, the
  overlays, and the API. It must not serve video.
- **Domain:** gameover.fyi. Apex points at Vercel, `clips.gameover.fyi` points at the R2
  bucket. Registering it alongside other domains at the same registrar is fine, since
  registrar accounts are not an enforcement vector here.
- **Pipeline:** ingest, clipping, and inference stay wherever they already run. They
  serve nothing publicly and carry no exposure.

### Rules the code must respect

- No clip files in `public/`, `static/`, or anywhere inside the deployment bundle.
  Anything in the bundle is hosted by Vercel regardless of what the UI links to, which
  defeats the separation.
- No use of Vercel Blob for clips.
- All clip URLs resolve from a single `CLIP_BASE_URL` env var so storage can be swapped
  in one place.
- Add a build-time check that fails the build if any video file extension is found in
  the deployment directory. Wire it into the `prebuild` script.
- Vercel's fair use terms lean against using the platform as a media host, and Hobby
  bandwidth is modest. The separation is correct on cost and throughput grounds
  independent of the legal reasoning.

## Contacts

- Takedown contact is a project address (`abuse@gameover.fyi`), not a personal inbox.
- Storage account registered to that address so provider correspondence stays in one
  place.

## General

- Do not point the hackathon submission at a personal or professional domain.
- Keep the deploy reproducible so the project can move hosts quickly if a provider pulls
  it.

## Repo hygiene

- Add a `README.md` section stating that the repo contains no BattleBots footage and
  that the pipeline expects the user to supply their own inputs.
- Ship the code under a licence that covers your code only, with an explicit note that
  it does not cover third-party media.
- Keep the scraping and downloading tooling in a separate module from the analytics and
  UI, so the reusable parts are cleanly separable.

## Outreach sequencing

Do this in order:

1. Submit to the hackathon.
2. Email BattleBots a private demo link before any public post. Frame it as a fan
   analytics layer they could license or absorb, and offer to take it down on request.
   Approaching them first turns discovery into a conversation rather than a complaint.
3. Message r/battlebots moderators before posting publicly.
4. Post publicly only after the above, and expect the post itself to be the most likely
   trigger for any complaint.

## Note

This is an engineering checklist reflecting a risk posture, not legal advice, and it is
not a substitute for a lawyer's review. The core exposure from self-hosting the footage
remains regardless of how many of these boxes are ticked.

---

# Where the repo actually stands

**Everything above this line is the target. Everything below is an audit of the repo
against it, taken on 31 Jul 2026 at commit `c99f17a`. The two do not currently agree,
and several of the gaps are things the codebase does deliberately and documents as
required — so they are conflicts to resolve, not oversights to tidy.**

Re-run the audit rather than trusting this list once anything moves.

## Already holds

| Rule | State |
|---|---|
| No monetization | Holds. No ads, affiliate links, donation button, paid tier or crypto anywhere. |
| No accounts / paywall / email capture | Holds. The only input on the site is the era B URL box, which posts nowhere. |
| Clip source metadata | Substantially holds. `clips/<clip>.source.json` carries `url`, `start`, `duration`, plus `t0`/`span` for the keyframe the cut actually landed on. Field names differ from the spec (`duration` not `end_seconds`, video id embedded in `url` rather than separate) but nothing is missing. |
| Scraper separated from analytics | Substantially holds. `ingest.py`, `scrape_comments.py` and `crowd.py` are separate modules from `analyze.py` and the frontend. |
| Licence covers code only | Partially. MIT `LICENSE` exists but carries no note excluding third-party media. |

## Does not hold

Ordered by how sharp the exposure is, not by how hard the fix is.

### 1. Four clips are committed to git and served by Vercel — 26 MB

This is the central conflict, and it is deliberate. `.gitignore` is `clips/*` plus a `!`
exception per clip, and `CLAUDE.md` documents this as **required**: *"A git-connected
build only sees committed files, so any new clip you want on the public site needs its
own exception."* The live site serves the bytes from `gameover-nine.vercel.app/clips/`.

Against the doc this breaks hard rule 3, the whole *Deployment and hosting separation*
section, and *No clip files… anywhere inside the deployment bundle*.

Adding `*.mp4` to `.gitignore` in isolation would **take the public site down** — the
HUD falls back to a placeholder arena with no video. The clips have to move to R2 and
`CLIP_BASE_URL` has to exist before the ignore rule can land. Doing it in the other
order breaks the demo.

Note also that removing the files from the working tree does not remove them from
history; a genuine purge needs a rewrite of every commit that touched `clips/`.

### 2. Reddit usernames are stored and displayed

50 distinct usernames across three files, and the UI renders them as `u/<name>` in two
places — `index.html:1974` (the in-fight fan comment) and `:2270` (the crowd card
quotes). Attribution is a shipped, documented feature.

This is the sharpest item on the page: the doc puts it under UK GDPR, and *"dropping
identifiers is what keeps the controller obligations off the table."* Unlike the clips
it is cheap to fix — the salted hash the doc describes preserves the per-author
deduplication the pool actually uses, and the on-screen credit degrades to
`r/battlebots`, which the card already renders when `author` is absent.

The comment records also keep the full `text` body. The UI does display it, so this sits
inside the doc's carve-out, but `created_utc` is absent where the spec asks for it.

### 3. The site is fully indexable

No `<meta name="robots">` anywhere in `index.html`, and no `robots.txt` at all. Nothing
has been submitted to Search Console, but nothing prevents crawling either. No `og:`
tags of any kind at present, so the *no `og:video`* rule holds by absence rather than by
decision — worth pinning before anyone adds a share preview.

### 4. No attribution surface exists

No credit line, no link back to the source video, no footer, no `/about`, no
`/takedown`. The source URL and start timestamp needed to build the link are already on
disk in `clips/<clip>.source.json`, so the data side is done and only the rendering is
missing.

### 5. No takedown machinery

No `SITE_ENABLED` kill switch, no `scripts/teardown.sh`, no project contact address. The
"remove within 24 hours" commitment cannot be honoured at speed without at least the
kill switch.

### 6. No `CLIP_BASE_URL`, no prebuild check

Clip URLs are hard-coded as `../clips/<clip>.mp4` relative paths in `index.html`. There
is no build step at all — the site is a pure static deploy — so the `prebuild` video-
extension check has nowhere to hook until one exists.

### 7. README claims the opposite of the doc's requirement

The doc asks for a section stating the repo contains **no** BattleBots footage. It
currently contains four clips, so that section cannot be written truthfully until item 1
is done. Writing it before then would be worse than leaving it out.

## The honest summary

The two rules that are fully satisfied — no monetization and no accounts — are the two
that were never going to be violated. Every rule that constrains how the footage and the
Reddit data are handled is currently unmet, and the two that matter most (clips in the
deployment bundle, usernames on screen) are load-bearing features rather than
accidents.

Sequencing that follows from the dependencies rather than from the doc's ordering:

1. **Usernames.** Independent of everything else, cheap, and the only item with a
   regulatory rather than a takedown flavour.
2. **`robots.txt` + noindex.** One file and one meta tag. Directly serves the stated
   goal of being discoverable by invitation rather than by search.
3. **Attribution, `/about`, `/takedown`, kill switch.** All additive, none of them break
   anything, and they are what turn a complaint into an email.
4. **Move the clips to R2 behind `CLIP_BASE_URL`.** The largest change, and the one that
   must land before `*.mp4` can enter `.gitignore` without taking the site down.

None of this is legal advice, and the note above the line applies to the audit as much
as to the checklist: ticking every box leaves the core exposure from self-hosting the
footage exactly where it was.
