"""Small, polite scraper prototype for EGamersWorld pages.

The scraper intentionally does not try to bypass Cloudflare or other access
controls. When the site returns a challenge page, it raises ``AccessBlockedError`` so
callers can decide whether to retry later, use an allowed API/feed, or provide
saved HTML for parsing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Iterable
from datetime import UTC
from datetime import datetime
from typing import cast
from urllib.parse import urljoin
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from bs4 import Tag
from pydantic import Field
from pydantic import HttpUrl
from pydantic import ValidationError

from egw_scout.models import BaseSchema
from egw_scout.models import BettingOdd
from egw_scout.models import EsportGame
from egw_scout.models import HeadToHeadSummary
from egw_scout.models import MatchDetail
from egw_scout.models import MatchInfo
from egw_scout.models import MatchParticipant
from egw_scout.models import MatchStatus
from egw_scout.models import Player
from egw_scout.models import Stream
from egw_scout.models import Team
from egw_scout.models import TeamLineup
from egw_scout.models import TeamSide
from egw_scout.models import Tournament
from egw_scout.settings import AppSettings
from egw_scout.settings import load_settings

MATCH_LINK_RE = re.compile(r"/(?:matches|events|news|tips)(?:/|$)", re.IGNORECASE)
TEAM_SEPARATOR_RE = re.compile(r"\s+(?:vs\.?|v\.?|versus)\s+", re.IGNORECASE)
BEST_OF_RE = re.compile(r"\bbo\s*([1357])\b", re.IGNORECASE)


class AccessBlockedError(RuntimeError):
    """Raised when the remote site returns an anti-bot/challenge page."""

    def __init__(self, url: str, status_code: int, reason: str) -> None:
        self.url = url
        self.status_code = status_code
        self.reason = reason
        super().__init__(f"access blocked for {url} ({status_code}): {reason}")


class PageMetadata(BaseSchema):
    """Basic metadata extracted from an HTML page."""

    url: HttpUrl
    title: str | None = None
    description: str | None = None
    canonical_url: HttpUrl | None = None


class ScrapedPage(BaseSchema):
    """Structured result from one scraped page."""

    metadata: PageMetadata
    interesting_links: tuple[HttpUrl, ...] = Field(default_factory=tuple)
    matches: tuple[MatchInfo, ...] = Field(default_factory=tuple)


class DetailedScrapedPage(BaseSchema):
    """Listing page plus detail records fetched from every match URL."""

    metadata: PageMetadata
    match_details: tuple[MatchDetail, ...] = Field(default_factory=tuple)


class EgamersWorldScraper:
    """Fetch and parse public EGamersWorld HTML pages."""

    def __init__(self, settings: AppSettings | None = None) -> None:
        self.settings = settings or load_settings()
        self.base_url = str(self.settings.scraper.base_url).rstrip("/") + "/"
        self.client = httpx.Client(
            follow_redirects=True,
            timeout=self.settings.scraper.timeout_seconds,
            headers={
                "User-Agent": self.settings.scraper.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": self.settings.scraper.accept_language,
            },
        )

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self.client.close()

    def __enter__(self) -> EgamersWorldScraper:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def scrape(self, path_or_url: str = "/") -> ScrapedPage:
        """Fetch and parse one listing or content page."""
        url = self._absolute_url(path_or_url)
        response = self.client.get(url)
        self._raise_for_blocked_response(response)
        response.raise_for_status()
        return parse_html(response.text, str(response.url))

    def scrape_match_detail(self, path_or_url: str) -> MatchDetail:
        """Fetch and parse one match detail page."""
        url = self._absolute_url(path_or_url)
        response = self.client.get(url)
        self._raise_for_blocked_response(response)
        response.raise_for_status()
        return parse_match_detail_html(response.text, str(response.url))

    def scrape_page_with_details(
        self,
        path_or_url: str = "/matches/upcoming-matches",
        limit: int | None = None,
    ) -> DetailedScrapedPage:
        """Fetch a match listing and then fetch detail pages for its matches."""
        page = self.scrape(path_or_url)
        matches = page.matches[:limit] if limit is not None else page.matches
        details = tuple(self.scrape_match_detail(str(match.url)) for match in matches if match.url is not None)
        return DetailedScrapedPage(metadata=page.metadata, match_details=details)

    def _absolute_url(self, path_or_url: str) -> str:
        return urljoin(self.base_url, path_or_url)

    @staticmethod
    def _raise_for_blocked_response(response: httpx.Response) -> None:
        text_head = response.text[:2048]
        cf_mitigated = response.headers.get("cf-mitigated") == "challenge"
        challenge_title = "<title>Just a moment...</title>" in text_head
        challenge_text = "Enable JavaScript and cookies to continue" in text_head
        if cf_mitigated or challenge_title or challenge_text:
            raise AccessBlockedError(str(response.url), response.status_code, "Cloudflare challenge page")


def parse_html(html: str, url: str) -> ScrapedPage:
    """Parse saved or fetched EGamersWorld-like HTML into structured data."""
    soup = BeautifulSoup(html, "html.parser")
    metadata = PageMetadata.model_validate(
        {
            "url": url,
            "title": _first_text(
                _meta_content(soup, "property", "og:title"),
                _meta_content(soup, "name", "twitter:title"),
                _tag_text(soup.find("title")),
            ),
            "description": _first_text(
                _meta_content(soup, "name", "description"),
                _meta_content(soup, "property", "og:description"),
            ),
            "canonical_url": _canonical_url(soup, url),
        }
    )
    return ScrapedPage.model_validate(
        {
            "metadata": metadata,
            "interesting_links": _interesting_links(soup, url),
            "matches": _matches_from_page(soup, url),
        }
    )


def parse_match_detail_html(html: str, url: str) -> MatchDetail:
    """Parse one EGamersWorld match detail page."""
    soup = BeautifulSoup(html, "html.parser")
    match = _match_from_detail_overview(soup, url)
    if match is None:
        match = next(iter(_matches_from_page(soup, url)), None)
    if match is None:
        raise ValueError(f"could not find match details in {url}")

    streams = _streams_from_detail(soup)
    if streams:
        match = match.model_copy(update={"streams": streams})

    return MatchDetail.model_validate(
        {
            "source_url": url,
            "match": match,
            "odds": _odds_from_detail(soup),
            "lineups": _lineups_from_detail(soup, url),
            "head_to_head": _head_to_head_from_detail(soup),
            "about": _about_from_detail(soup),
        }
    )


def _matches_from_page(soup: BeautifulSoup, page_url: str) -> tuple[MatchInfo, ...]:
    matches: list[MatchInfo] = []
    seen_ids: set[str] = set()
    for match in [*_matches_from_cards(soup, page_url), *_matches_from_json_ld(soup, page_url)]:
        if match.id in seen_ids:
            continue
        seen_ids.add(match.id)
        matches.append(match)
    return tuple(matches)


def _matches_from_json_ld(soup: BeautifulSoup, page_url: str) -> Iterable[MatchInfo]:
    for item in _json_ld_items(soup):
        match = _match_from_event(item, page_url)
        if match is not None:
            yield match


def _json_ld_items(soup: BeautifulSoup) -> Iterable[dict[str, object]]:
    for script in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.IGNORECASE)}):
        if not isinstance(script, Tag):
            continue
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        yield from _flatten_json_ld(payload)


def _flatten_json_ld(payload: object) -> Iterable[dict[str, object]]:
    if isinstance(payload, list):
        for item in payload:
            yield from _flatten_json_ld(item)
    elif isinstance(payload, dict):
        mapping = cast("dict[str, object]", payload)
        graph = mapping.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from _flatten_json_ld(item)
        else:
            yield payload


def _match_from_event(item: dict[str, object], page_url: str) -> MatchInfo | None:
    item_type = item.get("@type")
    types = {item_type.casefold()} if isinstance(item_type, str) else set()
    if isinstance(item_type, list):
        types = {str(value).casefold() for value in item_type}
    if not types.intersection({"event", "sportsevent"}):
        return None

    title = _clean_string(item.get("name"))
    if title is None:
        return None

    team_names = _team_names_from_event(item, title)
    if len(team_names) < 2:
        return None

    match_url = _clean_string(item.get("url")) or page_url
    status = _status_from_event(item)
    starts_at = _parse_datetime(_clean_string(item.get("startDate")))
    best_of = _best_of_from_text(" ".join(filter(None, [title, _clean_string(item.get("description"))])))

    game_text = " ".join(filter(None, [title, match_url, _clean_string(item.get("description"))]))

    try:
        return MatchInfo.model_validate(
            {
                "id": _stable_match_id(match_url, title),
                "title": title,
                "url": match_url,
                "game": _game_from_text(game_text),
                "status": status,
                "starts_at": starts_at,
                "best_of": best_of,
                "tournament": _tournament_from_event(item),
                "home": MatchParticipant(team=Team(name=team_names[0]), side=TeamSide.HOME),
                "away": MatchParticipant(team=Team(name=team_names[1]), side=TeamSide.AWAY),
            }
        )
    except ValidationError:
        return None


def _matches_from_cards(soup: BeautifulSoup, page_url: str) -> Iterable[MatchInfo]:
    """Extract server-rendered match cards from EGamersWorld listing pages."""
    for card in _find_all_with_class(soup, "match_wrap__"):
        teams_link = _find_with_class(card, "match_teams__")
        if teams_link is None:
            continue
        href = teams_link.get("href")
        match_url = urljoin(page_url, href) if isinstance(href, str) else page_url

        team_names = [_tag_text(tag) for tag in _find_all_with_class(teams_link, "match_teamName__")]
        team_names = [name for name in team_names if name is not None]
        if len(team_names) < 2:
            title = _clean_string(teams_link.get("title"))
            if title is not None:
                team_names = _team_names_from_title(title)
        if len(team_names) < 2:
            continue

        event_link = _find_with_class(card, "match_event__")
        event_name = _tag_text(event_link) if event_link is not None else None
        event_href = event_link.get("href") if event_link is not None else None
        event_url = urljoin(page_url, event_href) if isinstance(event_href, str) else None

        title = _clean_string(teams_link.get("title")) or f"{team_names[0]} vs {team_names[1]}"
        date_text = _tag_text(_find_with_class(card, "match_date__"))
        time_text = _tag_text(_find_with_class(card, "match_time__"))
        best_of_text = _tag_text(_find_with_class(card, "match_bo__"))
        game_text = " ".join(filter(None, [match_url, _image_alt(_find_with_class(card, "match_gameLogo__"))]))

        try:
            yield MatchInfo.model_validate(
                {
                    "id": _stable_match_id(match_url, title),
                    "title": title,
                    "url": match_url,
                    "game": _game_from_text(game_text),
                    "status": _status_from_listing_url(page_url),
                    "starts_at": _parse_listing_datetime(date_text, time_text),
                    "best_of": _best_of_from_text(best_of_text or title),
                    "tournament": _tournament_from_card(event_name, event_url),
                    "home": MatchParticipant(team=Team(name=team_names[0]), side=TeamSide.HOME),
                    "away": MatchParticipant(team=Team(name=team_names[1]), side=TeamSide.AWAY),
                }
            )
        except ValidationError:
            continue


def _match_from_detail_overview(soup: BeautifulSoup, page_url: str) -> MatchInfo | None:
    overview = soup.find(id="m_tl1")
    if not isinstance(overview, Tag):
        return None

    team_tags = _detail_team_tags(overview)
    if len(team_tags) < 2:
        return None
    home_team = _team_from_tag(team_tags[0], page_url)
    away_team = _team_from_tag(team_tags[1], page_url)
    if home_team is None or away_team is None:
        return None

    event_link = _find_with_class(overview, "match_event__")
    event_name = _tag_text(event_link) if event_link is not None else None
    event_href = event_link.get("href") if event_link is not None else None
    event_url = urljoin(page_url, event_href) if isinstance(event_href, str) else None

    title = _title_from_detail(soup, home_team.name, away_team.name)
    date_text = _tag_text(_find_with_class(overview, "match_date__"))
    time_text = _tag_text(_find_with_class(overview, "match_time__"))
    best_of_text = _tag_text(_find_with_class(overview, "match_bo__"))
    game_text = " ".join(
        filter(
            None,
            [
                page_url,
                _meta_content(soup, "property", "og:title"),
                _meta_content(soup, "name", "description"),
            ],
        )
    )

    try:
        return MatchInfo.model_validate(
            {
                "id": _stable_match_id(page_url, title),
                "title": title,
                "url": page_url,
                "game": _game_from_text(game_text),
                "status": _status_from_listing_url(page_url),
                "starts_at": _parse_listing_datetime(date_text, time_text),
                "best_of": _best_of_from_text(best_of_text or title),
                "tournament": _tournament_from_card(event_name, event_url),
                "home": MatchParticipant(team=home_team, side=TeamSide.HOME),
                "away": MatchParticipant(team=away_team, side=TeamSide.AWAY),
            }
        )
    except ValidationError:
        return None


def _detail_team_tags(overview: Tag) -> list[Tag]:
    team_tags: list[Tag] = []
    for tag in _find_all_with_class(overview, "match_team__"):
        if _find_with_class(tag, "match_teamName__") is None:
            continue
        if not isinstance(tag.get("href"), str):
            continue
        team_tags.append(tag)
        if len(team_tags) == 2:
            break
    return team_tags


def _team_from_tag(tag: Tag, page_url: str) -> Team | None:
    name = _tag_text(_find_with_class(tag, "match_teamName__")) or _tag_text(_find_with_class(tag, "styles_name__"))
    if name is None:
        return None
    href = tag.get("href")
    team_url = urljoin(page_url, href) if isinstance(href, str) else None
    logo = _image_src(_find_with_class(tag, "match_teamLogo__")) or _image_src(_find_with_class(tag, "styles_logo__"))
    flag_url = _image_src(_find_with_class(tag, "match_flag__")) or _image_src(_find_with_class(tag, "styles_flag__"))
    country = _country_from_flag_url(flag_url)
    return Team.model_validate(
        {
            "id": _id_from_url(team_url),
            "name": name,
            "country": country,
            "logo_url": logo,
            "url": team_url,
        }
    )


def _title_from_detail(soup: BeautifulSoup, home_name: str, away_name: str) -> str:
    h1_text = _tag_text(soup.find("h1"))
    if h1_text:
        marker = " live score"
        return h1_text.split(marker, maxsplit=1)[0].strip() or f"{home_name} vs {away_name}"
    og_title = _meta_content(soup, "property", "og:title")
    if og_title:
        return og_title.split("➥", maxsplit=1)[0].strip() or f"{home_name} vs {away_name}"
    return f"{home_name} vs {away_name}"


def _streams_from_detail(soup: BeautifulSoup) -> tuple[Stream, ...]:
    section = soup.find(id="m_tl2")
    if not isinstance(section, Tag):
        return ()
    streams: list[Stream] = []
    for item in _find_all_with_class(section, "styles_item__"):
        name = _tag_text(_find_with_class(item, "styles_name__"))
        if name is None:
            continue
        language = _country_from_flag_url(_image_src(_find_with_class(item, "styles_country__")))
        viewers = _tag_text(_find_with_class(item, "styles_count__"))
        streams.append(Stream(platform=name, language=language, viewers=viewers))
    return tuple(streams)


def _odds_from_detail(soup: BeautifulSoup) -> tuple[BettingOdd, ...]:
    overview = soup.find(id="m_tl1")
    if not isinstance(overview, Tag):
        return ()
    odds: list[BettingOdd] = []
    for side, team_tag in zip((TeamSide.HOME, TeamSide.AWAY), _detail_team_tags(overview), strict=False):
        value = _float_from_text(_tag_text(_find_with_class(team_tag, "match_odd__")))
        if value is not None:
            odds.append(BettingOdd(side=side, value=value))
    return tuple(odds)


def _lineups_from_detail(soup: BeautifulSoup, page_url: str) -> tuple[TeamLineup, ...]:
    section = soup.find(id="m_tl6")
    if not isinstance(section, Tag):
        return ()
    lineups: list[TeamLineup] = []
    list_tags = _find_all_with_class(section, "styles_list__")
    for side, list_tag in zip((TeamSide.HOME, TeamSide.AWAY), list_tags, strict=False):
        team_tag = next((tag for tag in _find_all_with_class(list_tag, "styles_team__")), None)
        if team_tag is None:
            continue
        team = _lineup_team_from_tag(team_tag, page_url)
        players = tuple(_players_from_lineup(list_tag, page_url))
        lineups.append(TeamLineup(team=team, side=side, players=players))
        if len(lineups) == 2:
            break
    return tuple(lineups)


def _lineup_team_from_tag(tag: Tag, page_url: str) -> Team:
    name = _tag_text(_find_with_class(tag, "styles_name__")) or "Unknown"
    href = tag.get("href")
    team_url = urljoin(page_url, href) if isinstance(href, str) else None
    return Team.model_validate(
        {
            "id": _id_from_url(team_url),
            "name": name,
            "logo_url": _image_src(_find_with_class(tag, "styles_logo__")),
            "url": team_url,
        }
    )


def _players_from_lineup(list_tag: Tag, page_url: str) -> Iterable[Player]:
    for item in _find_all_with_class(list_tag, "styles_item__"):
        if _class_contains(item, "styles_team__"):
            continue
        name = _tag_text(_find_with_class(item, "styles_name__"))
        if name is None:
            continue
        href = item.get("href")
        player_url = urljoin(page_url, href) if isinstance(href, str) else None
        yield Player.model_validate(
            {
                "id": _id_from_url(player_url),
                "name": name,
                "country": _country_from_flag_url(_image_src(_find_with_class(item, "styles_flag__"))),
                "photo_url": _image_src(_find_with_class(item, "styles_photo__")),
                "url": player_url,
            }
        )


def _head_to_head_from_detail(soup: BeautifulSoup) -> HeadToHeadSummary | None:
    section = soup.find(id="m_tl7")
    if not isinstance(section, Tag):
        return None
    scores = [_int_from_text(_tag_text(tag)) for tag in _find_all_with_class(section, "styles_score__")]
    note = _tag_text(_find_with_class(section, "styles_noData__"))
    if not scores and note is None:
        return None
    home_wins = scores[0] or 0 if len(scores) > 0 else 0
    away_wins = scores[1] or 0 if len(scores) > 1 else 0
    return HeadToHeadSummary(home_wins=home_wins, away_wins=away_wins, note=note)


def _about_from_detail(soup: BeautifulSoup) -> str | None:
    section = _find_with_class(soup, "stylesPage_description__")
    if section is None:
        return None
    info = _find_with_class(section, "seo_info__") or section
    return _tag_text(info)


def _team_names_from_event(item: dict[str, object], title: str) -> list[str]:
    names: list[str] = []
    for field in ("competitor", "performer", "participant"):
        value = item.get(field)
        for name in _names_from_json_ld_value(value):
            if name not in names:
                names.append(name)
    if len(names) >= 2:
        return names[:2]

    return _team_names_from_title(title)


def _team_names_from_title(title: str) -> list[str]:
    title_parts = [part.strip(" -—") for part in TEAM_SEPARATOR_RE.split(title, maxsplit=1)]
    return [part for part in title_parts if part][:2]


def _names_from_json_ld_value(value: object) -> Iterable[str]:
    if isinstance(value, str):
        cleaned = _clean_string(value)
        if cleaned is not None:
            yield cleaned
    elif isinstance(value, dict):
        mapping = cast("dict[str, object]", value)
        name = _clean_string(mapping.get("name"))
        if name is not None:
            yield name
    elif isinstance(value, list):
        for item in value:
            yield from _names_from_json_ld_value(item)


def _tournament_from_event(item: dict[str, object]) -> Tournament | None:
    container = item.get("superEvent") or item.get("subEvent")
    if not isinstance(container, dict):
        return None
    container_mapping = cast("dict[str, object]", container)
    name = _clean_string(container_mapping.get("name"))
    if name is None:
        return None
    try:
        return Tournament.model_validate({"name": name, "url": _clean_string(container_mapping.get("url"))})
    except ValidationError:
        return Tournament(name=name)


def _tournament_from_card(name: str | None, url: str | None) -> Tournament | None:
    if name is None:
        return None
    try:
        return Tournament.model_validate({"name": name, "url": url})
    except ValidationError:
        return Tournament(name=name)


def _status_from_event(item: dict[str, object]) -> MatchStatus:
    event_status = _clean_string(item.get("eventStatus"))
    if event_status:
        normalized = event_status.casefold()
        if "cancel" in normalized:
            return MatchStatus.CANCELLED
        if "postpon" in normalized:
            return MatchStatus.POSTPONED
        if "live" in normalized:
            return MatchStatus.LIVE
        if "complete" in normalized or "finished" in normalized:
            return MatchStatus.FINISHED
    starts_at = _parse_datetime(_clean_string(item.get("startDate")))
    if starts_at and starts_at < datetime.now(tz=UTC):
        return MatchStatus.FINISHED
    return MatchStatus.SCHEDULED


def _game_from_text(text: str) -> EsportGame:
    normalized = text.casefold()
    if (
        "counter-strike" in normalized
        or "counterstrike" in normalized
        or "cs2" in normalized
        or "cs:go" in normalized
        or "csgo" in normalized
    ):
        return EsportGame.CS2
    if "dota" in normalized:
        return EsportGame.DOTA2
    if "league of legends" in normalized or re.search(r"\blol\b", normalized):
        return EsportGame.LEAGUE_OF_LEGENDS
    if "valorant" in normalized:
        return EsportGame.VALORANT
    if "rocket league" in normalized:
        return EsportGame.ROCKET_LEAGUE
    if "rainbow" in normalized:
        return EsportGame.RAINBOW_SIX
    if "call of duty" in normalized or re.search(r"\bcod\b", normalized):
        return EsportGame.CALL_OF_DUTY
    return EsportGame.OTHER


def _best_of_from_text(text: str) -> int:
    match = BEST_OF_RE.search(text)
    if match is None:
        return 1
    return int(match.group(1))


def _status_from_listing_url(page_url: str) -> MatchStatus:
    path = urlparse(page_url).path.casefold()
    if "history" in path:
        return MatchStatus.FINISHED
    return MatchStatus.SCHEDULED


def _parse_listing_datetime(date_text: str | None, time_text: str | None) -> datetime | None:
    if date_text is None:
        return None
    value = date_text if time_text is None else f"{date_text} {time_text}"
    for fmt in ("%d.%m.%y %H:%M", "%d.%m.%y"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _stable_match_id(match_url: str, title: str) -> str:
    path = urlparse(match_url).path.strip("/")
    if path:
        return path
    return hashlib.sha1(title.encode()).hexdigest()[:12]


def _find_with_class(root: BeautifulSoup | Tag, marker: str) -> Tag | None:
    for tag in _find_all_with_class(root, marker):
        return tag
    return None


def _find_all_with_class(root: BeautifulSoup | Tag, marker: str) -> Iterable[Tag]:
    for element in root.find_all(True):
        if isinstance(element, Tag) and _class_contains(element, marker):
            yield element


def _class_contains(tag: Tag, marker: str) -> bool:
    class_value = tag.get("class")
    if isinstance(class_value, str):
        return marker in class_value
    if isinstance(class_value, list):
        return any(marker in str(item) for item in class_value)
    return False


def _image_alt(tag: Tag | None) -> str | None:
    if tag is None:
        return None
    image = tag if tag.name == "img" else tag.find("img")
    if not isinstance(image, Tag):
        return None
    alt = image.get("alt")
    return alt if isinstance(alt, str) else None


def _image_src(tag: Tag | None) -> str | None:
    if tag is None:
        return None
    image = tag if tag.name == "img" else tag.find("img")
    if not isinstance(image, Tag):
        return None
    src = image.get("src")
    return src if isinstance(src, str) and src.startswith(("http://", "https://")) else None


def _country_from_flag_url(flag_url: str | None) -> str | None:
    if flag_url is None:
        return None
    match = re.search(r"/flags/([a-z]{2})\.svg", flag_url, re.IGNORECASE)
    return match.group(1).lower() if match else None


def _id_from_url(value: str | None) -> str | None:
    if value is None:
        return None
    path = urlparse(value).path.strip("/")
    return path.rsplit("/", maxsplit=1)[-1] if path else None


def _float_from_text(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def _int_from_text(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.search(r"\d+", value)
    return int(match.group(0)) if match else None


def _interesting_links(soup: BeautifulSoup, page_url: str) -> tuple[str, ...]:
    links: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href")
        if not isinstance(href, str):
            continue
        absolute = urljoin(page_url, href)
        if absolute in seen or MATCH_LINK_RE.search(urlparse(absolute).path) is None:
            continue
        seen.add(absolute)
        links.append(absolute)
    return tuple(links)


def _canonical_url(soup: BeautifulSoup, page_url: str) -> str | None:
    for link in soup.find_all("link"):
        if not isinstance(link, Tag):
            continue
        rel = link.get("rel")
        rel_values = rel if isinstance(rel, list) else [rel]
        if "canonical" not in rel_values:
            continue
        href = link.get("href")
        if not isinstance(href, str) or not href.strip():
            return None
        return urljoin(page_url, href)
    return None


def _meta_content(soup: BeautifulSoup, attr: str, value: str) -> str | None:
    tag = soup.find("meta", attrs={attr: value})
    if not isinstance(tag, Tag):
        return None
    content = tag.get("content")
    return content if isinstance(content, str) else None


def _tag_text(tag: object) -> str | None:
    if not isinstance(tag, Tag):
        return None
    return tag.get_text(" ", strip=True)


def _first_text(*values: str | None) -> str | None:
    for value in values:
        cleaned = _clean_string(value)
        if cleaned is not None:
            return cleaned
    return None


def _clean_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch and parse EGamersWorld pages.")
    parser.add_argument("path", nargs="?", default="/matches/upcoming-matches")
    parser.add_argument("--limit", type=int, default=None, help="Limit the number of matches printed or detailed.")
    parser.add_argument("--details", action="store_true", help="Fetch match detail pages for listing results.")
    args = parser.parse_args(argv)

    try:
        with EgamersWorldScraper() as scraper:
            if args.details and _looks_like_match_url(args.path):
                result: BaseSchema = scraper.scrape_match_detail(args.path)
            elif args.details:
                result = scraper.scrape_page_with_details(args.path, limit=args.limit)
            else:
                page = scraper.scrape(args.path)
                if args.limit is not None:
                    page = page.model_copy(update={"matches": page.matches[: args.limit]})
                result = page
    except AccessBlockedError as exc:
        print(json.dumps({"ok": False, "error": str(exc), "url": exc.url}, ensure_ascii=False, indent=2))
        return 2

    print(result.model_dump_json(indent=2))
    return 0


def _looks_like_match_url(path_or_url: str) -> bool:
    return "/match/" in urlparse(path_or_url).path


if __name__ == "__main__":
    raise SystemExit(main())
