# yt-trend-radar

Category-level YouTube trend discovery — surfacing what's **hot now** and what's **breaking out**,
for videos and creators alike.

[한국어](README.md)

---

## Why

YouTube **retired the Trending page in July 2025**. The Data API's
`videos.list(chart=mostPopular)` now returns only the Music / Movies / Gaming charts.

An actual response (region KR, 2026-07-30):

```
[10] Shut The Door                       — Music
[1]  Avengers: Doomsday comic-con leak   — Film
[20] League of Legends match highlight   — Gaming
```

So **there is no API path to "food" or "travel" trends.** They have to be computed.
That constraint is this project's premise and its differentiator.

## How the score works

A **normalized velocity** over a snapshot time series:

```
score = Δvalue / (Δhours × max(subscribers, floor) ** α)
```

A single knob, α, produces two boards with genuinely different characters:

| Board | α | Meaning |
|-------|---|---------|
| **Hot now** | 0.25 | Absolute growth dominates; large channels get only a mild handicap |
| **Breaking out** | **1.00** | Growth per subscriber — size-neutral, so small channels that overperform rise |

> **α ≥ 1.0 is an invariant.** When Δ scales with subscriber count,
> `score ∝ subscribers^(1-α)`. With α < 1 the exponent stays positive, so the
> "breaking out" board collapses back into a subscriber ranking — which is exactly what
> happened when it was demoed at α = 0.7. Only at α = 1.0 does "performance relative to
> size" actually hold. The code **raises at construction time** for a rising config with
> α < 1: a silent degradation here is invisible to everyone.

**Δtime is measured, never assumed.** GitHub Actions cron drifts; assuming a fixed 8-hour
interval would inflate or flatten velocity whenever a run is late.

## Quota strategy

The YouTube Data API allows 10,000 units/day with no option to buy more, and
`search.list` costs 100 units — 100× a batched lookup. So the collection path avoids it entirely.

| Purpose | Method | Cost | Measured (90 channels) |
|---------|--------|------|------------------------|
| Detect new videos | **Channel RSS feed** | **0 u** | 90 requests |
| Video statistics | `videos.list`, batches of 50 | 1 u / 50 | 479 videos → 10 u |
| Channel statistics | `channels.list`, batches of 50 | 1 u / 50 | 2 u |
| Channel discovery | `search.list` (budgeted) | 100 u / call | excluded from collection |

**One collection run costs 12 units.** Three runs a day is 36 u — 0.4% of the daily budget.

Visitor traffic is decoupled from quota entirely: the web tier reads only our own database.

```
[cron collector] --36u/day--> YouTube API
       ↓ writes snapshots
   [Supabase] --compute--> ranking table
       ↓ read-only
     [web]  ← 10 visitors or 100k, quota cost is zero
```

## Layout

```
collector/            collection & scoring (Python, minimal dependencies)
  core/               models · config · db · quota
  sources/            yt_client · rss_watcher   (each has harness + live impls)
  engine/             classifier · trend_engine
  jobs/               collect · compute · purge · bootstrap_seeds · refill_seeds
  tests/              243 tests, no external calls
config/               categories.yaml (taxonomy & discovery queries) · seeds.yaml
db/migrations/        schema · RLS grants · publish RPC
tools/                report generators · verification scripts
docs/                 SPEC · PLAN · DESIGN · TASK  ← source of truth
```

## How it's built

- **Spec-driven.** `docs/` holds SPEC → PLAN → DESIGN → TASK, updated in the same turn as
  the code. Where code and docs disagree, **the docs win**.
- **Test-first.** Tests precede implementation. The default gate runs with **zero external
  calls** (`YT_MODE=harness`); tests hitting the real API are isolated behind
  `@pytest.mark.live`.
- **Harness-first.** Every external dependency ships with a harness implementation.

```bash
cd collector
python -m pytest            # 243 passed — no network
python -m pytest -m live    # real YouTube API / RSS (spends a little quota)
```

## Running it

```bash
cp .env.example .env        # fill in keys
cd collector && pip install -r requirements.txt

python -m jobs.sync_config          # taxonomy → DB
python -m jobs.collect              # collect (12u)
python -m jobs.compute              # score → publish rankings
python -m jobs.purge                # enforce 30-day retention

python ../tools/verify_seeds.py     # seed quality via RSS (0 quota)
python ../tools/gen_admin.py        # build the ops console
```

Adding a category means editing `config/categories.yaml` — **no code change** — then:

```bash
python -m jobs.refill_seeds --only <category_id>   # discover for that category only (700u)
```

Omitting `--only` re-discovers every category and burns quota needlessly.

## Data handling (YouTube API ToS)

- **30-day retention**: collected data is refreshed or deleted within 30 days
  (`jobs/purge`, run after every collection).
- **Artifacts containing video titles are never committed** — git history survives deletion.
  Review reports upload as Actions artifacts and expire on their own.
- Playback always **links out to YouTube**; nothing is embedded or re-hosted.
- Ranking scores are **our own metric**, not an official YouTube signal, and the UI says so.
- No personal data is collected — only public channel metadata and public video statistics.

## Security

- Secrets live in `.env` (local) and GitHub Secrets (CI). They never enter the repository.
- The web tier reaches the database through a **read-only key plus RLS**; the write-capable
  key exists only server-side.
- A security review is a required gate before any push or deploy (secrets, dependency
  advisories, RLS, API politeness). The latest review is recorded in `docs/TASK.md`.

## Status

Cold-start collection is under way. Velocity needs at least two snapshots per target, so
boards stay thin for the first few days — expected behaviour, and the ops console says as much.

Progress lives in `docs/TASK.md` and `docs/progress.html`.
