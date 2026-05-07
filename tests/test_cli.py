import re

from typer.testing import CliRunner

from egw_scout.cli import app

runner = CliRunner()
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _plain_output(value: str) -> str:
    return ANSI_ESCAPE_RE.sub("", value)


def test_cli_help_uses_typer_app() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Scrape EGamersWorld esports data" in result.stdout
    assert "scrape" in result.stdout


def test_scrape_command_help_shows_typer_options() -> None:
    result = runner.invoke(app, ["scrape", "--help"])
    output = _plain_output(result.stdout)

    assert result.exit_code == 0
    assert "EGamersWorld path or full URL to scrape" in output
    assert "--details" in output
    assert "--json" in output
    assert "--verbose" in output
