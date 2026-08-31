"""Shared ESPN league data loading and calculation helpers used by every page."""

import pickle
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from espn_api.football import League

CACHE_DIR = Path(__file__).parent / ".cache"
# Bump this whenever a change to the parsing/computation logic would change the
# shape or correctness of cached data. Old cache files written under a stale
# version are simply never read (the version is in the filename), so nothing
# needs an explicit migration step - they just quietly get recomputed once.
CACHE_SCHEMA_VERSION = 3


def _is_year_final(year):
    """A fantasy season is treated as permanently over - and safe to cache forever -
    once we're in a later calendar year than it started in; by the time the NFL
    calendar rolls over, that season is long done. The current (or a future)
    calendar year is always re-fetched live, since it could still be in progress."""
    return year < datetime.now().year


def _cache_path(kind, league_id, year):
    return CACHE_DIR / f"{kind}_v{CACHE_SCHEMA_VERSION}_{league_id}_{year}.pkl"


def _load_cached_year(kind, league_id, year):
    """The cached per-year result if this season is over and a cache file exists
    for the current schema version, else None (meaning: compute it live)."""
    if not _is_year_final(year):
        return None
    path = _cache_path(kind, league_id, year)
    if not path.exists():
        return None
    try:
        with open(path, 'rb') as f:
            return pickle.load(f)
    except Exception as e:
        print(f"Cache read failed for {kind} {year}: {e}")
        return None


def _save_cached_year(kind, league_id, year, data):
    """Persists a completed season's computed result so it never needs to be
    fetched from ESPN again. A season still in progress is never cached, since
    its data can still change week to week."""
    if not _is_year_final(year):
        return
    try:
        CACHE_DIR.mkdir(exist_ok=True)
        with open(_cache_path(kind, league_id, year), 'wb') as f:
            pickle.dump(data, f)
    except Exception as e:
        print(f"Cache write failed for {kind} {year}: {e}")


def get_credentials():
    """Read league credentials from Streamlit secrets."""
    return (
        st.secrets["league_id"],
        st.secrets["espn_s2"],
        st.secrets["swid"],
    )


def get_owner_name(team):
    """Extract a stable display name for a team's owner."""
    owner_name = "Unknown Owner"
    if hasattr(team, 'owners') and team.owners:
        if isinstance(team.owners, list) and len(team.owners) > 0:
            owner_name = team.owners[0].get('firstName', '') + ' ' + team.owners[0].get('lastName', '')
        elif isinstance(team.owners, dict):
            owner_name = team.owners.get('firstName', '') + ' ' + team.owners.get('lastName', '')
        else:
            owner_name = str(team.owners[0]) if isinstance(team.owners, list) else str(team.owners)

    owner_name = owner_name.strip()
    if owner_name == "" or owner_name == " ":
        owner_name = f"Team {team.team_id}"
    return owner_name


def get_playoff_start_week(year):
    """Get the correct playoff start week based on year"""
    if year in [2019, 2020]:
        return 14  # 13 regular season weeks, playoffs start week 14
    elif year == 2021:
        return 15  # 14 regular season weeks for 2021
    else:
        return 15  # Standard 14 regular season weeks for 2022+, playoffs start week 15


def get_all_time_h2h_by_scores_fixed(league_id, start_year, end_year, espn_s2=None, swid=None, record_type='all'):
    """Head-to-head win/loss records, keyed by OWNER (not team_id/team_name) -
    same reasoning as build_league_history: a team's name changes year to year,
    and aggregating by anything else risks splitting or merging the wrong
    seasons together if a franchise slot's id or name isn't perfectly stable."""

    all_time_h2h = {}

    for year in range(start_year, end_year + 1):
        print(f"Processing {year} season...")

        try:
            league = League(league_id, year, espn_s2=espn_s2, swid=swid)

            # Get correct playoff start week for this year
            playoff_start_week = get_playoff_start_week(year)
            # ESPN schedules every team into games during "playoff weeks" - the top
            # seeds play the real playoff bracket, everyone else plays a consolation
            # bracket. Only a team's regular-season seed tells us which bracket
            # they're actually in.
            playoff_team_count = getattr(league.settings, 'playoff_team_count', None)

            max_week = league.current_week
            processed_games = set()

            for week in range(max_week):

                actual_week = week + 1
                is_playoff_week = actual_week >= playoff_start_week

                for team in league.teams:
                    if (week < len(team.schedule) and
                        week < len(team.scores) and
                        hasattr(team.schedule[week], 'team_id')):

                        opponent = team.schedule[week]
                        team_score = team.scores[week]
                        opponent_score = opponent.scores[week]

                        if team_score is None or opponent_score is None:
                            continue

                        # A playoff-week game only counts as a real playoff game if both
                        # teams actually qualified; otherwise it's a consolation-bracket game
                        team_made_playoffs = playoff_team_count is not None and team.standing <= playoff_team_count
                        opponent_made_playoffs = playoff_team_count is not None and opponent.standing <= playoff_team_count
                        is_real_playoff_game = is_playoff_week and team_made_playoffs and opponent_made_playoffs

                        # Filter based on record type
                        if record_type == 'regular' and is_real_playoff_game:
                            continue
                        elif record_type == 'playoffs' and not is_real_playoff_game:
                            continue

                        # Avoid double counting
                        game_id = tuple(sorted([team.team_id, opponent.team_id]))
                        full_game_id = (year, week, *game_id)

                        if full_game_id in processed_games:
                            continue
                        processed_games.add(full_game_id)

                        team_owner = get_owner_name(team)
                        opponent_owner = get_owner_name(opponent)

                        # determine winner
                        if team_score > opponent_score:
                            winner = team_owner
                        elif opponent_score > team_score:
                            winner = opponent_owner
                        else:
                            continue

                        # Create consistent key (alphabetical, for a stable lookup either way)
                        key = tuple(sorted([team_owner, opponent_owner]))

                        if key not in all_time_h2h:
                            all_time_h2h[key] = {team_owner: 0, opponent_owner: 0}

                        # Record the win for the owner with the HIGHER score
                        all_time_h2h[key][winner] += 1

        except Exception as e:
            print(f"Error processing {year}: {e}")
            st.error(f"Error processing {year}: {e}")

    # h2h dict
    readable_records = {}
    for (owner1, owner2), wins_dict in all_time_h2h.items():
        owner1_wins = wins_dict.get(owner1, 0)
        owner2_wins = wins_dict.get(owner2, 0)

        # Create both directions for easy lookup
        key1 = f"{owner1} vs {owner2}"
        key2 = f"{owner2} vs {owner1}"

        readable_records[key1] = {
            'team1': owner1,
            'team1_wins': owner1_wins,
            'team2': owner2,
            'team2_wins': owner2_wins,
            'total_games': owner1_wins + owner2_wins
        }

        readable_records[key2] = {
            'team1': owner2,
            'team1_wins': owner2_wins,
            'team2': owner1,
            'team2_wins': owner1_wins,
            'total_games': owner1_wins + owner2_wins
        }

    return readable_records


