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
| No usernames stored or displayed | `crowd.author_hash()` salts and truncates at scrape time; the plaintext never enters a record. `backend/scrub_authors.py` migrated the 57 already committed. The UI credits `r/battlebots` on both render paths. Git history was scrubbed by `filter-repo` and garbage-collected by GitHub — see *Closed*, item 2. |
| Salt held outside the repo | `GAMEOVER_AUTHOR_SALT` in `.env`, which is gitignored *and* vercelignored. `author_hash()` refuses to run without it rather than emitting a reversible hash. |
| noindex / nofollow | On all three pages, plus `googlebot`. |
| `robots.txt` with `Disallow: /` | At the deploy root. No sitemap. **One recorded deviation (2026-08-02):** narrow `Allow: /` blocks for the link-preview crawlers only — `redditbot`, `Twitterbot`, `LinkedInBot`, `facebookexternalhit` (the last also renders Instagram link cards) — because they respect robots.txt and the blanket Disallow blanked the og:image on the launch post — the preview the "Search visibility" section itself permits. The two rules were in direct conflict; this resolves it in favour of the stated goal (discoverable by people you send there). Everything else stays disallowed and every page keeps noindex/nofollow meta. |
| No `og:video`, no structured data | None present. |
| Visible credit line | `#legal`, on every surface — one element inside `#stage`, above every screen, so the title card, the fight and the GAME OVER card cannot drift apart. |
| Link back to the source at its timestamp | `sourceLink()` builds it from `clips/<clip>.source.json`. Prefers `t0` over `start` — the keyframe the cut actually landed on, 1.02s apart on manta. |
| Persistent unaffiliated footer | In `#legal`, hidden only on narrow screens and dimmed during play. |
| `/about` and `/takedown` | Real pages, rewritten in `vercel.json` **and** in `serve.py` so dev matches production. |
| Takedown contact + 24h commitment | `abuse@gameover.fyi`, on both pages and in the README. |
| Kill switch | `scripts/killswitch.sh off` — verified to round-trip and restore the config exactly. It is a rewrite, not an env var; see the script for why a static deploy cannot have one without gaining a build step. |
| `scripts/teardown.sh` | Written. **Never run against a real bucket, because there isn't one yet.** Defaults to `--dry-run`. |
| Single `CLIP_BASE_URL` | `frontend/config.js`, read through `clipUrl()`. Every clip asset — video and `source.json` — resolves through it. |
| No-video build check | `scripts/check_no_video.sh`, wired into `vercel.json` as `buildCommand` and passing. Needs `"outputDirectory": "."` beside it, or `buildCommand` puts Vercel into build mode and it fails the deploy looking for `public/`. |
| Licence covers code only | Note appended to `LICENSE` disclaiming any rights in third-party media or marks. |
| README states the input policy | Says the pipeline expects your own inputs, and states that no video is committed or in git history. |
| Scraper separated from analytics | `ingest.py` / `scrape_comments.py` / `crowd.py` are separate from `analyze.py` and the frontend. |
| Analytics survive a clip takedown | Already true and now load-bearing: `?demo=1` and a missing clip both fall back to the rAF clock, so the HUD, the timeline and the crowd card run with no video at all. |

## Closed

### 1. The clips are off git and off the deployment — done

The four clips live in Cloudflare R2 (`gameover-clips`) behind `clips.gameover.fyi`.
`.gitignore` has no `!` exception for `*.mp4`, `.vercelignore` excludes `clips/`, and
`check_no_video.sh` runs as `buildCommand` — verified: `/clips/*.mp4` returns 404 on the
live site and 206 from R2.

Ran in the mandated order — bucket → upload → `CLIP_BASE` → ignore rules — and the order
really was load-bearing. Notes for anyone moving storage again:

- Uploads were verified by **MD5 against the local files**, not by trusting HTTP 200.
- CORS matters more than it looks. A plain `<video src>` needs none, but `sourceLink()`
  `fetch`es `<clip>.source.json` and **swallows failures**, so a CORS mistake removes the
  attribution link with no error anywhere. The policy names `gameover.fyi`,
  `gameover-nine.vercel.app` and `localhost:40911`; a new origin must be added.
- Wiring `check_no_video.sh` into `buildCommand` **broke the deploy** until
  `"outputDirectory": "."` was added — `buildCommand` switches Vercel out of zero-config
  static mode and it then demands a `public/` directory. Caught on a preview.
- Git is no longer a backup. R2 and local disk are the only copies, plus
  `clips/.raw/` for re-cutting.

**Deviation, recorded rather than resolved:** the bucket is in a personal Cloudflare
account, not one created under a project-specific email as *Required architecture* asks.
Abuse enforcement lands on the account, so this is the live gap in the separation.

### 2. Git history is scrubbed — done

Two `git filter-repo` passes, force-pushed, each verified from a **fresh clone of
GitHub** rather than from the local repo:

- **Usernames** — 37 distinct handles across 9 commits, redacted in place. This also
  caught one the audit had missed: `CLAUDE.md`'s comments-schema example carried a real
  handle in the *working tree*, on a file `.vercelignore` keeps off the site but GitHub
  serves anyway. The example was stale as well as leaky — records carry the opaque `by`
  token — so it was corrected rather than merely masked.
- **Clips** — 6 `.mp4` blobs removed; the repo went 27M → 872K. `.source.json` kept.

Both passes left every file at HEAD byte-identical, and all 88 commits intact.

**A force-push does not delete anything by itself.** Pre-rewrite commits stayed fetchable
by direct SHA — verified, not assumed — until GitHub Support ran garbage collection on
request. That request has been sent and actioned. Anyone who cloned earlier still has
everything; there were 0 forks and 0 PRs, which is the only reason the GC was effective.

### 3. Domain and takedown route are real — done

`gameover.fyi` is registered at Porkbun with DNS on Cloudflare. The apex serves the site
via Vercel (`A 76.76.21.21`, **DNS-only** — proxying it causes redirect loops),
`clips.gameover.fyi` serves the bucket, and `abuse@gameover.fyi` forwards to a monitored
inbox via Cloudflare Email Routing.

Two traps worth recording: adding a site to Cloudflare **imports the registrar's existing
DNS records**, and Porkbun's defaults include a `*` wildcard that pointed
`clips.gameover.fyi` at a parking page and blocked the bucket binding outright — the zone
must be emptied first. And the old parking IP survives in resolver caches long enough to
look like a broken deploy: no cert for the hostname, so TLS fails and the HUD shows
"DEMO ARENA — no clip loaded".

## Does not hold

### 4. `created_utc` — code done, backfill needs one paid scrape

**No longer blocked on a design question.** The Bright Data payload has carried the
timestamp all along — `date_posted` and `timestamp` are both in the dataset's confirmed
key set — and `crowd.enrich()` was simply dropping it. It now stores `created_utc` as an
integer UTC epoch, and **omits the key entirely when there is no date**, so every record
written before this stays byte-identical.

That covers every future scrape. Backfilling the 58 existing records still needs one
Bright Data run, because the raw rows were never kept — but the reason this was deferred
is now gone. The stated risk was that "a re-scrape can return a *worse* pool, which the
zero-rows guard does not catch", and that risk came entirely from the normal path
**replacing** the file. `scrape_comments.py --backfill-dates` does not replace anything:
it scrapes, keeps only `{comment_id -> created_utc}`, and merges that one key into the
records already on disk, matched by `id`. Text, score and the prediction labels are read
off the fresh rows and discarded.

So a thinner, blander or differently-labelled scrape costs nothing — it just contributes
fewer timestamps. No `fan_comment` can be orphaned (no `text` is touched, so unlike a
normal re-scrape it needs no `analyze.py --rejoin` after), the record count is invariant,
and it is idempotent.

Outstanding: the run itself, which is real money.

### 5. The storage account is personal, not project-specific

*Required architecture* asks for an account "created with a project-specific email and
used for nothing else", and *Contacts* asks for the storage account to be registered to
`abuse@gameover.fyi`. The R2 bucket is instead in a personal Cloudflare account that
predates this project. The bucket, the DNS and the mail routing all sit there.

This is the one structural rule on this page that is knowingly unmet. It matters because
enforcement — an abuse complaint, a suspension — attaches to the **account**, not the
bucket, so the blast radius includes everything else in it. Moving it later means a new
account, a new bucket, a re-upload and a DNS change; buckets do not transfer.

### 6. Operational tidy-ups

- ~~The Cloudflare API token has 363 permission groups and no expiry.~~ **Done** —
  narrowed to 6 groups (R2 read/write on the account; DNS, Zone read and Email Routing
  on `gameover.fyi` only) and given a 90-day expiry. Verified after: R2, DNS and email
  routing still work; token and member enumeration are denied and only the one zone is
  visible.
- `scripts/teardown.sh` has a real bucket to point at now but **has still never been run
  against it**. Verify it on a calm day, not the day you need it.

## The honest summary

Every rule that could be satisfied by code is satisfied, and the three that needed an
account, a domain or a history rewrite have now been done: the footage is off git and off
the deployment, the history is scrubbed and garbage-collected, and the takedown route
resolves to a monitored inbox.

What remains is one paid run (`created_utc`, where the code is done and the risk that
deferred it has been designed out), one knowing structural deviation (a personal storage
account), and one untested script (`teardown.sh`).

The caveat this page opened with is unchanged, and none of the above softens it: **none
of this is legal advice, and ticking every box leaves the core exposure from self-hosting
the footage exactly where it was.** What changed is where the bytes are served from, how
fast they can be pulled down — `scripts/teardown.sh` for the bucket,
`scripts/killswitch.sh off` for the UI, and both are needed, since either alone leaves
half the site standing — and that a complainant now has a working address to write to.
