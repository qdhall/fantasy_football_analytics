"""Vegas odds data for the Matchup Predictor - a second, independent external
source alongside espn_data.py's ESPN fantasy data. Talks to SportsGameOdds
(https://sportsgameodds.com), a sports-betting odds API whose free tier bills
per EVENT (not per market/odds line - a single NFL game's ~1,000+ odds
entries still cost one "object"), so a weekly pull of a full ~16-game NFL
slate costs about 16 objects against a 2,500/month free allowance.

Odds are live, constantly-moving data - unlike espn_data.py's season-final
disk/R2 cache (built for data that's permanently done and safe to cache
forever), this module only short-TTL-caches (see fetch_current_nfl_odds),
long enough to survive a burst of Streamlit reruns without re-hitting the
API on every single one, short enough to still track real line movement
and live scores within a minute or so.
"""

import re

import requests
import streamlit as st

ODDS_API_BASE = "https://api.sportsgameodds.com/v2"

# A player_id counts as "a real player" (not a team defense/special-teams
# entity) if it doesn't map to a suffix like "_NFL" attached to a team
# abbreviation - SportsGameOdds doesn't offer player-style props for D/ST or
# kickers, so those simply never appear as playerID-tagged odds entries.
_SUFFIX_RE = re.compile(r"\b(jr|sr|ii|iii|iv|v)\.?$")
_PUNCT_RE = re.compile(r"[^\w\s]")


def normalize_player_name(name):
    """Lowercase, drop punctuation, drop a trailing generational suffix -
    used on both sides of the ESPN <-> SportsGameOdds name match, since the
    two systems share no player ID at all."""
    if not name:
        return ""
    cleaned = _PUNCT_RE.sub("", name.lower()).strip()
    cleaned = _SUFFIX_RE.sub("", cleaned).strip()
    return re.sub(r"\s+", " ", cleaned)


def get_odds_api_key():
    return st.secrets.get("sportsgameodds_api_key")


@st.cache_data(ttl=300)
def fetch_current_nfl_odds():
    """This week's NFL events with odds. Session-lifetime caching (the
    original approach) went stale for anyone leaving a tab open for hours as
    lines moved and games completed; removing caching entirely instead had
    every single Streamlit rerun - every widget click on the Matchup
    Predictor page, not just a fresh page load - re-hit the API, which
    quietly blew through SportsGameOdds' free-tier RATE limit (requests per
    minute; separate from, and much stricter than, the per-event monthly
    quota the module docstring above is about) and left every call
    returning a 429 with an empty event list - silently collapsing every
    player's Vegas tier down to an ESPN-only projection with no signal at
    all. st.cache_data's TTL is the fix that satisfies both constraints:
    it's process-wide (shared across every session hitting this app, not
    per-session), so a burst of reruns/pages/users within the same window
    costs one real request. 5 minutes gives real usage (multiple league
    members clicking around at once, not just one dev script hammering it)
    a comfortable safety margin, while still tracking real line movement and
    live scores through the week - Vegas lines don't meaningfully move
    minute-to-minute anyway. Returns the raw list of event dicts from the
    API, or [] if the key is missing or the request fails (callers should
    treat that as "no Vegas signal available" and fall back to ESPN-only
    projections, not an error)."""
    api_key = get_odds_api_key()
    if not api_key:
        return []

    events = []
    try:
        resp = requests.get(
            f"{ODDS_API_BASE}/events/",
            headers={"X-Api-Key": api_key},
            params={"leagueID": "NFL", "oddsAvailable": "true", "limit": 50},
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("success"):
            events = payload.get("data", [])
    except Exception as e:
        print(f"Error fetching NFL odds: {e}")
        events = []

    return events


def parse_player_props(events):
    """{normalized_player_name: {'fantasy_score_line': float|None,
    'stat_props': {statID: float}}} - one entry per player who appears in
    any event's odds. Prefers the de-vigged "fair" line over the raw
    "book" line when both are present (fair strips the bookmaker's margin,
    book doesn't); falls back to book if fair isn't available for that
    market."""
    props = {}
    for event in events:
        odds = event.get("odds") or {}
        for odd in odds.values():
            player_id = odd.get("playerID")
            if not player_id:
                continue
            # Every prop market also exists in 1st-quarter/1st-half/2nd-half
            # variants alongside the full-game one, all sharing the same
            # statID - e.g. Bijan Robinson's fantasyScore line was 22 for
            # "game" but only 4 for "1q". Without this filter, whichever
            # period happened to iterate last silently overwrote the
            # full-game line - a real bug that understated most players.
            if odd.get("periodID") != "game":
                continue
            stat_id = odd.get("statID")
            bet_type = odd.get("betTypeID")
            if bet_type != "ou" or odd.get("sideID") != "over":
                continue  # the "under" side of the same line is redundant

            line = odd.get("fairOverUnder", odd.get("bookOverUnder"))
            if line is None:
                continue
            try:
                line = float(line)
            except (TypeError, ValueError):
                continue

            player_name = _player_name_from_id(player_id)
            entry = props.setdefault(
                normalize_player_name(player_name),
                {"fantasy_score_line": None, "stat_props": {}},
            )
            if stat_id == "fantasyScore":
                entry["fantasy_score_line"] = line
            else:
                entry["stat_props"][stat_id] = line
    return props


_PLAYER_ID_SUFFIX_RE = re.compile(r"_\d+_[A-Z]+$")


def _player_name_from_id(player_id):
    """playerID is e.g. "BREECE_HALL_1_NFL" - a name-derived id, not an
    arbitrary code, so it's more reliable to recover a name from this than
    from a human-written marketName string (whose wording varies by market:
    "Rushing Yards", "Receptions", "Any Touchdowns", etc). Strips the
    trailing "_<index>_<LEAGUE>" and title-cases the rest."""
    stripped = _PLAYER_ID_SUFFIX_RE.sub("", player_id)
    return stripped.replace("_", " ").title()


def parse_team_implied_totals(events):
    """{team_abbr: implied_points} - one entry per team in every event that
    has both a spread and a game total. Standard sportsbook conversion:
    favorite's implied score = (total - abs(spread)) / 2 + abs(spread),
    underdog's = (total - abs(spread)) / 2, expressed here directly from the
    home team's signed spread so it works for either side without a
    favorite/underdog branch."""
    totals = {}
    for event in events:
        odds = event.get("odds") or {}
        home_spread = _first_float(odds, "points-home-game-sp-home", "fairSpread", "bookSpread")
        game_total = _first_float(odds, "points-all-game-ou-over", "fairOverUnder", "bookOverUnder")
        if home_spread is None or game_total is None:
            continue

        home_implied = (game_total - home_spread) / 2
        away_implied = (game_total + home_spread) / 2

        home_abbr = event.get("teams", {}).get("home", {}).get("names", {}).get("short")
        away_abbr = event.get("teams", {}).get("away", {}).get("names", {}).get("short")
        if home_abbr:
            totals[home_abbr] = home_implied
        if away_abbr:
            totals[away_abbr] = away_implied
    return totals


def _first_float(odds, odd_id, *field_names):
    odd = odds.get(odd_id)
    if not odd:
        return None
    for field in field_names:
        value = odd.get(field)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None