def create_h2h_matrix(league_id, start_year, end_year, espn_s2=None, swid=None, record_type='all'):
    """
    Create the H2H matrix using the scores function
    record_type: 'all', 'regular', 'playoffs'
    """

    # Get records using the scores function
    all_records = get_all_time_h2h_by_scores_fixed(league_id, start_year, end_year, espn_s2, swid, record_type)

    # Extract team names
    all_teams = set()
    for key in all_records.keys():
        if " vs " in key:
            teams = key.split(" vs ")
            if len(teams) == 2:
                all_teams.add(teams[0])
                all_teams.add(teams[1])

    all_teams = sorted(list(all_teams))

    # Create matrix
    matrix_data = {}
    for row_team in all_teams:
        matrix_data[row_team] = {}
        for col_team in all_teams:
            if row_team == col_team:
                matrix_data[row_team][col_team] = "-"
            else:
                lookup_key = f"{row_team} vs {col_team}"

                if lookup_key in all_records:
                    record = all_records[lookup_key]

                    flipped_wins = record['team2_wins']
                    flipped_losses = record['team1_wins']

                    matrix_data[row_team][col_team] = f"{flipped_wins}-{flipped_losses}"
                else:
                    matrix_data[row_team][col_team] = "0-0"

    df = pd.DataFrame(matrix_data)
    return df


def _new_all_time_stats_record():
    return {
        'regular_season': {'total_points': 0, 'wins': 0, 'losses': 0, 'ties': 0},
        'playoffs': {'total_points': 0, 'wins': 0, 'losses': 0, 'ties': 0, 'appearances': 0},
        'years_played': 0,
    }


def _merge_all_time_stats_record(target, delta):
    target['regular_season']['wins'] += delta['regular_season']['wins']
    target['regular_season']['losses'] += delta['regular_season']['losses']
    target['regular_season']['ties'] += delta['regular_season']['ties']
    target['regular_season']['total_points'] += delta['regular_season']['total_points']
    target['playoffs']['wins'] += delta['playoffs']['wins']
    target['playoffs']['losses'] += delta['playoffs']['losses']
    target['playoffs']['ties'] += delta['playoffs']['ties']
    target['playoffs']['total_points'] += delta['playoffs']['total_points']
    target['playoffs']['appearances'] += delta['playoffs']['appearances']
    target['years_played'] += delta['years_played']


def _compute_all_time_stats_year(league_id, year, espn_s2, swid):
    """One season's regular-season/playoff deltas per owner - the unit
    calculate_all_time_stats caches to disk forever once that season is over,
    same pattern as build_league_history."""
    year_stats = {}
    try:
        league = League(league_id, year, espn_s2=espn_s2, swid=swid)

        # Get correct playoff start week for this year
        playoff_start_week = get_playoff_start_week(year)
        # ESPN schedules every team into games during "playoff weeks" - the top
        # seeds play the real playoff bracket, everyone else plays a consolation
        # bracket. Only a team's regular-season seed tells us which bracket
        # they're actually in.
        playoff_team_count = getattr(league.settings, 'playoff_team_count', None)

        for team in league.teams:
            owner_name = get_owner_name(team)
            made_playoffs = playoff_team_count is not None and team.standing <= playoff_team_count

            # Calculate regular season and playoff stats
            reg_wins = reg_losses = reg_ties = 0
            reg_points = 0
            playoff_wins = playoff_losses = playoff_ties = 0
            playoff_points = 0

            # Process each completed week's games (skip future/unplayed weeks,
            # which carry 0-0 placeholder scores that would otherwise look like ties)
            for week_num in range(min(len(team.scores), league.current_week)):
                if week_num < len(team.schedule) and team.scores[week_num] is not None:
                    opponent = team.schedule[week_num]
                    if hasattr(opponent, 'scores') and week_num < len(opponent.scores) and opponent.team_id != team.team_id:
                        team_score = team.scores[week_num]
                        opp_score = opponent.scores[week_num]

                        if opp_score is not None:
                            actual_week = week_num + 1
                            # Only bucket a playoff-week game as a "playoff" game if
                            # this team actually qualified; a non-qualifier's playoff-week
                            # game is a consolation-bracket game, which still counts
                            # toward their overall record but not their playoff record.
                            is_real_playoff_game = actual_week >= playoff_start_week and made_playoffs
                            if is_real_playoff_game:
                                playoff_points += team_score
                                if team_score > opp_score:
                                    playoff_wins += 1
                                elif team_score < opp_score:
                                    playoff_losses += 1
                                else:
                                    playoff_ties += 1
                            else:
                                reg_points += team_score
                                if team_score > opp_score:
                                    reg_wins += 1
                                elif team_score < opp_score:
                                    reg_losses += 1
                                else:
                                    reg_ties += 1

            # Skip a season that hasn't started yet (e.g. 2026 in preseason) entirely -
            # a team's seed is meaningless before any games are played, so nothing here
            # (playoff appearances included) should be credited for this team-year
            games_this_year = reg_wins + reg_losses + reg_ties + playoff_wins + playoff_losses + playoff_ties
            if games_this_year == 0:
                continue

            record = year_stats.setdefault(owner_name, _new_all_time_stats_record())
            record['regular_season']['wins'] += reg_wins
            record['regular_season']['losses'] += reg_losses
            record['regular_season']['ties'] += reg_ties
            record['regular_season']['total_points'] += reg_points

            record['playoffs']['wins'] += playoff_wins
            record['playoffs']['losses'] += playoff_losses
            record['playoffs']['ties'] += playoff_ties
            record['playoffs']['total_points'] += playoff_points

            # Count a playoff appearance only if they actually qualified (top N seeds),
            # not merely because they played a game during playoff weeks
            if made_playoffs:
                record['playoffs']['appearances'] += 1

            record['years_played'] += 1

    except Exception as e:
        print(f"Error loading year {year}: {e}")

    return year_stats


