# EGamersWorld Scraper Plan

## 1. Goal

Build a reliable data pipeline that periodically fetches esports information from EGamersWorld and stores structured match data for downstream use.

Primary target data:

- Upcoming matches
- Match detail pages
- Finished match results
- Teams
- Players / lineups
- Tournaments / events
- Streams
- Odds snapshots
- Head-to-head summaries

The system should be able to run continuously, detect new or changed information, and keep a local historical record.

---

## 2. Current State

Implemented prototype:

- `pydantic` models for match-related data
- Listing page scraper for `/matches/upcoming-matches`
- Match detail scraper
- CLI entrypoint:

```bash
uv run egw-scout scrape /matches/upcoming-matches --details --limit 2
```

Currently extracted:

- Match id / URL / title
- Game
- Status
- Start time
- Best-of format
- Tournament
- Home / away teams
- Team URLs, IDs, flags, logos
- Odds
- Streams
- Lineups
- Head-to-head summary
- About text

Limitations:

- No persistent storage yet
- No scheduler yet
- No retry/backoff policy yet
- No deduplication beyond in-memory IDs
- No change tracking or historical snapshots
- No rate limiting beyond manual `--limit`
- Cloudflare can still block requests depending on environment and frequency

---

## 3. Recommended Architecture

```text
             ┌────────────────────┐
             │ Scheduler / Cron    │
             │ APScheduler / cron  │
             └─────────┬──────────┘
                       │
                       ▼
             ┌────────────────────┐
             │ Crawl Orchestrator  │
             │ chooses pages/jobs  │
             └─────────┬──────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ List Scraper │ │Detail Scraper│ │ Result Sync  │
│ upcoming     │ │ match pages  │ │ history page │
└──────┬───────┘ └──────┬───────┘ └──────┬───────┘
       │                │                │
       ▼                ▼                ▼
┌──────────────────────────────────────────────┐
│ Parser + Pydantic Validation                  │
└──────────────────────┬───────────────────────┘
                       ▼
┌──────────────────────────────────────────────┐
│ Storage Layer                                 │
│ PostgreSQL or SQLite first                    │
└──────────────────────┬───────────────────────┘
                       ▼
┌──────────────────────────────────────────────┐
│ Query / Export / API                          │
│ JSONL, CSV, REST API, dashboard, etc.         │
└──────────────────────────────────────────────┘
```

---

## 4. Storage Decision

### Short-term recommendation: SQLite

Use SQLite first because:

- Simple local development
- No external service required
- Good enough for one scraper process
- Easy to inspect and backup
- Can be migrated later

Recommended SQLite usage:

- WAL mode enabled
- Unique constraints on source IDs and URLs
- Timestamp columns for crawl state
- Store raw HTML optionally for debugging

Good fit while the project is:

- Single-machine
- Single-worker
- Mainly batch scraping
- Not serving many concurrent users

### Medium-term recommendation: PostgreSQL

Move to PostgreSQL when:

- Multiple scraper workers run in parallel
- Data volume grows significantly
- You need concurrent writes and reads
- You build an API/dashboard
- You want better JSON querying and indexing

Recommended PostgreSQL features:

- `JSONB` for raw payload snapshots
- `UPSERT` for match/team/tournament updates
- Partial indexes for upcoming/live matches
- Time-series-like table for odds snapshots

### Should we use Redis?

Not required at first.

Add Redis only when we need one or more of these:

- Distributed job queue
- Rate-limit coordination across workers
- Short-lived URL crawl cache
- Locking to avoid duplicate crawls
- Fast pub/sub notifications

For a first production-ish version, prefer:

- SQLite/PostgreSQL for durable state
- Simple scheduler
- No Redis

Later Redis could be useful with:

- RQ / Celery / Dramatiq workers
- Distributed scraping
- Per-domain token bucket rate limiting

---

## 5. Proposed Database Schema

Initial tables:

### `crawl_runs`

Tracks each scheduled run.

