# GAMEOVER — submission copy

Live: https://gameover.fyi · Repo: https://github.com/soycarts/gameover

Not served publicly — this file is in `.vercelignore`.

---

## Short version (~90 words, for a tagline field)

GAMEOVER turns real robot-combat footage into a playable-looking arcade fighting game.
A vision model watches the fight frame by frame and rates damage; deterministic code
turns those ratings into health bars, hit markers, damage numbers and a knockout
sequence synced to video time. Bright Data supplies the second half: real
r/battlebots comments, pulled from two Reddit datasets, filtered and routed in Python,
then fired at the exact moment of the blow they are reacting to — including a
pre-fight prediction split showing what the crowd got wrong.

---

## Full version — "What does your project do? How does it use Bright Data tools or data?"

**What it does**

GAMEOVER watches a real robot-combat clip and renders it as an arcade fighting game.
Health bars drain, hit markers land where contact happened, damage numbers pop, the
screen shakes on heavy blows, and the fight ends on a K.O. stamp and a full match
breakdown. None of it is scripted — every number on screen is derived from the footage.

A vision model is shown the fight at 2fps in ~3-second batches and asked one question
per bot per frame: how bad was that — none, glance, solid, heavy, or catastrophic. It
never emits a health value. Deterministic Python converts those ratings into the bar,
detects the knockout, and bleeds the loser's remaining health across the referee count
rather than inventing a finishing blow. Two independent halves — a Python pipeline and
a single no-build HTML page — are joined by one JSON contract, so the same frames
always produce the same fight.

That gets you accurate. It does not get you *alive*. A fight is something people watch
together and argue about, and that is the half Bright Data provides.

**How it uses Bright Data**

Every comment in the HUD comes through Bright Data, using two Reddit datasets for two
genuinely different jobs.

*1. The pinned pre-fight thread (Reddit — Comments dataset).* Each clip is pinned to
its episode's r/battlebots fight-card thread, expanded into real threaded comments.
This is the primary source, and the reason is the most important design decision in the
project. Predictions are the most interesting thing a crowd produces — the only comments
where the audience is wrong on record — and they live in the pre-fight card thread.
Pinning is what makes reaching them **reliable**: the pinned pull returns 14, 15 and 8
pre-fight comments on our three clips, every run. Discovery can reach pre-fight comments
too (it contributed 11, 7 and 1), but it is a lottery — a keyword run for "mad catter
tombstone" returned 14 rows of "Season 7 Rumor Mill" and 8 from a two-year-old SawBlaze
fight, and nothing from the episode. The pre-fight CROWD CALL panel ("As much as
Skorpios is my goat, Manta is going to kick their ass" against "Skorpios over manta is
some serious copium", split 10–4) is dependable because of the pinned pull, not lucky.

*2. Discovery (Reddit — Posts, discover_by=subreddit_url).* The secondary pool, which
is mostly post-fight reaction. Scoped to the subreddit rather than keyword search:
a keyword run for "battlebots tombstone witch doctor" returned 40 rows from r/tifu,
r/movies and r/politics, matching on "doctor" and "fight". Scoping to r/battlebots and
passing bot names as the keyword is what makes results on-topic. Discovery is wrapped
so a timeout on it can never cost the pinned pull.

The structure of the returned data is what makes the best feature possible. Replies come
back nested inside each row under a different schema (reply_id / user_replying / reply /
date_of_reply) rather than as flat rows with parent ids. Flattening those preserves
real parent/child links — which is how the HUD replays actual two-person arguments as
timed exchanges during the fight. Without the nesting the thread looks flat and that
feature cannot exist.

Everything after the scrape is deterministic Python:

- **Routing, not dropping.** One fight-card thread covers three matchups, so a single
  comment often names robots from all of them. A naive length cap and a naive rival
  filter threw away the two best comments in the thread — one was a 600-character
  paragraph-per-matchup prediction, the other named six robots in one sentence. We now
  find the longest span of a comment naming only *this* fight's robots (whole comment,
  else a paragraph, else a run of sentences), changing the unit being filtered rather
  than loosening the filters.
- **Safety gates that never loosen.** Real threads contain explicit language, deleted
  bodies arriving as literal "[deleted]" text, and comments about entirely different
  fights. Two deterministic gates handle it, with the profanity check running on the
  whole body first so a clean sentence can never escape an unusable comment. Filtering
  ~45% of a discovery scrape is normal.
- **Privacy by construction.** No Reddit username is ever written to disk. Usernames
  are salted and truncated at scrape time, and the hasher refuses to run without a salt
  held outside the repository rather than emit a hash reversible by trying a candidate
  list. Records carry an opaque token used only to pair the two halves of an exchange.
  The UI credits r/battlebots.
- **Cost discipline.** Billing is per record, so per-input limits are pinned rather
  than left null, thread expansion is capped, and two flags exist purely to avoid
  re-scraping — one re-runs the prediction labels over a pool already on disk, and one
  backfills timestamps by merging only {comment_id → created_utc} into existing
  records, so a thinner re-scrape cannot damage a good pool. A scrape returning zero
  rows refuses to overwrite an existing file.

**What we'd build next on Bright Data**

- **SERP API to replace the hand-pinned thread.** Three clips currently map to one
  thread by hand — which is exactly the weakness of the design above. Finding the
  episode's fight-card thread automatically from bot names and air date is what turns
  "reliable for three curated fights" into "reliable for any fight", and it is the
  single biggest unlock.
- **YouTube comments as a second crowd.** The adapter already has a YouTube dataset
  slot, deliberately unset. The pipeline ingests any YouTube fight; those videos have
  their own comment threads, and the same fight watched on two platforms gives two
  crowds worth contrasting.
- **Scheduled scrapes for live events.** The pipeline is batch. Polling a live
  discussion thread during a broadcast would let the HUD show the crowd reacting at
  roughly the speed they actually reacted. The pinned/discovery split already models
  before-and-after, so the shape is there.
- **Deterministic phase detection.** We now store created_utc but still classify
  pre/post-fight with a model call. Comparing the real timestamp against air time is
  free, deterministic, and strictly better.

Everything Bright Data-specific lives in one adapter function with the exact request
shapes documented, so the datasets can be swapped without touching the rest of the
pipeline.

---

## Notes for whoever posts this

- Both quotes above are verbatim from the real scraped pool and are in the live demo.
- The 10–4 Manta/Skorpios prediction split is the actual tally in
  `comments/manta-skorpios.json`.
- The pinned-vs-discovery numbers (14/15/8 against 11/7/1) were measured from the
  committed pools, not estimated. Re-check them if the pools are ever re-scraped.
- Do not claim discovery cannot reach pre-fight comments. It can — the argument for
  pinning is yield and reliability. An earlier draft of this got that wrong.
- Do not claim the footage is licensed. The framing throughout is "unaffiliated fan
  project", which is what COMPLIANCE.md commits to.