def calculate_all_time_stats(league_id, start_year, end_year, espn_s2, swid):
    """Calculate all-time statistics for all teams, separating regular season and
    playoffs. Each year is computed once by _compute_all_time_stats_year and
    cached to disk forever once that season is over (see
    _load_cached_year/_save_cached_year) - only the current, possibly
    still-in-progress year is ever re-fetched from ESPN on a given run."""
    all_time_stats = {}

    for year in range(start_year, end_year + 1):
        year_stats = _load_cached_year('all_time_stats', league_id, year)
        if year_stats is None:
            year_stats = _compute_all_time_stats_year(league_id, year, espn_s2, swid)
            _save_cached_year('all_time_stats', league_id, year, year_stats)

        for owner_name, delta in year_stats.items():
            record = all_time_stats.setdefault(owner_name, _new_all_time_stats_record())
            _merge_all_time_stats_record(record, delta)

    return all_time_stats


def _compute_owner_trend_year(league_id, year, espn_s2, swid):
    """One season's snapshot per owner (final standing, combined W-L-T, total
    points, regular + playoffs) - the unit build_owner_season_trend caches to
    disk forever once that season is over."""
    year_data = {}
    try:
        league = League(league_id, year, espn_s2=espn_s2, swid=swid)

        for team in league.teams:
            owner_name = get_owner_name(team)
            wins = losses = ties = 0
            points = 0.0

            for week_num in range(min(len(team.scores), league.current_week)):
                if week_num < len(team.schedule) and team.scores[week_num] is not None:
                    opponent = team.schedule[week_num]
                    if hasattr(opponent, 'scores') and week_num < len(opponent.scores) and opponent.team_id != team.team_id:
                        team_score = team.scores[week_num]
                        opp_score = opponent.scores[week_num]
                        if opp_score is not None:
                            points += team_score
                            if team_score > opp_score:
                                wins += 1
                            elif team_score < opp_score:
                                losses += 1
                            else:
                                ties += 1

            games = wins + losses + ties
            if games == 0:
                continue  # season hasn't started yet for this team

            season_finalized = getattr(team, 'final_standing', 0) not in (0, None)
            standing = team.final_standing if season_finalized else team.standing

            year_data[owner_name] = {
                'standing': standing, 'wins': wins, 'losses': losses, 'ties': ties,
                'points': round(points, 2),
            }

    except Exception as e:
        print(f"Error loading {year} for owner trend: {e}")

    return year_data


def build_owner_season_trend(league_id, start_year, end_year, espn_s2, swid):
    """Per-owner, per-year snapshot (final standing, combined W-L-T, total
    points) for the Team Overview trend chart - each year computed once by
    _compute_owner_trend_year and cached to disk forever once that season is
    over, same pattern as the other build_* functions.

    Returns {owner: {year: {standing, wins, losses, ties, points}}}."""
    trend = {}
    for year in range(start_year, end_year + 1):
        year_data = _load_cached_year('owner_trend', league_id, year)
        if year_data is None:
            year_data = _compute_owner_trend_year(league_id, year, espn_s2, swid)
            _save_cached_year('owner_trend', league_id, year, year_data)

        for owner, snapshot in year_data.items():
            trend.setdefault(owner, {})[year] = snapshot

    return trend


def _lineup_players(lineup):
    return [
        {
            'name': p.name,
            'position': p.position,
            'slot': p.slot_position,
            'points': p.points,
            'projected': p.projected_points,
            'pro_team': p.proTeam,
        }
        for p in (lineup or [])
    ]


def _compute_season_box_scores(league_id, year, espn_s2, swid):
    """{week: [{home_owner, home_score, home_lineup, away_owner, away_score,
    away_lineup}, ...]} for every week of one season - the full starter+bench
    detail behind every matchup, used for the Matchup History page's
    week-by-week drill-down."""
    weeks = {}
    try:
        league = League(league_id, year, espn_s2=espn_s2, swid=swid)
        for week in range(1, league.current_week + 1):
            try:
                box_scores = league.box_scores(week=week)
            except Exception as e:
                print(f"Error loading box scores {year} week {week}: {e}")
                continue
            matchups = []
            for bs in box_scores:
                if bs.home_team is None or bs.away_team is None:
                    continue
                if bs.home_team.team_id == bs.away_team.team_id:
                    continue  # bye week - ESPN schedules a team against itself
                matchups.append({
                    'home_owner': get_owner_name(bs.home_team),
                    'home_score': bs.home_score,
                    'home_lineup': _lineup_players(bs.home_lineup),
                    'away_owner': get_owner_name(bs.away_team),
                    'away_score': bs.away_score,
                    'away_lineup': _lineup_players(bs.away_lineup),
                })
            weeks[week] = matchups
    except Exception as e:
        print(f"Error loading {year} for season box scores: {e}")

    return weeks


def build_season_box_scores(league_id, year, espn_s2, swid):
    """Disk-cached per-season box scores (see _load_cached_year/_save_cached_year) -
    each season fetched from ESPN once and cached forever after it's final."""
    cached = _load_cached_year('season_box_scores', league_id, year)
    if cached is not None:
        return cached
    data = _compute_season_box_scores(league_id, year, espn_s2, swid)
    _save_cached_year('season_box_scores', league_id, year, data)
    return data


