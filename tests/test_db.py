from datetime import UTC
from datetime import datetime

from sqlalchemy import select

from egw_scout.db import ScraperRepository
from egw_scout.db import create_db_engine
from egw_scout.db import create_session_factory
from egw_scout.db import create_tables
from egw_scout.db import session_scope
from egw_scout.db.models import MatchLineupRecord
from egw_scout.db.models import MatchRecord
from egw_scout.db.models import OddsSnapshotRecord
from egw_scout.db.models import StreamRecord
from egw_scout.db.models import TeamRecord
from egw_scout.models import EsportGame
from egw_scout.models import MatchDetail
from egw_scout.models import MatchStatus
from egw_scout.models import TeamSide


def make_detail() -> MatchDetail:
    home = {
        "id": "team-alpha-123",
        "name": "Team Alpha",
        "country": "us",
        "logo_url": "https://cdn.example.com/alpha.svg",
        "url": "https://egamersworld.com/dota2/team/team-alpha-123",
    }
    away = {
        "id": "team-beta-456",
        "name": "Team Beta",
        "country": "ca",
        "logo_url": "https://cdn.example.com/beta.svg",
        "url": "https://egamersworld.com/dota2/team/team-beta-456",
    }
    return MatchDetail.model_validate(
        {
            "source_url": "https://egamersworld.com/dota2/match/event/team-alpha-vs-team-beta",
            "match": {
                "id": "dota2/match/event/team-alpha-vs-team-beta",
                "title": "Team Alpha VS Team Beta",
                "url": "https://egamersworld.com/dota2/match/event/team-alpha-vs-team-beta",
                "game": EsportGame.DOTA2,
                "status": MatchStatus.SCHEDULED,
                "starts_at": datetime(2026, 5, 6, 11, 0, tzinfo=UTC),
                "best_of": 3,
                "tournament": {
                    "name": "Premier Cup",
                    "url": "https://egamersworld.com/dota2/event/premier-cup",
                },
                "home": {"team": home, "side": TeamSide.HOME},
                "away": {"team": away, "side": TeamSide.AWAY},
                "streams": ({"platform": "main_stream", "language": "en", "viewers": "1.2K"},),
            },
            "odds": (
                {"side": TeamSide.HOME, "value": 1.5},
                {"side": TeamSide.AWAY, "value": 2.5},
            ),
            "lineups": (
                {
                    "team": home,
                    "side": TeamSide.HOME,
                    "players": (
                        {
                            "id": "player-a",
                            "name": "Player A",
                            "url": "https://egamersworld.com/dota2/player/player-a",
                        },
                    ),
                },
                {
                    "team": away,
                    "side": TeamSide.AWAY,
                    "players": (
                        {
                            "id": "player-b",
                            "name": "Player B",
                            "url": "https://egamersworld.com/dota2/player/player-b",
                        },
                    ),
                },
            ),
            "head_to_head": {"home_wins": 3, "away_wins": 2},
            "about": "About this match.",
        }
    )


def test_repository_persists_match_detail() -> None:
    engine = create_db_engine("sqlite:///:memory:")
    try:
        create_tables(engine)
        session_factory = create_session_factory(engine)

        with session_scope(session_factory) as session:
            record = ScraperRepository(session).save_match_detail(make_detail())
            match_id = record.id

        with session_scope(session_factory) as session:
            match = session.scalar(select(MatchRecord).where(MatchRecord.id == match_id))
            assert match is not None
            assert match.title == "Team Alpha VS Team Beta"
            assert match.game == "dota2"
            assert match.best_of == 3
            assert match.h2h_home_wins == 3
            assert session.scalars(select(TeamRecord)).all()
            assert len(session.scalars(select(MatchLineupRecord)).all()) == 2
            assert len(session.scalars(select(StreamRecord)).all()) == 1
            assert len(session.scalars(select(OddsSnapshotRecord)).all()) == 2
    finally:
        engine.dispose()


def test_repository_upserts_match_but_keeps_odds_snapshots() -> None:
    engine = create_db_engine("sqlite:///:memory:")
    try:
        create_tables(engine)
        session_factory = create_session_factory(engine)

        with session_scope(session_factory) as session:
            repository = ScraperRepository(session)
            repository.save_match_detail(make_detail())
            repository.save_match_detail(make_detail())

        with session_scope(session_factory) as session:
            assert len(session.scalars(select(MatchRecord)).all()) == 1
            assert len(session.scalars(select(OddsSnapshotRecord)).all()) == 4
    finally:
        engine.dispose()
