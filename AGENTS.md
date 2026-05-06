# Repository Guidelines

## Project Overview

This repository builds a Python scraper and data pipeline for EGamersWorld esports data. It parses listing pages, match detail pages, and persists structured match information for scheduled refreshes.

- `PLAN.md` is the architecture and roadmap document. Read it before making design changes, adding infrastructure, or changing long-term direction.
- `TODOS.md` is the short operational task list. Update it when adding, finishing, or reprioritizing concrete work items.

## Build, Test, and Development Commands

Use `uv` for all Python workflows.

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ty check .
uv run egw-scout scrape /matches/upcoming-matches --limit 3
uv run egw-scout scrape /matches/upcoming-matches --details --limit 2
```

Add dependencies with `uv add`; do not use `pip install` to mutate the environment.

## Code Organization

- `src/egw_scout/models.py`: Pydantic domain models.
- `src/egw_scout/scraper.py`: HTTP fetching and HTML parsing.
- `src/egw_scout/settings.py`: Pydantic Settings and YAML/env config.
- `src/egw_scout/db/`: SQLAlchemy persistence layer.
- `tests/`: pytest tests.

Keep scraper/domain models separate from database ORM models.

## Style and Quality

The project uses Ruff and ty. Keep line length at 120 characters and prefer explicit typed functions. Run the full gate before finalizing changes:

```bash
uv run pytest && uv run ruff check . && uv run ty check .
```

## Testing Guidelines

Use pytest with function-based tests in `tests/test_*.py`. Prefer small HTML fixtures and assert parsed Pydantic models or persisted database rows. For database tests, use in-memory SQLite unless persistence behavior specifically requires a file database.

## Scraping and Configuration Notes

Do not bypass Cloudflare or access controls. Add rate limiting, jitter, and retry/backoff when increasing crawl volume. Configuration should come from `config.yaml`, `config.local.yaml`, environment variables, or explicit settings objects; keep `config.example.yaml` safe to commit.