def _new_owner_record():
    return {
        'years': [],
        'total_wins': 0, 'total_losses': 0, 'total_ties': 0,
        'total_points': 0.0,
        'playoff_wins': 0, 'playoff_losses': 0, 'playoff_ties': 0,
        'playoff_appearances': 0,
        'championships': 0,
        'championship_appearances': 0,
        'champion_years': set(),
        'dfl_finishes': 0,
        'dfl_years': set(),
        'bye_weeks': 0,
        'best_record_seasons': 0,
        'best_record_years': set(),
        'most_points_seasons': 0,
        'most_points_years': set(),
        'season_points': {},
        'playoff_years': set(),
        'game_log': [],
    }


def _merge_owner_record(target, delta):
    target['years'].extend(delta['years'])
    target['total_wins'] += delta['total_wins']
    target['total_losses'] += delta['total_losses']
    target['total_ties'] += delta['total_ties']
    target['total_points'] += delta['total_points']
    target['playoff_wins'] += delta['playoff_wins']
    target['playoff_losses'] += delta['playoff_losses']
    target['playoff_ties'] += delta['playoff_ties']
    target['playoff_appearances'] += delta['playoff_appearances']
    target['championships'] += delta['championships']
    target['championship_appearances'] += delta['championship_appearances']
    target['champion_years'] |= delta['champion_years']
    target['dfl_finishes'] += delta['dfl_finishes']
    target['dfl_years'] |= delta['dfl_years']
    target['bye_weeks'] += delta['bye_weeks']
    target['best_record_seasons'] += delta['best_record_seasons']
    target['best_record_years'] |= delta['best_record_years']
    target['most_points_seasons'] += delta['most_points_seasons']
    target['most_points_years'] |= delta['most_points_years']
    target['season_points'].update(delta['season_points'])
    target['playoff_years'] |= delta['playoff_years']
    target['game_log'].extend(delta['game_log'])


def _compute_league_history_year(league_id, year, espn_s2, swid):
    """One season's worth of league-history deltas, keyed by owner name - the unit
    build_league_history caches to disk once a season is over. Same shape as a full
    owner record (see build_league_history's docstring), just scoped to this year."""
    try:
        league = League(league_id, year, espn_s2=espn_s2, swid=swid)
    except Exception as e:
        print(f"Error loading {year}: {e}")
        return {}

    year_owners = {}

    def ensure_owner(name):
        return year_owners.setdefault(name, _new_owner_record())

    playoff_start_week = get_playoff_start_week(year)
    max_week = league.current_week
    # ESPN schedules every team into games during "playoff weeks" - the top
    # seeds play the real playoff bracket, everyone else plays a consolation
    # bracket. Only a team's regular-season seed tells us which bracket they're
    # actually in, so that (not "played a game after playoff_start_week") is
    # what determines a real playoff appearance.
    playoff_team_count = getattr(league.settings, 'playoff_team_count', None)
    # DFL ("Dead F***ing Last") is the worst regular-season-only record for the
    # year, tiebreak by lowest regular-season points - collected across all teams
    # below, then resolved once every team for the year has been processed.
    year_regular_season_records = []
    # Best regular-season record and highest season point total are the mirror
    # image of DFL - same per-team collection, resolved the same way once every
    # team for the year has been processed.
    year_season_points_records = []

    for team in league.teams:
        owner_name = get_owner_name(team)
        made_playoffs = playoff_team_count is not None and team.standing <= playoff_team_count

        season_wins = season_losses = season_ties = 0
        season_playoff_wins = season_playoff_losses = season_playoff_ties = 0
        season_points = 0.0
        reg_only_wins = reg_only_losses = reg_only_ties = 0
        reg_only_points = 0.0
        season_game_log = []

        season_bye_weeks = 0

        for week in range(max_week):
            if week >= len(team.schedule) or week >= len(team.scores):
                continue

            opponent = team.schedule[week]
            team_score = team.scores[week]
            if team_score is None or not hasattr(opponent, 'scores') or week >= len(opponent.scores):
                continue

            # A bye week is represented as a self-matchup (ESPN falls back to the
            # team's own id when it has no opponent) - equal, non-None scores that
            # would otherwise look like a real tie. Skip it entirely: no win/loss/
            # tie, no points, not a real game.
            if opponent.team_id == team.team_id:
                season_bye_weeks += 1
                continue

            opp_score = opponent.scores[week]
            if opp_score is None:
                continue

            actual_week = week + 1
            is_playoff_week = actual_week >= playoff_start_week
            # Only count it as a "playoff game" if this team actually qualified;
            # a non-qualifier's playoff-week game is a consolation-bracket game,
            # which still counts toward their overall record but not their
            # playoff-specific stats.
            is_real_playoff_game = is_playoff_week and made_playoffs

            if team_score > opp_score:
                result = 'W'
            elif team_score < opp_score:
                result = 'L'
            else:
                result = 'T'

            season_points += team_score

            if is_real_playoff_game:
                if result == 'W':
                    season_playoff_wins += 1
                elif result == 'L':
                    season_playoff_losses += 1
                else:
                    season_playoff_ties += 1
            else:
                if result == 'W':
                    season_wins += 1
                elif result == 'L':
                    season_losses += 1
                else:
                    season_ties += 1

            if not is_playoff_week:
                reg_only_points += team_score
                if result == 'W':
                    reg_only_wins += 1
                elif result == 'L':
                    reg_only_losses += 1
                else:
                    reg_only_ties += 1

            season_game_log.append({
                'year': year,
                'week': actual_week,
                'is_playoff': is_real_playoff_game,
                'points': team_score,
                'opp_points': opp_score,
                'opponent': get_owner_name(opponent),
                'result': result,
            })

        games_this_season = season_wins + season_losses + season_ties + \
            season_playoff_wins + season_playoff_losses + season_playoff_ties
        if games_this_season == 0:
            continue  # season hasn't started yet for this team

        if reg_only_wins + reg_only_losses + reg_only_ties > 0:
            year_regular_season_records.append({
                'owner': owner_name,
                'wins': reg_only_wins,
                'points': reg_only_points,
            })
        year_season_points_records.append({
            'owner': owner_name,
            'points': season_points,
        })

        record = ensure_owner(owner_name)
        record['years'].append(year)
        record['bye_weeks'] += season_bye_weeks
        record['total_wins'] += season_wins + season_playoff_wins
        record['total_losses'] += season_losses + season_playoff_losses
        record['total_ties'] += season_ties + season_playoff_ties
        record['total_points'] += season_points
        record['playoff_wins'] += season_playoff_wins
        record['playoff_losses'] += season_playoff_losses
        record['playoff_ties'] += season_playoff_ties
        record['season_points'][year] = season_points
        record['game_log'].extend(season_game_log)

        if made_playoffs:
            record['playoff_appearances'] += 1
            record['playoff_years'].add(year)

        # Only count championships/appearances once ESPN has finalized the season
        season_finalized = getattr(team, 'final_standing', 0) not in (0, None)
        if season_finalized:
            if team.final_standing == 1:
                record['championships'] += 1
                record['championship_appearances'] += 1
                record['champion_years'].add(year)
            elif team.final_standing == 2:
                record['championship_appearances'] += 1

    # Resolve this year's DFL ("Dead F***ing Last"): worst regular-season
    # record, tiebreak by lowest regular-season points. Only once the regular
    # season has actually finished (current_week has reached playoff_start_week) -
    # otherwise an in-progress season would crown a DFL prematurely.
    regular_season_complete = max_week >= playoff_start_week
    if regular_season_complete and year_regular_season_records:
        dfl_entry = min(year_regular_season_records, key=lambda r: (r['wins'], r['points']))
        dfl_record = ensure_owner(dfl_entry['owner'])
        dfl_record['dfl_finishes'] += 1
        dfl_record['dfl_years'].add(year)

        best_entry = max(year_regular_season_records, key=lambda r: (r['wins'], r['points']))
        best_record = ensure_owner(best_entry['owner'])
        best_record['best_record_seasons'] += 1
        best_record['best_record_years'].add(year)

    if year_season_points_records:
        most_points_entry = max(year_season_points_records, key=lambda r: r['points'])
        most_points_record = ensure_owner(most_points_entry['owner'])
        most_points_record['most_points_seasons'] += 1
        most_points_record['most_points_years'].add(year)

    return year_owners


