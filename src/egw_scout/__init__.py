"""EGamersWorld data models."""

from egw_scout.models import BaseSchema
from egw_scout.models import BettingOdd
from egw_scout.models import EsportGame
from egw_scout.models import HeadToHeadSummary
from egw_scout.models import MapScore
from egw_scout.models import MatchDetail
from egw_scout.models import MatchInfo
from egw_scout.models import MatchParticipant
from egw_scout.models import MatchScore
from egw_scout.models import MatchStatus
from egw_scout.models import Player
from egw_scout.models import Stream
from egw_scout.models import Team
from egw_scout.models import TeamLineup
from egw_scout.models import TeamSide
from egw_scout.models import Tournament

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