Fields:

- `id`
- `started_at`
- `finished_at`
- `status`
- `source_url`
- `matches_found`
- `details_fetched`
- `error_message`

### `matches`

Current known state of each match.

Fields:

- `id`
- `source_id`
- `source_url`
- `title`
- `game`
- `status`
- `starts_at`
- `best_of`
- `tournament_id`
- `home_team_id`
- `away_team_id`
- `home_score`
- `away_score`
- `winner_side`
- `created_at`
- `updated_at`
- `last_seen_at`

Unique constraints:

- `source_url`
- optionally `source_id`

### `teams`

Fields:

- `id`
- `source_id`
- `source_url`
- `name`
- `country`
- `logo_url`
- `created_at`
- `updated_at`

### `players`

Fields:

- `id`
- `source_id`
- `source_url`
- `name`
- `country`
- `photo_url`
- `created_at`
- `updated_at`

### `tournaments`

Fields:

- `id`
- `source_id`
- `source_url`
- `name`
- `tier`
- `prize_pool`
- `starts_at`
- `ends_at`
- `created_at`
- `updated_at`

### `match_lineups`

Fields:

- `match_id`
- `team_id`
- `player_id`
- `side`
- `observed_at`

### `streams`

Fields:

- `id`
- `match_id`
- `platform`
- `url`
- `language`
- `viewers`
- `observed_at`

### `odds_snapshots`

Odds change over time, so store snapshots instead of only current values.

Fields:

- `id`
- `match_id`
- `side`
- `value`
- `bookmaker`
- `observed_at`

### `raw_pages` optional

Useful for debugging parser regressions.

Fields:

- `id`
- `url`
- `status_code`
- `html_hash`
- `html`
- `fetched_at`

This can grow quickly, so keep only recent pages or store compressed content.

---

## 6. Periodic Fetch Strategy

Recommended crawl frequencies:

### Upcoming matches listing

Fetch every 10-30 minutes.

Reason:

- New matches can appear
- Start times can change
- Odds can change

### Match detail pages for upcoming matches

Fetch based on start time:

- More than 7 days away: every 12 hours
- 1-7 days away: every 3-6 hours
- Within 24 hours: every 30-60 minutes
- Within 2 hours: every 10-15 minutes
- Live matches: every 1-5 minutes, if live pages expose scores
- Finished matches: fetch once after completion, then maybe once again after 1-2 hours for corrections

### Historical results

Fetch `/matches/history` periodically:

- Every 1-6 hours
- More frequently if live/result accuracy matters

---

## 7. Job Model

Use durable crawl jobs eventually.

Possible job types:

- `fetch_listing`
- `fetch_match_detail`
- `fetch_match_history`
- `refresh_tournament`
- `refresh_team`

Job fields:

- `id`
- `type`
- `url`
- `priority`
- `status`
- `scheduled_at`
- `started_at`
- `finished_at`
- `attempts`
- `last_error`

Initial implementation can be simple:

- Scheduler calls Python functions directly
- DB stores crawl state
- Failed URLs are retried with backoff

Later implementation:

- Redis + RQ/Celery/Dramatiq
- Multiple workers
- Distributed rate limits

---

## 8. Rate Limiting and Politeness

Important because the website uses Cloudflare.

Recommended rules:

- Start with one process and low concurrency
- Add random jitter between requests
- Respect retry-after headers when present
- Back off on 403, 429, 503, Cloudflare challenge pages
- Avoid crawling all 496+ detail pages too frequently
- Cache unchanged pages using hashes
- Prefer targeted recrawls based on match start time

Initial defaults:

```text
listing pages: 1 request every 10-30 minutes
detail pages: 1 request every 2-5 seconds while batch crawling
max detail pages per run: configurable, e.g. 50
```

Do not bypass access controls. If Cloudflare blocks the scraper, record the event and retry later with lower frequency.

---

## 9. Change Detection

Every parsed record should be upserted.

Track changes for:

