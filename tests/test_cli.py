from typer.testing import CliRunner

from egw_scout.cli import app

runner = CliRunner()


def test_cli_help_uses_typer_app() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Scrape EGamersWorld esports data" in result.stdout
    assert "scrape" in result.stdout


def test_scrape_command_help_shows_typer_options() -> None:
    result = runner.invoke(app, ["scrape", "--help"])

    assert result.exit_code == 0
    assert "EGamersWorld path or full URL to scrape" in result.stdout
    assert "--details" in result.stdout
    assert "--json" in result.stdout