def build_league_history(league_id, start_year, end_year, espn_s2, swid):
    """
    Walk every season and build a per-owner history used for GOAT rankings, league
    records, and trivia. Owner identity (not team name, which changes year to year)
    is the aggregation key throughout. Each year's data is computed once by
    _compute_league_history_year and cached to disk forever once that season is
    over (see _load_cached_year/_save_cached_year) - only the current, possibly
    still-in-progress year is ever re-fetched from ESPN on a given run.

    Each owner entry:
      years: list of years actually played (seasons with 0 completed games are skipped,
             e.g. a season that hasn't started yet)
      total_wins/losses/ties, total_points: regular season + playoffs combined
      playoff_wins/losses/ties, playoff_appearances
      championships, championship_appearances, champion_years: only counted for
             seasons ESPN has finalized (team.final_standing is 0 until a season
             concludes)
      dfl_finishes, dfl_years: worst regular-season record that year (tiebreak by
             lowest regular-season points), only resolved once the regular season
             has actually finished
      best_record_seasons, best_record_years: best regular-season record that year
             (tiebreak by highest regular-season points), same completion gate as DFL
      most_points_seasons, most_points_years: highest single-season point total
             (reg + playoffs) that year
      bye_weeks: total playoff first-round byes across all years
      season_points: {year: points scored that season (reg + playoffs)}
      playoff_years: set of years they made the playoffs
      game_log: list of {year, week, is_playoff, points, opp_points, opponent, result}
             in chronological order, used for streaks and single-game records
    """
    owners = {}

    def ensure_owner(name):
        return owners.setdefault(name, _new_owner_record())

    for year in range(start_year, end_year + 1):
        year_data = _load_cached_year('league_history', league_id, year)
        if year_data is None:
            year_data = _compute_league_history_year(league_id, year, espn_s2, swid)
            _save_cached_year('league_history', league_id, year, year_data)

        for owner_name, delta in year_data.items():
            _merge_owner_record(ensure_owner(owner_name), delta)

    return owners


def load_real_teams_data_full(league_id, year, espn_s2, swid):
    """Load complete team data including players"""
    try:
        league = League(league_id, year, espn_s2=espn_s2, swid=swid)

        teams_data = {}

        for team in league.teams:
            owner_name = get_owner_name(team)

            # Collect player data
            players_list = []
            if hasattr(team, 'roster'):
                for player in team.roster:
                    player_data = {
                        'Player': player.name,
                        'Position': player.position,
                        'Points': player.total_points,
                        'Avg Points': player.avg_points,
                        'Pro Team': player.proTeam if hasattr(player, 'proTeam') else 'FA',
                        'Injury Status': player.injuryStatus if hasattr(player, 'injuryStatus') else 'ACTIVE'
                    }
                    players_list.append(player_data)

            teams_data[owner_name] = {
                'total_points': team.points_for,
                'rank': team.standing,
                'wins': team.wins,
                'losses': team.losses,
                'ties': team.ties if hasattr(team, 'ties') else 0,
                'team_name': team.team_name,
                'players': pd.DataFrame(players_list)
            }

        return teams_data

    except Exception as e:
        st.error(f"Error loading team data: {str(e)}")
        return {}