- Match status
- Start time
- Teams
- Tournament
- Odds
- Lineups
- Scores
- Streams

Recommended strategy:

1. Parse page into Pydantic model.
2. Normalize into DB rows.
3. Compute a stable hash of important fields.
4. If hash differs from previous hash:
   - update current table
   - optionally insert into `match_change_events`

Possible `match_change_events` table:

- `id`
- `match_id`
- `field`
- `old_value`
- `new_value`
- `observed_at`

This is useful for alerts and audits.

---

## 10. Implementation Roadmap

### Phase 1: Local persistence

- Add SQLite database
- Add repository/storage layer
- Save listing matches
- Save match detail records
- Add `crawl_runs`
- Add CLI commands:

```bash
egw scrape-listing /matches/upcoming-matches
egw scrape-detail <match-url>
egw scrape-with-details /matches/upcoming-matches --limit 50
```

### Phase 2: Scheduler

Options:

- Simple cron invoking CLI
- `APScheduler` inside Python
- systemd timer on Linux

Recommended first choice:

- cron or systemd timer for simplicity

Example cron-style schedule:

```text
*/20 * * * * uv run egw-scout scrape /matches/upcoming-matches --details --limit 50
```

Better version after DB scheduling:

```text
*/10 * * * * uv run egw schedule-due-jobs
* * * * * uv run egw run-next-job --max-jobs 5
```

### Phase 3: Smarter recrawl policy

- Prioritize matches starting soon
- Skip stable future matches
- Refetch live/recently-finished matches more often
- Persist failed fetches and retry with backoff

### Phase 4: Historical results

- Parse `/matches/history`
- Update finished scores
- Store map-level scores if available
- Detect completed matches

### Phase 5: API / export

Possible outputs:

- JSONL export
- CSV export
- FastAPI read API
- Small dashboard

### Phase 6: Scale-out only if needed

Add PostgreSQL if SQLite becomes limiting.

Add Redis + workers only if:

- The scraper needs parallelism
- Multiple machines are used
- Job queue durability and retries become complex

---

## 11. Suggested Technology Choices

### Keep now

- Python 3.14
- uv
- Pydantic
- httpx
- BeautifulSoup
- pytest / ruff / ty

### Add next

- SQLite
- SQLModel or SQLAlchemy
- Typer for CLI commands
- APScheduler only if not using cron/systemd

### Maybe later

- PostgreSQL
- Redis
- RQ / Celery / Dramatiq
- FastAPI
- Docker Compose

Recommended near-term stack:

```text
Python + httpx + BeautifulSoup + Pydantic
SQLite + SQLAlchemy
Typer CLI
cron/systemd timer
```

Recommended later stack:

```text
Python workers
PostgreSQL
Redis queue
FastAPI dashboard/API
```

---

## 12. Open Questions

1. What is the final consumer of the data?
   - Local files?
   - Database queries?
   - API?
   - Dashboard?
   - Betting/analytics model?

2. How fresh must the data be?
   - 1 minute?
   - 15 minutes?
   - Hourly?

3. Which games matter most?
   - All games?
   - Dota 2 / CS2 / Valorant only?

4. Do we need odds history?
   - Current odds only is simpler.
   - Historical odds requires snapshots.

5. Do we need live scores?
   - Live score scraping needs much more frequent refresh and careful rate limiting.

6. How long should raw HTML be retained?
   - None
   - Recent 7 days
   - Only failed parses
   - Full archive

---

## 13. Immediate Next Steps

Recommended next implementation tasks:

1. Add a SQLite storage layer.
2. Add `scrape_with_details` command that persists results.
3. Add a `crawl_runs` table.
4. Add configurable rate limit and jitter.
5. Add systemd timer or cron example.
6. Add result/history page parser.
7. Add score parsing for finished matches.

The first production-like milestone should be:

```text
A scheduled command runs every 20 minutes, fetches upcoming matches,
fetches details for matches starting soon, and upserts everything into SQLite.
```
