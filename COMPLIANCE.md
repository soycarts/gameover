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
against it, re-taken on 31 Jul 2026 after the first implementation pass.**

Re-run the audit rather than trusting this list once anything moves.

## Holds

| Rule | How |
|---|---|
| No monetization | No ads, affiliate links, donation button, paid tier or crypto. |
| No accounts / paywall / email capture | The only input is the era B URL box, which posts nowhere. |
| No usernames stored or displayed | `crowd.author_hash()` salts and truncates at scrape time; the plaintext never enters a record. `backend/scrub_authors.py` migrated the 57 already committed. The UI credits `r/battlebots` on both render paths. **Git history still holds the old names** — see below. |
| Salt held outside the repo | `GAMEOVER_AUTHOR_SALT` in `.env`, which is gitignored *and* vercelignored. `author_hash()` refuses to run without it rather than emitting a reversible hash. |
| noindex / nofollow | On all three pages, plus `googlebot`. |
| `robots.txt` with `Disallow: /` | At the deploy root. No sitemap. |
| No `og:video`, no structured data | None present. |
| Visible credit line | `#legal`, on every surface — one element inside `#stage`, above every screen, so the title card, the fight and the GAME OVER card cannot drift apart. |
| Link back to the source at its timestamp | `sourceLink()` builds it from `clips/<clip>.source.json`. Prefers `t0` over `start` — the keyframe the cut actually landed on, 1.02s apart on manta. |
| Persistent unaffiliated footer | In `#legal`, hidden only on narrow screens and dimmed during play. |
| `/about` and `/takedown` | Real pages, rewritten in `vercel.json` **and** in `serve.py` so dev matches production. |
| Takedown contact + 24h commitment | `abuse@gameover.fyi`, on both pages and in the README. |
| Kill switch | `scripts/killswitch.sh off` — verified to round-trip and restore the config exactly. It is a rewrite, not an env var; see the script for why a static deploy cannot have one without gaining a build step. |
| `scripts/teardown.sh` | Written. **Never run against a real bucket, because there isn't one yet.** Defaults to `--dry-run`. |
| Single `CLIP_BASE_URL` | `frontend/config.js`, read through `clipUrl()`. Every clip asset — video and `source.json` — resolves through it. |
| No-video build check | `scripts/check_no_video.sh`, and its `.vercelignore` prune logic is verified both ways. **Deliberately not wired in: it fails today, correctly.** |
| Licence covers code only | Note appended to `LICENSE` disclaiming any rights in third-party media or marks. |
| README states the input policy | Says the pipeline expects your own inputs, and flags the committed clips as the exception being removed. |
| Scraper separated from analytics | `ingest.py` / `scrape_comments.py` / `crowd.py` are separate from `analyze.py` and the frontend. |
| Analytics survive a clip takedown | Already true and now load-bearing: `?demo=1` and a missing clip both fall back to the rAF clock, so the HUD, the timeline and the crowd card run with no video at all. |

## Does not hold

### 1. Four clips are committed to git and served by Vercel — 26 MB

Unchanged, and still the central conflict. `.gitignore` is `clips/*` plus a `!` exception
per clip, and `CLAUDE.md` documents this as **required** for a git-connected build. This
breaks hard rule 3 and the whole *Deployment and hosting separation* section.

**Everything needed to fix it is now in place except the bucket.** `CLIP_BASE_URL` is
plumbed, the teardown script is written, the build check is written and verified. The
remaining steps need credentials and account creation, which is not something an agent
should be doing on your behalf:

1. Create the Cloudflare R2 account under a project-specific email, and a bucket.
2. Upload the four clips and the `.source.json` files.
3. Point `clips.gameover.fyi` at the bucket.
4. Set `CLIP_BASE` in `frontend/config.js` to that host.
5. **Only then**: drop the `!` exceptions, add `*.mp4` etc. to `.gitignore`, add
   `clips/` to `.vercelignore`, and wire `check_no_video.sh` into `buildCommand`.

Doing 5 before 4 takes the site down. Order matters.

### 2. Git history still holds the 57 usernames

The working tree is clean and every future scrape hashes at source, but
`git log -p comments/` still shows the names, and the repo is on GitHub. Scrubbing that
needs a `git filter-repo` pass over every commit touching `comments/`, which rewrites
every hash on the branch and requires a force-push. Worth doing before the repo is ever
made public; not worth doing silently.

The same is true of the clips: removing them from the tree will not remove them from
history.

### 3. `created_utc` is not stored on comment records

The spec lists it. The pool carries `id`, `url`, `score`, `text` and the derived labels
but no timestamp, and adding one means re-scraping — Bright Data spend, and a re-scrape
can return a *worse* pool, which the zero-rows guard does not catch. Left as-is
deliberately; it is the least consequential item on this page.

### 4. Contact addresses and the domain are aspirational

`abuse@gameover.fyi` is written into the pages, the README and this file, but the domain
is not registered and the mailbox does not exist. **A takedown route that bounces is
worse than none**, so this is the one item to close before anything is shared publicly —
ahead of the clip migration, because it is cheap and it is what the outreach sequencing
depends on.

## The honest summary

Every rule that could be satisfied by code is satisfied. What remains needs an account,
a domain, or a history rewrite — decisions with money or irreversibility attached, which
is the right place for an implementation pass to stop.

Two of the four are blockers for going public, in this order:

1. **Register the domain and the mailbox.** Cheap, fast, and everything else assumes it.
2. **Move the clips to R2.** The rest of the work for this is already done.
3. Scrub git history, if the repo is ever to be public.
4. `created_utc`, if a re-scrape happens anyway for another reason.

None of this is legal advice, and the note above the line applies to the audit as much
as to the checklist: ticking every box leaves the core exposure from self-hosting the
footage exactly where it was.