def get_current_season_snapshot(league_id, year, espn_s2, swid):
    """Live standings + rosters for the home page's award/playoff race widgets.
    Always freshly fetched, never disk-cached - by definition the current season is
    still in progress, so yesterday's snapshot would be stale by tomorrow. Distinct
    from load_real_teams_data_full (which returns a pandas DataFrame per team,
    built for the Team Overview/Player Analysis pages) so home_stats.py can stay
    pandas-free like the other *_stats.py computation modules."""
    try:
        league = League(league_id, year, espn_s2=espn_s2, swid=swid)
    except Exception as e:
        st.error(f"Error loading current season data: {str(e)}")
        return {'teams': {}, 'playoff_team_count': None, 'current_week': 0, 'season_started': False}

    teams_data = {}
    games_played_total = 0
    for team in league.teams:
        owner_name = get_owner_name(team)
        ties = getattr(team, 'ties', 0)
        games_played_total += team.wins + team.losses + ties

        players = [
            {
                'player': player.name,
                'position': player.position,
                'points': player.total_points,
                'avg_points': player.avg_points,
                'pro_team': getattr(player, 'proTeam', 'FA'),
                'injury_status': getattr(player, 'injuryStatus', 'ACTIVE'),
            }
            for player in getattr(team, 'roster', [])
        ]

        teams_data[owner_name] = {
            'team_name': team.team_name,
            'wins': team.wins,
            'losses': team.losses,
            'ties': ties,
            'points_for': team.points_for,
            'standing': team.standing,
            'players': players,
        }

    return {
        'teams': teams_data,
        'playoff_team_count': getattr(league.settings, 'playoff_team_count', 6),
        'current_week': league.current_week,
        'season_started': games_played_total > 0,
    }


def get_active_player_ids(league_id, year, espn_s2, swid, candidate_ids, min_projected_points=100.0):
    """Which of candidate_ids are still real, fantasy-RELEVANT NFL players as of
    `year` - a retired/unsigned player still exists in ESPN's historical data
    (player_info still returns a Player object for them) but has no current pro
    team and a zero projection, since ESPN doesn't project players nobody could
    actually roster. min_projected_points goes a step further than just
    "has a pro team": a deep waiver-tier player can have a real team and a
    nonzero-but-tiny projection (a backup kicker projected for 30 points on the
    season) without being anyone's actual draft-day consideration, so the floor
    keeps this to players someone would plausibly draft, not just anyone still
    employed by an NFL team. Used to filter the Do Not Draft List. Batches the
    lookup in chunks since player_info's underlying request has an unconfirmed
    size limit - better to make a few requests than risk one huge one failing
    outright."""
    try:
        league = League(league_id, year, espn_s2=espn_s2, swid=swid)
    except Exception as e:
        print(f"Error loading {year} for active-player lookup: {e}")
        return set()

    active_ids = set()
    candidate_ids = list(candidate_ids)
    chunk_size = 100
    for i in range(0, len(candidate_ids), chunk_size):
        chunk = candidate_ids[i:i + chunk_size]
        try:
            result = league.player_info(playerId=chunk)
        except Exception as e:
            print(f"Error looking up players {i}-{i + chunk_size} for {year}: {e}")
            continue
        if result is None:
            continue
        players = result if isinstance(result, list) else [result]
        for p in players:
            if p.proTeam not in (None, 'None', 'FA') and p.projected_total_points >= min_projected_points:
                active_ids.add(p.playerId)

    return active_ids


def _optimal_lineup_ids(players, dedicated_slots, flex_slots):
    """Given a team's available players for one week (starters + bench, excluding IR)
    and the league's slot structure, return the set of player ids that would have
    maximized total points that week: fill each dedicated position slot with the top
    scorers at that exact position, then fill flex slots from the best leftover skill
    player. This greedy order is optimal for this slot structure - every flex-eligible
    position already got its best players placed in its own dedicated slots first, so
    the flex slot just needs the single best player left in the pool."""
    by_position = {}
    for p in players:
        by_position.setdefault(p.position, []).append(p)
    for plist in by_position.values():
        plist.sort(key=lambda p: p.points, reverse=True)

    used_ids = set()
    for slot, count in dedicated_slots:
        pool = by_position.get(slot, [])
        for p in pool[:count]:
            used_ids.add(p.playerId)
        by_position[slot] = pool[count:]

    for slot, count in flex_slots:
        eligible_positions = slot.split('/')
        leftover = [p for pos in eligible_positions for p in by_position.get(pos, [])]
        leftover.sort(key=lambda p: p.points, reverse=True)
        for p in leftover[:count]:
            used_ids.add(p.playerId)
            by_position[p.position].remove(p)

    return used_ids


def _new_gm_record():
    return {'picks': [], 'acquisitions': []}


def _new_coach_record():
    return {
        'correct_calls': 0, 'total_calls': 0,
        'actual_points': 0.0, 'optimal_points': 0.0,
        'weekly_log': [],
    }


def _new_luck_record():
    return {'boom_wins': 0, 'games_played': 0}


