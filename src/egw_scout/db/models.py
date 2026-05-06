"""SQLAlchemy ORM models for persisted scraper data."""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime
from sqlalchemy import Float
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import UniqueConstraint
from sqlalchemy import func
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship


class CrawlRunStatus(StrEnum):
    """Status for a scheduled or manual crawl run."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Base(DeclarativeBase):
    """Base class for ORM mappings."""


class TimestampMixin:
    """Created/updated timestamps shared by mutable rows."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(tz=UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(tz=UTC),
        onupdate=lambda: datetime.now(tz=UTC),
        nullable=False,
    )


class CrawlRunRecord(Base):
    """One execution of the crawler."""

    __tablename__ = "crawl_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=CrawlRunStatus.RUNNING.value, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(tz=UTC),
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    matches_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    details_fetched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)


class TeamRecord(TimestampMixin, Base):
    """Current known team identity."""

    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str | None] = mapped_column(String(255), index=True)
    source_url: Mapped[str | None] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    country: Mapped[str | None] = mapped_column(String(8))
    logo_url: Mapped[str | None] = mapped_column(Text)


class PlayerRecord(TimestampMixin, Base):
    """Current known player identity."""

    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str | None] = mapped_column(String(255), index=True)
    source_url: Mapped[str | None] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    country: Mapped[str | None] = mapped_column(String(8))
    photo_url: Mapped[str | None] = mapped_column(Text)


class TournamentRecord(TimestampMixin, Base):
    """Tournament/event containing matches."""

    __tablename__ = "tournaments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str | None] = mapped_column(String(255), index=True)
    source_url: Mapped[str | None] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    tier: Mapped[str | None] = mapped_column(String(64))
    prize_pool: Mapped[str | None] = mapped_column(String(128))
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MatchRecord(TimestampMixin, Base):
    """Current known match state."""

    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    game: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    best_of: Mapped[int] = mapped_column(Integer, nullable=False)
    tournament_id: Mapped[int | None] = mapped_column(ForeignKey("tournaments.id", ondelete="SET NULL"), index=True)
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False, index=True)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False, index=True)
    home_score: Mapped[int | None] = mapped_column(Integer)
    away_score: Mapped[int | None] = mapped_column(Integer)
    winner_side: Mapped[str | None] = mapped_column(String(16))
    about: Mapped[str | None] = mapped_column(Text)
    h2h_home_wins: Mapped[int | None] = mapped_column(Integer)
    h2h_away_wins: Mapped[int | None] = mapped_column(Integer)
    h2h_note: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(tz=UTC),
        nullable=False,
    )

    tournament: Mapped[TournamentRecord | None] = relationship()
    home_team: Mapped[TeamRecord] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped[TeamRecord] = relationship(foreign_keys=[away_team_id])
    lineups: Mapped[list[MatchLineupRecord]] = relationship(back_populates="match", cascade="all, delete-orphan")
    streams: Mapped[list[StreamRecord]] = relationship(back_populates="match", cascade="all, delete-orphan")
    odds_snapshots: Mapped[list[OddsSnapshotRecord]] = relationship(
        back_populates="match",
        cascade="all, delete-orphan",
    )


class MatchLineupRecord(Base):
    """Player observed in a match lineup."""

    __tablename__ = "match_lineups"
    __table_args__ = (UniqueConstraint("match_id", "team_id", "player_id", "side", name="uq_match_lineup_player"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(tz=UTC),
        nullable=False,
    )

    match: Mapped[MatchRecord] = relationship(back_populates="lineups")
    team: Mapped[TeamRecord] = relationship()
    player: Mapped[PlayerRecord] = relationship()


class StreamRecord(Base):
    """Stream observed for a match."""

    __tablename__ = "streams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(128), nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(16))
    viewers: Mapped[str | None] = mapped_column(String(32))
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(tz=UTC),
        nullable=False,
    )

    match: Mapped[MatchRecord] = relationship(back_populates="streams")


class OddsSnapshotRecord(Base):
    """Odds are stored as snapshots because they can change over time."""

    __tablename__ = "odds_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    bookmaker: Mapped[str | None] = mapped_column(String(128))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    match: Mapped[MatchRecord] = relationship(back_populates="odds_snapshots")
