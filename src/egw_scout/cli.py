"""Typer CLI with Rich terminal output for EGW Scout."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from egw_scout.models import MatchDetail
from egw_scout.scraper import AccessBlockedError
from egw_scout.scraper import DetailedScrapedPage
from egw_scout.scraper import EgamersWorldScraper
from egw_scout.scraper import PageMetadata
from egw_scout.scraper import ScrapedPage

app = typer.Typer(
    help="Scrape EGamersWorld esports data and show readable terminal output.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def scrape(
    path: Annotated[
        str,
        typer.Argument(help="EGamersWorld path or full URL to scrape."),
    ] = "/matches/upcoming-matches",
    limit: Annotated[
        int | None,
        typer.Option("--limit", "-n", min=1, help="Limit listing matches or detail pages."),
    ] = None,
    details: Annotated[
        bool,
        typer.Option("--details", "-d", help="Fetch each match detail page from a listing page."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print raw JSON instead of Rich tables."),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable debug logging, including per-query timings."),
    ] = False,
) -> None:
    """Scrape a listing or match page."""
    _configure_logging(verbose)
    try:
        with EgamersWorldScraper() as scraper:
            if details and _looks_like_match_path(path):
                result: ScrapedPage | DetailedScrapedPage | MatchDetail = scraper.scrape_match_detail(path)
            elif details:
                result = scraper.scrape_page_with_details(path, limit=limit)
            else:
                page = scraper.scrape(path)
                result = page.model_copy(update={"matches": page.matches[:limit]}) if limit is not None else page
    except AccessBlockedError as exc:
        _print_access_blocked(exc)
        raise typer.Exit(2) from exc

    if json_output:
        console.print_json(result.model_dump_json())
        return

    if isinstance(result, DetailedScrapedPage):
        _print_detailed_page(result)
    elif isinstance(result, ScrapedPage):
        _print_scraped_page(result)
    else:
        _print_match_detail(result)


@app.callback()
def main() -> None:
    """EGW Scout command line interface."""


def _print_scraped_page(page: ScrapedPage) -> None:
    _print_metadata(page.metadata)
    table = Table(title=f"Matches ({len(page.matches)})", show_lines=False)
    table.add_column("#", justify="right", style="dim")
    table.add_column("Match", style="bold")
    table.add_column("Game")
    table.add_column("Status")
    table.add_column("Starts")
    table.add_column("Tournament")
    table.add_column("URL", overflow="fold")

    for index, match in enumerate(page.matches, start=1):
        table.add_row(
            str(index),
            match.title,
            match.game.value,
            match.status.value,
            _format_datetime(match.starts_at),
            match.tournament.name if match.tournament else "-",
            str(match.url or "-"),
        )

    console.print(table)
    if page.interesting_links:
        console.print(f"[dim]Interesting links discovered: {len(page.interesting_links)}[/dim]")


def _print_detailed_page(page: DetailedScrapedPage) -> None:
    _print_metadata(page.metadata)
    table = Table(title=f"Match details ({len(page.match_details)})", show_lines=True)
    table.add_column("#", justify="right", style="dim")
    table.add_column("Match", style="bold")
    table.add_column("Status")
    table.add_column("Starts")
    table.add_column("Odds")
    table.add_column("Lineups")
    table.add_column("Source URL", overflow="fold")

    for index, detail in enumerate(page.match_details, start=1):
        table.add_row(
            str(index),
            detail.match.title,
            detail.match.status.value,
            _format_datetime(detail.match.starts_at),
            _format_odds(detail),
            _format_lineups(detail),
            str(detail.source_url),
        )

    console.print(table)


def _print_match_detail(detail: MatchDetail) -> None:
    match = detail.match
    console.print(
        Panel.fit(
            Text(match.title, style="bold cyan"),
            title="Match detail",
            subtitle=str(detail.source_url),
        )
    )

    table = Table(show_header=False)
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Game", match.game.value)
    table.add_row("Status", match.status.value)
    table.add_row("Starts", _format_datetime(match.starts_at))
    table.add_row("Best of", str(match.best_of))
    table.add_row("Tournament", match.tournament.name if match.tournament else "-")
    table.add_row("Teams", f"{match.home.team.name} vs {match.away.team.name}")
    table.add_row("Odds", _format_odds(detail))
    table.add_row("Lineups", _format_lineups(detail))
    if detail.about:
        table.add_row("About", detail.about)
    console.print(table)


def _print_metadata(metadata: PageMetadata) -> None:
    console.print(
        Panel(
            f"[bold]Scraped page[/bold]: {metadata.url}\n"
            f"[bold]Title[/bold]: {metadata.title or '-'}\n"
            f"[bold]Canonical[/bold]: {metadata.canonical_url or '-'}",
            title="EGW Scout",
            border_style="cyan",
        )
    )


def _configure_logging(verbose: bool) -> None:
    if not verbose:
        return
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s:%(name)s:%(message)s", force=True)


def _print_access_blocked(exc: AccessBlockedError) -> None:
    console.print(
        Panel(
            "EGamersWorld returned an access challenge.\n\n"
            f"URL: {exc.url}\n"
            f"Status: {exc.status_code}\n"
            f"Reason: {exc.reason}",
            title="Access blocked",
            border_style="red",
        )
    )


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.isoformat()


def _format_odds(detail: MatchDetail) -> str:
    if not detail.odds:
        return "-"
    return ", ".join(f"{odd.side.value}: {odd.value:g}" for odd in detail.odds)


def _format_lineups(detail: MatchDetail) -> str:
    if not detail.lineups:
        return "-"
    return ", ".join(f"{lineup.team.name}: {len(lineup.players)}" for lineup in detail.lineups)


def _looks_like_match_path(path_or_url: str) -> bool:
    return "/match/" in path_or_url


if __name__ == "__main__":
    app()