def _compute_front_office_year(league_id, year, espn_s2, swid):
    """
    One season's worth of GM/Coach deltas plus that year's draft log - the unit
    build_front_office_history caches to disk once a season is over. This is a much
    heavier pull than a single _compute_league_history_year call (~50 extra API
    calls for the weekly box scores), which is exactly why caching it per-year
    matters most here.

    Returns (gm_year, coach_year, draft_year_log), each scoped to just this year:

    gm_year[owner] = {
      'picks': [{year, player_id, player_name, position, round_num, round_pick,
                 total_actual, total_projected, value (actual - projected), scale,
                 weeks_rostered, ir_weeks,
                 weekly: [{week, actual, projected, slot, owner}, ...]}, ...],
      'acquisitions': [{year, player_id, player_name, position,
                         total_actual, total_projected, value, scale,
                         weeks_rostered, ir_weeks, weekly: [...]}, ...]
    }
    Each drafted player who actually played a game that season becomes a 'picks'
    entry, value tracked only for the weeks that specific player was actually on the
    DRAFTING owner's roster (checked week by week, not summed for the whole season) -
    a bust traded or dropped in week 3 stops counting against the original drafter
    the moment it leaves. Every OTHER player-owner pairing that season (a trade
    acquisition or a waiver/free-agent pickup - this league's transaction log doesn't
    reliably distinguish the two, see below) becomes an 'acquisitions' entry for
    whoever actually rostered them, valued the same way. Being good at trading or
    working the waiver wire is part of being a good GM, so acquisitions become
    additional decisions alongside draft picks when the GM score gets computed (see
    front_office_stats.py). (ESPN's trade-transaction log was tried first, but its
    own "TRADE_PROPOSAL" records show 'PENDING' status even for trades confirmed, by
    checking actual roster movement, to have gone through - not reliable enough to
    isolate trades specifically, so acquisitions are judged as a whole instead.)

    coach_year[owner] = {
      'correct_calls': int, 'total_calls': int,
      'actual_points': float, 'optimal_points': float,
      'weekly_log': [{year, week, owner, correct, total, points_left}, ...]
    }
    "Optimal" is computed directly from ESPN's own roster slot data for that specific
    week (BoxPlayer.slot_position) - not reverse-engineered from score totals - so
    ties/bye-weeks/injuries are all handled exactly as ESPN recorded them that week.

    draft_year_log = [{year, player_id, player_name}, ...] - every draft pick made
    this year, regardless of whether that player ever played a game (unlike
    gm_year['picks'], which only includes picks that did), for draft-frequency trivia.

    luck_year[owner] = {'boom_wins': int, 'games_played': int}
    A "boom win" is a win where the owner's own starters' PROJECTED total was
    actually below what their opponent ACTUALLY scored - on paper they should
    have lost that game, so winning it anyway means an unexpected overperformance
    (a boom) bailed them out. Computed once per real head-to-head game (skips
    byes, where ESPN gives a team a self-matchup) alongside the coach-stats pass
    below, from the same box-score data, so it costs no extra API calls.

    Returns ({}, {}, [], {}) for a year with no completed draft yet or that
    hasn't started (e.g. 2026 in preseason) - build_front_office_history skips
    those.
    """
    gm_year = {}
    coach_year = {}
    draft_year_log = []
    luck_year = {}

    def ensure_gm(owner):
        return gm_year.setdefault(owner, _new_gm_record())

    def ensure_coach(owner):
        return coach_year.setdefault(owner, _new_coach_record())

    def ensure_luck(owner):
        return luck_year.setdefault(owner, _new_luck_record())

    try:
        league = League(league_id, year, espn_s2=espn_s2, swid=swid)
    except Exception as e:
        print(f"Error loading {year}: {e}")
        return {}, {}, [], {}

    if not league.draft or league.current_week == 0:
        return {}, {}, [], {}  # no draft recorded yet, or season hasn't started

    slot_counts = league.settings.position_slot_counts
    # 'D/ST' is a single dedicated position despite the slash in its name - the
    # real multi-position flex slots are the only other slash-containing keys.
    dedicated_slots = [(slot, count) for slot, count in slot_counts.items()
                        if count > 0 and slot not in ('BE', 'IR', '') and ('/' not in slot or slot == 'D/ST')]
    flex_slots = [(slot, count) for slot, count in slot_counts.items()
                  if count > 0 and '/' in slot and slot != 'D/ST']

    draft_by_player = {
        pick.playerId: {
            'owner': get_owner_name(pick.team),
            'round_num': pick.round_num,
            'round_pick': pick.round_pick,
        }
        for pick in league.draft
    }
    for pick in league.draft:
        draft_year_log.append({'year': year, 'player_id': pick.playerId, 'player_name': pick.playerName})

    # player_id -> accumulated actual/projected/weeks while rostered, this season
    player_season = {}

    for week in range(1, league.current_week + 1):
        try:
            box_scores = league.box_scores(week=week)
        except Exception as e:
            print(f"Error loading box scores {year} week {week}: {e}")
            continue

        for bs in box_scores:
            # Boom-win detection - kept independent of the per-team loop below
            # (which processes each side without visibility into the other) since
            # it needs BOTH sides' starter totals at once to know what "should
            # have happened" on paper. A bye is a self-matchup (ESPN gives a team
            # its own id as the opponent), which the team_id check excludes.
            home_lineup, away_lineup = bs.home_lineup or [], bs.away_lineup or []
            if (bs.home_team is not None and bs.away_team is not None
                    and home_lineup and away_lineup
                    and bs.home_team.team_id != bs.away_team.team_id):
                home_starters = [p for p in home_lineup if p.slot_position not in ('BE', 'IR')]
                away_starters = [p for p in away_lineup if p.slot_position not in ('BE', 'IR')]
                home_actual = sum(p.points for p in home_starters)
                away_actual = sum(p.points for p in away_starters)
                home_projected = sum(p.projected_points for p in home_starters)
                away_projected = sum(p.projected_points for p in away_starters)

                for team, own_actual, own_projected, opp_actual in (
                    (bs.home_team, home_actual, home_projected, away_actual),
                    (bs.away_team, away_actual, away_projected, home_actual),
                ):
                    luck = ensure_luck(get_owner_name(team))
                    luck['games_played'] += 1
                    if own_actual > opp_actual and own_projected < opp_actual:
                        luck['boom_wins'] += 1

            for team, lineup in ((bs.home_team, bs.home_lineup), (bs.away_team, bs.away_lineup)):
                if team is None or not lineup:
                    continue
                owner = get_owner_name(team)

                starters = [p for p in lineup if p.slot_position not in ('BE', 'IR')]
                bench = [p for p in lineup if p.slot_position == 'BE']
                available = starters + bench

                optimal_ids = _optimal_lineup_ids(available, dedicated_slots, flex_slots)
                actual_ids = {p.playerId for p in starters}
                week_actual_points = sum(p.points for p in starters)
                week_optimal_points = sum(p.points for p in available if p.playerId in optimal_ids)

                coach = ensure_coach(owner)
                coach['correct_calls'] += len(actual_ids & optimal_ids)
                coach['total_calls'] += len(starters)
                coach['actual_points'] += week_actual_points
                coach['optimal_points'] += week_optimal_points
                coach['weekly_log'].append({
                    'year': year, 'week': week, 'owner': owner,
                    'correct': len(actual_ids & optimal_ids), 'total': len(starters),
                    'points_left': week_optimal_points - week_actual_points,
                })

                for p in lineup:
                    entry = player_season.setdefault(p.playerId, {
                        'name': p.name, 'position': p.position,
                        'total_actual': 0.0, 'total_projected': 0.0,
                        'weeks_rostered': 0, 'ir_weeks': 0, 'weekly': [],
                    })
                    entry['total_actual'] += p.points
                    entry['total_projected'] += p.projected_points
                    entry['weeks_rostered'] += 1
                    if p.slot_position == 'IR':
                        entry['ir_weeks'] += 1
                    entry['weekly'].append({
                        'week': week, 'actual': p.points, 'projected': p.projected_points,
                        'slot': p.slot_position, 'owner': owner,
                    })

    for player_id, entry in player_season.items():
        pick = draft_by_player.get(player_id)
        drafting_owner = pick['owner'] if pick else None

        # A player can pass through more than one roster in a season (waiver
        # pickup, or a trade - which, since it isn't reliably confirmable from
        # this league's transaction log, just falls out of the roster data the
        # same way any other acquisition does). Group this player's weeks by
        # whoever actually had them, so each owner is judged only on the weeks
        # they controlled that roster spot.
        weeks_by_owner = {}
        for w in entry['weekly']:
            weeks_by_owner.setdefault(w['owner'], []).append(w)

        for owner, owner_weeks in weeks_by_owner.items():
            total_actual = sum(w['actual'] for w in owner_weeks)
            total_projected = sum(w['projected'] for w in owner_weeks)
            ir_weeks = sum(1 for w in owner_weeks if w['slot'] == 'IR')

            decision = {
                'year': year,
                'player_id': player_id,
                'player_name': entry['name'],
                'position': entry['position'],
                'total_actual': total_actual,
                'total_projected': total_projected,
                'value': total_actual - total_projected,
                'scale': total_projected,  # classification denominator - see front_office_stats.py
                'weeks_rostered': len(owner_weeks),
                'ir_weeks': ir_weeks,
                'weekly': owner_weeks,
            }

            gm = ensure_gm(owner)
            if owner == drafting_owner:
                decision['round_num'] = pick['round_num']
                decision['round_pick'] = pick['round_pick']
                gm['picks'].append(decision)
            else:
                gm['acquisitions'].append(decision)

    return gm_year, coach_year, draft_year_log, luck_year


