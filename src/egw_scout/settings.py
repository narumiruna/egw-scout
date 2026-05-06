"""Application settings loaded from YAML, environment variables, and init kwargs."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings
from pydantic_settings import PydanticBaseSettingsSource
from pydantic_settings import SettingsConfigDict
from pydantic_settings import YamlConfigSettingsSource


class DatabaseSettings(BaseSettings):
    """Database connection settings."""

    url: str = "sqlite:///data/egw_scout.sqlite3"
    echo: bool = False


class ScraperSettings(BaseSettings):
    """HTTP scraper settings."""

    base_url: str = "https://egamersworld.com/"
    timeout_seconds: float = Field(default=20.0, gt=0)
    user_agent: str = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
    accept_language: str = "en-US,en;q=0.9"
    request_delay_seconds: float = Field(default=2.0, ge=0)
    request_jitter_seconds: float = Field(default=1.0, ge=0)
    max_details_per_run: int = Field(default=50, ge=1)


class SchedulerSettings(BaseSettings):
    """Periodic crawl policy settings."""

    upcoming_interval_minutes: int = Field(default=20, ge=1)
    history_interval_minutes: int = Field(default=60, ge=1)
    live_interval_minutes: int = Field(default=3, ge=1)


class AppSettings(BaseSettings):
    """Top-level application settings.

    Loading priority, highest first:

    1. Explicit init kwargs
    2. Environment variables, e.g. `EGW_DATABASE__URL=sqlite:///...`
    3. `.env`
    4. YAML files: `config.yaml`, then `config.local.yaml`
    5. Model defaults
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        env_prefix="EGW_",
        extra="ignore",
        yaml_file=("config.yaml", "config.local.yaml"),
        yaml_file_encoding="utf-8",
    )

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    scraper: ScraperSettings = Field(default_factory=ScraperSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Add YAML as the default file-based configuration source."""
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls, deep_merge=True),
            file_secret_settings,
        )


def load_settings() -> AppSettings:
    """Load application settings from configured sources."""
    return AppSettings()
