"""Persistence operations for scraper Pydantic models."""

from __future__ import annotations

from datetime import UTC
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from egw_scout.db.models import MatchLineupRecord
from egw_scout.db.models import MatchRecord
from egw_scout.db.models import OddsSnapshotRecord
from egw_scout.db.models import PlayerRecord
from egw_scout.db.models import StreamRecord
from egw_scout.db.models import TeamRecord
from egw_scout.db.models import TournamentRecord
from egw_scout.models import MatchDetail
from egw_scout.models import Player
from egw_scout.models import Team
from egw_scout.models import Tournament


class ScraperRepository:
    """Repository that normalizes scraper models into relational tables."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def save_match_detail(self, detail: MatchDetail, *, observed_at: datetime | None = None) -> MatchRecord:
        """Upsert a match detail payload and related entities.

        Odds and streams are intentionally inserted as observations/snapshots.
        Lineups are upserted by match/team/player/side.
        """
        observed_at = observed_at or datetime.now(tz=UTC)
        match = detail.match
        home_team = self.upsert_team(match.home.team)
        away_team = self.upsert_team(match.away.team)
        tournament = self.upsert_tournament(match.tournament) if match.tournament else None

        record = self._match_by_source_url(str(match.url))
        if record is None:
            record = MatchRecord(
                source_id=match.id,
                source_url=str(match.url),
                title=match.title,
                game=match.game.value,
                status=match.status.value,
                starts_at=match.starts_at,
                best_of=match.best_of,
                home_team_id=home_team.id,
                away_team_id=away_team.id,
                tournament_id=tournament.id if tournament else None,
            )
            self.session.add(record)
            self.session.flush()

        record.source_id = match.id
        record.title = match.title
        record.game = match.game.value
        record.status = match.status.value
        record.starts_at = match.starts_at
        record.best_of = match.best_of
        record.home_team_id = home_team.id
        record.away_team_id = away_team.id
        record.tournament_id = tournament.id if tournament else None
        record.home_score = match.score.home_score if match.score else None
        record.away_score = match.score.away_score if match.score else None
        record.winner_side = match.score.winner.value if match.score and match.score.winner else None
        record.about = detail.about
        record.h2h_home_wins = detail.head_to_head.home_wins if detail.head_to_head else None
        record.h2h_away_wins = detail.head_to_head.away_wins if detail.head_to_head else None
        record.h2h_note = detail.head_to_head.note if detail.head_to_head else None
        record.last_seen_at = observed_at
        self.session.flush()

        for lineup in detail.lineups:
            team = self.upsert_team(lineup.team)
            for player in lineup.players:
                player_record = self.upsert_player(player)
                self._ensure_lineup(record.id, team.id, player_record.id, lineup.side.value, observed_at)

        for stream in match.streams:
            self.session.add(
                StreamRecord(
                    match_id=record.id,
                    platform=stream.platform,
                    url=str(stream.url) if stream.url else None,
                    language=stream.language,
                    viewers=stream.viewers,
                    observed_at=observed_at,
                )
            )

        for odd in detail.odds:
            self.session.add(
                OddsSnapshotRecord(
                    match_id=record.id,
                    side=odd.side.value,
                    value=odd.value,
                    observed_at=observed_at,
                )
            )

        self.session.flush()
        return record

    def upsert_team(self, team: Team) -> TeamRecord:
        """Upsert a team by source URL, source ID, or name."""
        record = self._team_by_identity(
            source_url=str(team.url) if team.url else None,
            source_id=team.id,
            name=team.name,
        )
        if record is None:
            record = TeamRecord(source_id=team.id, source_url=str(team.url) if team.url else None, name=team.name)
            self.session.add(record)
            self.session.flush()
        record.source_id = team.id or record.source_id
        record.source_url = str(team.url) if team.url else record.source_url
        record.name = team.name
        record.country = team.country
        record.logo_url = str(team.logo_url) if team.logo_url else None
        self.session.flush()
        return record

    def upsert_player(self, player: Player) -> PlayerRecord:
        """Upsert a player by source URL, source ID, or name."""
        record = self._player_by_identity(
            source_url=str(player.url) if player.url else None,
            source_id=player.id,
            name=player.name,
        )
        if record is None:
            record = PlayerRecord(
                source_id=player.id,
                source_url=str(player.url) if player.url else None,
                name=player.name,
            )
            self.session.add(record)
            self.session.flush()
        record.source_id = player.id or record.source_id
        record.source_url = str(player.url) if player.url else record.source_url
        record.name = player.name
        record.country = player.country
        record.photo_url = str(player.photo_url) if player.photo_url else None
        self.session.flush()
        return record

    def upsert_tournament(self, tournament: Tournament) -> TournamentRecord:
        """Upsert a tournament by source URL, source ID, or name."""
        record = self._tournament_by_identity(
            source_url=str(tournament.url) if tournament.url else None,
            source_id=tournament.id,
            name=tournament.name,
        )
        if record is None:
            record = TournamentRecord(
                source_id=tournament.id,
                source_url=str(tournament.url) if tournament.url else None,
                name=tournament.name,
            )
            self.session.add(record)
            self.session.flush()
        record.source_id = tournament.id or record.source_id
        record.source_url = str(tournament.url) if tournament.url else record.source_url
        record.name = tournament.name
        record.tier = tournament.tier
        record.prize_pool = tournament.prize_pool
        record.starts_at = tournament.starts_at
        record.ends_at = tournament.ends_at
        self.session.flush()
        return record

    def _match_by_source_url(self, source_url: str) -> MatchRecord | None:
        return self.session.scalar(select(MatchRecord).where(MatchRecord.source_url == source_url))

    def _team_by_identity(self, *, source_url: str | None, source_id: str | None, name: str) -> TeamRecord | None:
        if source_url:
            record = self.session.scalar(select(TeamRecord).where(TeamRecord.source_url == source_url))
            if record:
                return record
        if source_id:
            record = self.session.scalar(select(TeamRecord).where(TeamRecord.source_id == source_id))
            if record:
                return record
        return self.session.scalar(select(TeamRecord).where(TeamRecord.source_url.is_(None), TeamRecord.name == name))

    def _player_by_identity(self, *, source_url: str | None, source_id: str | None, name: str) -> PlayerRecord | None:
        if source_url:
            record = self.session.scalar(select(PlayerRecord).where(PlayerRecord.source_url == source_url))
            if record:
                return record
        if source_id:
            record = self.session.scalar(select(PlayerRecord).where(PlayerRecord.source_id == source_id))
            if record:
                return record
        return self.session.scalar(
            select(PlayerRecord).where(
                PlayerRecord.source_url.is_(None),
                PlayerRecord.name == name,
            )
        )

    def _tournament_by_identity(
        self,
        *,
        source_url: str | None,
        source_id: str | None,
        name: str,
    ) -> TournamentRecord | None:
        if source_url:
            record = self.session.scalar(select(TournamentRecord).where(TournamentRecord.source_url == source_url))
            if record:
                return record
        if source_id:
            record = self.session.scalar(select(TournamentRecord).where(TournamentRecord.source_id == source_id))
            if record:
                return record
        return self.session.scalar(
            select(TournamentRecord).where(
                TournamentRecord.source_url.is_(None),
                TournamentRecord.name == name,
            )
        )

    def _ensure_lineup(
        self,
        match_id: int,
        team_id: int,
        player_id: int,
        side: str,
        observed_at: datetime,
    ) -> MatchLineupRecord:
        record = self.session.scalar(
            select(MatchLineupRecord).where(
                MatchLineupRecord.match_id == match_id,
                MatchLineupRecord.team_id == team_id,
                MatchLineupRecord.player_id == player_id,
                MatchLineupRecord.side == side,
            )
        )
        if record is None:
            record = MatchLineupRecord(
                match_id=match_id,
                team_id=team_id,
                player_id=player_id,
                side=side,
                observed_at=observed_at,
            )
            self.session.add(record)
        else:
            record.observed_at = observed_at
        self.session.flush()
        return record
