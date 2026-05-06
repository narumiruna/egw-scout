from datetime import UTC
from datetime import datetime
from typing import Any

import pytest
from pydantic import ValidationError

from egw_scout import EsportGame
from egw_scout import MatchInfo
from egw_scout import MatchParticipant
from egw_scout import MatchScore
from egw_scout import MatchStatus
from egw_scout import Team
from egw_scout import TeamSide


def make_match(**overrides: Any) -> MatchInfo:
    data: dict[str, Any] = {
        "id": "match-1",
        "title": "Team Alpha vs Team Beta",
        "game": EsportGame.CS2,
        "status": MatchStatus.SCHEDULED,
        "starts_at": datetime(2026, 5, 6, 12, 0, tzinfo=UTC),
        "best_of": 3,
        "home": MatchParticipant(team=Team(id="team-a", name="Team Alpha"), side=TeamSide.HOME),
        "away": MatchParticipant(team=Team(id="team-b", name="Team Beta"), side=TeamSide.AWAY),
    }
    data.update(overrides)
    return MatchInfo.model_validate(data)


def test_match_info_accepts_core_match_data() -> None:
    match = make_match()

    assert match.id == "match-1"
    assert match.game is EsportGame.CS2
    assert match.best_of == 3
    assert match.home.team.name == "Team Alpha"
    assert match.away.team.name == "Team Beta"


def test_finished_match_requires_score() -> None:
    with pytest.raises(ValidationError, match="finished matches must include score"):
        make_match(status=MatchStatus.FINISHED)


def test_finished_match_accepts_score() -> None:
    match = make_match(
        status=MatchStatus.FINISHED,
        score=MatchScore(home_score=2, away_score=1, winner=TeamSide.HOME),
    )

    assert match.score is not None
    assert match.score.winner is TeamSide.HOME


def test_best_of_must_be_odd() -> None:
    with pytest.raises(ValidationError, match="best_of must be an odd number"):
        make_match(best_of=2)


def test_participants_must_be_different() -> None:
    same_team = Team(id="team-a", name="Team Alpha")

    with pytest.raises(ValidationError, match="home and away teams must be different"):
        make_match(
            home=MatchParticipant(team=same_team, side=TeamSide.HOME),
            away=MatchParticipant(team=same_team, side=TeamSide.AWAY),
        )
