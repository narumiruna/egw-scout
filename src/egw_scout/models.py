"""Pydantic models for EGamersWorld esports data."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import HttpUrl
from pydantic import field_validator
from pydantic import model_validator


class EsportGame(StrEnum):
    """Supported esports titles."""

    CS2 = "cs2"
    DOTA2 = "dota2"
    LEAGUE_OF_LEGENDS = "league_of_legends"
    VALORANT = "valorant"
    ROCKET_LEAGUE = "rocket_league"
    RAINBOW_SIX = "rainbow_six"
    CALL_OF_DUTY = "call_of_duty"
    OTHER = "other"


class MatchStatus(StrEnum):
    """Lifecycle state for a match."""

    SCHEDULED = "scheduled"
    LIVE = "live"
    FINISHED = "finished"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"


class TeamSide(StrEnum):
    """A team's side within a match."""

    HOME = "home"
    AWAY = "away"


class BaseSchema(BaseModel):
    """Shared configuration for all API/data schemas."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class Team(BaseSchema):
    """Esports team information."""

    id: str | None = Field(default=None, description="Provider-specific team id.")
    name: str = Field(min_length=1, description="Display name of the team.")
    country: str | None = Field(default=None, min_length=2, max_length=2)
    logo_url: HttpUrl | None = None
    url: HttpUrl | None = None


class Player(BaseSchema):
    """Player information shown on match detail pages."""

    id: str | None = Field(default=None, description="Provider-specific player id.")
    name: str = Field(min_length=1)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    photo_url: HttpUrl | None = None
    url: HttpUrl | None = None


class Tournament(BaseSchema):
    """Tournament or event containing matches."""

    id: str | None = Field(default=None, description="Provider-specific tournament id.")
    name: str = Field(min_length=1)
    url: HttpUrl | None = None
    tier: str | None = Field(default=None, description="Tier label, e.g. S-Tier or A-Tier.")
    prize_pool: str | None = Field(default=None, description="Human-readable prize pool text.")
    starts_at: datetime | None = None
    ends_at: datetime | None = None

    @model_validator(mode="after")
    def validate_date_range(self) -> Tournament:
        """Ensure the tournament end is not before the start."""
        if self.starts_at and self.ends_at and self.ends_at < self.starts_at:
            raise ValueError("tournament ends_at must be greater than or equal to starts_at")
        return self


class MatchParticipant(BaseSchema):
    """Team entry within a match."""

    team: Team
    side: TeamSide
    seed: int | None = Field(default=None, ge=1)


class MapScore(BaseSchema):
    """Score for one game/map in a series."""

    order: int = Field(ge=1, description="Map/game number in the series.")
    name: str | None = Field(default=None, description="Map name, if applicable.")
    home_score: int = Field(ge=0)
    away_score: int = Field(ge=0)
    winner: TeamSide | None = None


class MatchScore(BaseSchema):
    """Series-level score information."""

    home_score: int = Field(default=0, ge=0)
    away_score: int = Field(default=0, ge=0)
    maps: tuple[MapScore, ...] = Field(default_factory=tuple)
    winner: TeamSide | None = None


class Stream(BaseSchema):
    """Official or community stream for a match."""

    platform: str = Field(min_length=1, examples=["twitch", "youtube"])
    url: HttpUrl | None = None
    language: str | None = Field(default=None, min_length=2, max_length=8)
    viewers: str | None = Field(default=None, description="Human-readable viewer count, e.g. 2.6K.")


class BettingOdd(BaseSchema):
    """Bookmaker odds shown for a team in a match."""

    side: TeamSide
    value: float = Field(gt=0)


class TeamLineup(BaseSchema):
    """A team's players on a match detail page."""

    team: Team
    side: TeamSide
    players: tuple[Player, ...] = Field(default_factory=tuple)


class HeadToHeadSummary(BaseSchema):
    """Summary of historical meetings between two teams."""

    home_wins: int = Field(default=0, ge=0)
    away_wins: int = Field(default=0, ge=0)
    note: str | None = None


class MatchInfo(BaseSchema):
    """Core match information scraped from or mapped to EGamersWorld-like pages."""

    id: str = Field(min_length=1, description="Provider-specific match id.")
    title: str = Field(min_length=1, description="Human-readable match title.")
    url: HttpUrl | None = Field(default=None, description="Canonical match page URL.")
    game: EsportGame
    status: MatchStatus
    starts_at: datetime | None = Field(default=None, description="Scheduled match start time.")
    best_of: int = Field(default=1, ge=1, le=7, description="Series format, e.g. BO1/BO3/BO5.")
    tournament: Tournament | None = None
    home: MatchParticipant
    away: MatchParticipant
    score: MatchScore | None = None
    streams: tuple[Stream, ...] = Field(default_factory=tuple)
    updated_at: datetime | None = Field(default=None, description="Last time this record was updated.")

    @field_validator("best_of")
    @classmethod
    def best_of_must_be_odd(cls, value: int) -> int:
        """Most esports series are best-of odd numbers."""
        if value % 2 == 0:
            raise ValueError("best_of must be an odd number")
        return value

    @model_validator(mode="after")
    def validate_match(self) -> MatchInfo:
        """Validate match participant and score consistency."""
        if self.home.side != TeamSide.HOME:
            raise ValueError("home participant side must be 'home'")
        if self.away.side != TeamSide.AWAY:
            raise ValueError("away participant side must be 'away'")

        home_key = self.home.team.id or self.home.team.name.casefold()
        away_key = self.away.team.id or self.away.team.name.casefold()
        if home_key == away_key:
            raise ValueError("home and away teams must be different")

        if self.status == MatchStatus.FINISHED and self.score is None:
            raise ValueError("finished matches must include score")

        return self


class MatchDetail(BaseSchema):
    """Detailed information from a single match page."""

    source_url: HttpUrl
    match: MatchInfo
    odds: tuple[BettingOdd, ...] = Field(default_factory=tuple)
    lineups: tuple[TeamLineup, ...] = Field(default_factory=tuple)
    head_to_head: HeadToHeadSummary | None = None
    about: str | None = None


__all__ = [
    "BaseSchema",
    "BettingOdd",
    "EsportGame",
    "HeadToHeadSummary",
    "MapScore",
    "MatchDetail",
    "MatchInfo",
    "MatchParticipant",
    "MatchScore",
    "MatchStatus",
    "Player",
    "Stream",
    "Team",
    "TeamLineup",
    "TeamSide",
    "Tournament",
]
