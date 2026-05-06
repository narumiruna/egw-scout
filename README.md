# EGW Scout

## Objectives

- Parse important esports information from https://egamersworld.com/.

## Quick terminal example

Run this command to scrape the EGamersWorld upcoming matches page and print the parsed result as JSON in your terminal:

```bash
uv run python -m egw_scout.scraper /matches/upcoming-matches --limit 3
```

This command crawls this page:

```text
https://egamersworld.com/matches/upcoming-matches
```

You can open that URL in your browser and compare it with the terminal output.

If you also want to fetch each match detail page for the first 2 matches, run:

```bash
uv run python -m egw_scout.scraper /matches/upcoming-matches --details --limit 2
```

The output includes each match's `source_url`, so you can open the exact detail page that was parsed.
