import logging

import httpx

from egw_scout import EsportGame
from egw_scout import MatchStatus
from egw_scout import TeamSide
from egw_scout.scraper import EgamersWorldScraper
from egw_scout.scraper import parse_html
from egw_scout.scraper import parse_match_detail_html
from egw_scout.settings import AppSettings
from egw_scout.settings import ScraperSettings

HTML = """
<!doctype html>
<html>
  <head>
    <title>Upcoming esports matches</title>
    <meta name="description" content="Upcoming CS2 matches and tournaments">
    <link rel="canonical" href="https://egamersworld.com/matches/upcoming-matches">
    <script type="application/ld+json">
      {
        "@context": "https://schema.org",
        "@type": "SportsEvent",
        "name": "Team Alpha vs Team Beta BO3",
        "url": "https://egamersworld.com/matches/team-alpha-vs-team-beta-abc123",
        "description": "CS2 upcoming match",
        "startDate": "2027-05-06T12:00:00Z",
        "eventStatus": "https://schema.org/EventScheduled",
        "competitor": [
          {"@type": "SportsTeam", "name": "Team Alpha"},
          {"@type": "SportsTeam", "name": "Team Beta"}
        ],
        "superEvent": {
          "@type": "SportsEvent",
          "name": "Premier Cup",
          "url": "https://egamersworld.com/events/premier-cup"
        }
      }
    </script>
  </head>
  <body>
    <a href="/matches/upcoming-matches">Matches</a>
    <a href="/events/premier-cup">Event</a>
    <a href="/teams/team-alpha">Team</a>
  </body>
</html>
"""


def test_parse_html_extracts_page_metadata_links_and_matches() -> None:
    page = parse_html(HTML, "https://egamersworld.com/matches/upcoming-matches")

    assert page.metadata.title == "Upcoming esports matches"
    assert page.metadata.description == "Upcoming CS2 matches and tournaments"
    assert len(page.interesting_links) == 2

    assert len(page.matches) == 1
    match = page.matches[0]
    assert match.title == "Team Alpha vs Team Beta BO3"
    assert match.game is EsportGame.CS2
    assert match.status is MatchStatus.SCHEDULED
    assert match.best_of == 3
    assert match.home.side is TeamSide.HOME
    assert match.home.team.name == "Team Alpha"
    assert match.away.team.name == "Team Beta"
    assert match.tournament is not None
    assert match.tournament.name == "Premier Cup"


def test_scraper_records_query_timing_for_each_http_request(caplog) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html=HTML, request=request)

    settings = AppSettings(scraper=ScraperSettings(base_url="https://example.test/"))
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    scraper = EgamersWorldScraper(settings=settings, client=client)

    try:
        with caplog.at_level(logging.DEBUG, logger="egw_scout.scraper"):
            scraper.scrape("/matches/upcoming-matches")
    finally:
        client.close()

    assert len(scraper.query_timings) == 1
    timing = scraper.query_timings[0]
    assert timing.method == "GET"
    assert timing.status_code == 200
    assert str(timing.url) == "https://example.test/matches/upcoming-matches"
    assert timing.elapsed_seconds >= 0
    assert "HTTP query completed in" in caplog.text
    assert "GET https://example.test/matches/upcoming-matches -> 200" in caplog.text


def test_parse_match_detail_html_extracts_detail_sections() -> None:
    html = """
    <!doctype html>
    <html>
      <head>
        <meta property="og:title" content="Team Alpha VS Team Beta ➥ Dota 2" />
        <meta name="description" content="Team Alpha VS Team Beta Dota 2 BO3" />
      </head>
      <body>
        <h1>Team Alpha VS Team Beta live score and match stats - 06.05.26 11:00</h1>
        <span class="match_wrap__ESY2b stylesPage_info__hP38G" id="m_tl1">
          <a class="match_event__v_j2V" href="/dota2/event/premier-cup">Premier Cup</a>
          <span class="match_teams__zCYNy">
            <a class="match_team__AFfWM stylesPage_team__ZxsiM" href="/dota2/team/team-alpha-123">
              <span class="match_flag__BVxZn"><img src="https://cdn.egamersworld.com/asset/flags/us.svg" /></span>
              <span class="match_teamLogo__3eEfS"><img src="https://cdn.egamersworld.com/alpha.svg" /></span>
              <span class="match_teamName__UuLMc">Team Alpha</span>
              <span class="match_odd__szdGT">1.5</span>
            </a>
            <span class="match_scores__S0h6p">
              <div class="live_matchInfo__MKZuY">
                <span class="match_date__SckvM">06.05.26</span>
                <span class="match_time__pXAyi">11:00</span>
                <span class="match_bo__XTV9Z">Bo3</span>
              </div>
            </span>
            <a class="match_team__AFfWM stylesPage_team__ZxsiM match_away__i4MAb" href="/dota2/team/team-beta-456">
              <span class="match_flag__BVxZn"><img src="https://cdn.egamersworld.com/asset/flags/ca.svg" /></span>
              <span class="match_teamLogo__3eEfS"><img src="https://cdn.egamersworld.com/beta.svg" /></span>
              <span class="match_teamName__UuLMc">Team Beta</span>
              <span class="match_odd__szdGT">2.5</span>
            </a>
          </span>
        </span>
        <div id="m_tl2">
          <div class="styles_item___eC4e">
            <div class="styles_country___v3Dl">
              <img src="https://cdn.egamersworld.com/asset/flags/en.svg" />
            </div>
            <div class="styles_name__VVUE0">main_stream</div>
            <span class="styles_count__uugS5">1.2K</span>
          </div>
        </div>
        <div id="m_tl6">
          <div class="styles_list__qx1Sb">
            <a class="styles_item__ehCya styles_team__pl6T0" href="/dota2/team/team-alpha-123">
              <span class="styles_name__7ACBb">Team Alpha</span>
            </a>
            <a class="styles_item__ehCya" href="/dota2/player/player-a">
              <span class="styles_name__7ACBb">Player A</span>
            </a>
          </div>
          <div class="styles_list__qx1Sb">
            <a class="styles_item__ehCya styles_team__pl6T0" href="/dota2/team/team-beta-456">
              <span class="styles_name__7ACBb">Team Beta</span>
            </a>
            <a class="styles_item__ehCya" href="/dota2/player/player-b">
              <span class="styles_name__7ACBb">Player B</span>
            </a>
          </div>
        </div>
        <div id="m_tl7"><div class="styles_score__YF48C">3</div><div class="styles_score__YF48C">2</div></div>
        <div class="stylesPage_description__0jD6N"><div class="seo_info__wi2lF"><p>About this match.</p></div></div>
      </body>
    </html>
    """

    detail = parse_match_detail_html(html, "https://egamersworld.com/dota2/match/event/team-alpha-vs-team-beta")

    assert detail.match.title == "Team Alpha VS Team Beta"
    assert detail.match.starts_at is not None
    assert detail.match.best_of == 3
    assert detail.match.home.team.country == "us"
    assert detail.match.away.team.country == "ca"
    assert detail.match.streams[0].platform == "main_stream"
    assert detail.match.streams[0].language == "en"
    assert detail.odds[0].value == 1.5
    assert detail.odds[1].value == 2.5
    assert detail.lineups[0].players[0].name == "Player A"
    assert detail.lineups[1].players[0].name == "Player B"
    assert detail.head_to_head is not None
    assert detail.head_to_head.home_wins == 3
    assert detail.head_to_head.away_wins == 2
    assert detail.about == "About this match."