def build_front_office_history(league_id, start_year, end_year, espn_s2, swid):
    """
    Walk every season's draft plus every week's box scores to build two owner-keyed
    histories plus a flat draft log. Each year's data is computed once by
    _compute_front_office_year and cached to disk forever once that season is over
    (see _load_cached_year/_save_cached_year) - only the current, possibly
    still-in-progress year is ever re-fetched from ESPN on a given run. This is a
    much heavier pull than build_league_history (~50 extra API calls per season for
    the weekly box scores), which is exactly why per-year caching matters most here;
    it's meant to be used lazily, only for the Front Office page.

    gm_history[owner] = {
      'picks': [{year, player_id, player_name, position, round_num, round_pick,
                 total_actual, total_projected, value (actual - projected), scale,
                 weeks_rostered, ir_weeks,
                 weekly: [{week, actual, projected, slot, owner}, ...]}, ...],
      'acquisitions': [{year, player_id, player_name, position,
                         total_actual, total_projected, value, scale,
                         weeks_rostered, ir_weeks, weekly: [...]}, ...]
    }
    Each drafted player who actually played a game that season becomes a 'picks'
    entry, value tracked only for the weeks that specific player was actually on the
    DRAFTING owner's roster (checked week by week, not summed for the whole season) -
    a bust traded or dropped in week 3 stops counting against the original drafter
    the moment it leaves. Every OTHER player-owner pairing that season (a trade
    acquisition or a waiver/free-agent pickup - this league's transaction log doesn't
    reliably distinguish the two) becomes an 'acquisitions' entry for whoever
    actually rostered them, valued the same way.

    coach_history[owner] = {
      'correct_calls': int, 'total_calls': int,
      'actual_points': float, 'optimal_points': float,
      'weekly_log': [{year, week, owner, correct, total, points_left}, ...]
    }

    luck_history[owner] = {'boom_wins': int, 'games_played': int} - see
    _compute_front_office_year for what a "boom win" is.

    draft_log = [{year, player_id, player_name}, ...] - every draft pick ever made,
    regardless of whether that player ever played a game.

    Only years with an actual completed draft and at least one played week are
    included (skips a season that hasn't drafted/started yet, e.g. 2026 in preseason).
    """
    gm_history = {}
    coach_history = {}
    draft_log = []
    luck_history = {}

    def ensure_gm(owner):
        return gm_history.setdefault(owner, _new_gm_record())

    def ensure_coach(owner):
        return coach_history.setdefault(owner, _new_coach_record())

    def ensure_luck(owner):
        return luck_history.setdefault(owner, _new_luck_record())

    for year in range(start_year, end_year + 1):
        year_data = _load_cached_year('front_office', league_id, year)
        if year_data is None:
            year_data = _compute_front_office_year(league_id, year, espn_s2, swid)
            _save_cached_year('front_office', league_id, year, year_data)
        gm_year, coach_year, draft_year_log, luck_year = year_data

        for owner, delta in gm_year.items():
            gm = ensure_gm(owner)
            gm['picks'].extend(delta['picks'])
            gm['acquisitions'].extend(delta['acquisitions'])

        for owner, delta in coach_year.items():
            coach = ensure_coach(owner)
            coach['correct_calls'] += delta['correct_calls']
            coach['total_calls'] += delta['total_calls']
            coach['actual_points'] += delta['actual_points']
            coach['optimal_points'] += delta['optimal_points']
            coach['weekly_log'].extend(delta['weekly_log'])

        for owner, delta in luck_year.items():
            luck = ensure_luck(owner)
            luck['boom_wins'] += delta['boom_wins']
            luck['games_played'] += delta['games_played']

        draft_log.extend(draft_year_log)

    return gm_history, coach_history, draft_log, luck_history
