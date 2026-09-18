"""Postgres (Supabase) data-access layer - same architectural role
espn_data.py plays for the ESPN API: this module owns every read/write to the
database, nothing else touches psycopg2 directly. See schema.sql for the DDL
and /Users/qhall/.claude/plans/mellow-mapping-brook.md for the full migration
design this implements.

sync_season() is the one idempotent sync/backfill function - it re-upserts a
whole season every time it runs (never tries to detect "just the new week",
since ESPN sometimes corrects a stat after a week closes and the underlying
fetch is already fast/parallel/idempotent). ensure_synced() is the
sync-if-stale check every page calls before reading: compare the DB's
synced_through_week against the live current week, sync inline under a
spinner if behind, then every read function below just queries Postgres.
"""

import concurrent.futures
import uuid
from contextlib import contextmanager
from datetime import datetime

import pandas as pd

import psycopg2
import psycopg2.extras
import psycopg2.pool
import streamlit as st
from espn_api.football import League

psycopg2.extras.register_uuid()

from espn_data import (
    _last_completed_week,
    _slot_structure_from_league,
    get_owner_name,
    get_playoff_start_week,
)

# ESPN's recent_activity() action strings -> this schema's roster_moves.kind
# (see espn_data.get_recent_activity's docstring for the same enumeration -
# TRADE_SENT/TRADE_RECEIVED are handled separately below, not through this map).
ACTION_KIND_MAP = {
    'FA ADDED': 'fa_add',
    'WAIVER ADDED': 'waiver_add',
    'DROPPED': 'drop',
}


@st.cache_resource
def _get_pool():
    return psycopg2.pool.ThreadedConnectionPool(1, 5, st.secrets["supabase_db_url"])


@contextmanager
def _cursor(commit=False):
    """One connection from the process-wide pool, one cursor. Callers that
    need several statements to land atomically (sync_season) pass
    commit=True and do all their work inside the `with` block; everything
    else defaults to autocommit-style single-statement reads."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def ensure_league(espn_league_id, name=None):
    """Insert-or-fetch this league's internal id - the tenant key every
    other table hangs off. Safe to call every time; a no-op after the first."""
    with _cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO leagues (espn_league_id, name) VALUES (%s, %s)
            ON CONFLICT (platform, espn_league_id)
                DO UPDATE SET name = COALESCE(EXCLUDED.name, leagues.name)
            RETURNING id
            """,
            (espn_league_id, name),
        )
        return cur.fetchone()[0]


def _ensure_owner(cur, league_id, display_name, cache):
    """Insert-or-fetch one owner, memoized in `cache` (a plain dict passed in
    by the caller) so one sync_season call doesn't re-query the same owner
    dozens of times across a season's worth of games/player_weeks."""
    if display_name in cache:
        return cache[display_name]
    cur.execute(
        """
        INSERT INTO owners (league_id, display_name) VALUES (%s, %s)
        ON CONFLICT (league_id, display_name) DO NOTHING
        """,
        (league_id, display_name),
    )
    cur.execute(
        "SELECT id FROM owners WHERE league_id = %s AND display_name = %s",
        (league_id, display_name),
    )
    owner_id = cur.fetchone()[0]
    cache[display_name] = owner_id
    return owner_id


def _ensure_players(cur, players):
    """Bulk upsert (id, name, position) triples - players is a dict
    {player_id: (name, position)}. Called once per sync_season with
    everything seen that season, instead of one round trip per player."""
    if not players:
        return
    rows = [(pid, name, pos) for pid, (name, pos) in players.items()]
    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO players (id, name, position) VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            name = EXCLUDED.name, position = EXCLUDED.position, updated_at = now()
        """,
        rows,
    )


def _sync_roster_moves(cur, league, league_id, year, owner_cache):
    """Persists league.recent_activity()'s reliably-typed trade/waiver/drop
    data - a zero-extra-I/O side effect of a call already being made live
    elsewhere in the app. Wrapped independently from the rest of sync_season:
    this endpoint is a rolling recent-only window (not a full historical log,
    see schema.sql's roster_moves comment), so it's expected to return little
    or nothing useful for old seasons - that's fine, never worth failing the
    whole sync over."""
    try:
        activities = league.recent_activity(size=100)
    except Exception as e:
        print(f"roster_moves sync skipped for {year}: {e}")
        return

    rows = []
    move_players = {}  # player_id -> name, for players not seen elsewhere this sync
    for act in activities:
        occurred_at = datetime.fromtimestamp(act.date / 1000.0)
        sent = [(team, player) for team, action, player, _bid in act.actions if action == 'TRADE_SENT']
        received = [(team, player) for team, action, player, _bid in act.actions if action == 'TRADE_RECEIVED']

        if sent and received:
            teams_in_trade = list(dict.fromkeys(team for team, _ in sent))
            if len(teams_in_trade) != 2:
                continue  # only ever seen 2-team trades in this league's data - skip anything stranger
            team_a, team_b = teams_in_trade
            trade_group_id = uuid.uuid4()
            owner_a = _ensure_owner(cur, league_id, get_owner_name(team_a), owner_cache)
            owner_b = _ensure_owner(cur, league_id, get_owner_name(team_b), owner_cache)
            for team, player in sent:
                sender, counterparty = (owner_a, owner_b) if team == team_a else (owner_b, owner_a)
                move_players[player.playerId] = player.name
                rows.append((league_id, year, occurred_at, 'trade', sender, counterparty,
                             player.playerId, None, trade_group_id))
            continue

        for team, action, player, bid_amount in act.actions:
            kind = ACTION_KIND_MAP.get(action)
            if not team or kind is None:
                continue
            owner_id = _ensure_owner(cur, league_id, get_owner_name(team), owner_cache)
            move_players[player.playerId] = player.name
            rows.append((league_id, year, occurred_at, kind, owner_id, None,
                        player.playerId, bid_amount, None))

    if not rows:
        return
    # players referenced here might not appear anywhere else this sync (e.g.
    # a player dropped before ever starting a game) - upsert a bare name-only
    # row for each so the roster_moves FK never fails.
    _ensure_players(cur, {pid: (name, None) for pid, name in move_players.items()})
    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO roster_moves
            (league_id, year, occurred_at, kind, owner_id, counterparty_owner_id,
             player_id, bid_amount, trade_group_id)
        VALUES %s
        ON CONFLICT (league_id, occurred_at, owner_id, player_id, kind) DO NOTHING
        """,
        rows,
    )


def sync_season(espn_league_id, year, espn_s2, swid, league=None):
    """Re-syncs one league-year end to end: seasons, owners, season_teams
    (with resolved champion/DFL/best-record/most-points flags), games,
    player_weeks, draft_picks, and roster_moves. Idempotent - safe to call
    repeatedly, always re-upserts the full season rather than trying to
    detect what's new. `league` lets a caller that already constructed one
    (ensure_synced) pass it in instead of fetching twice."""
    if league is None:
        league = League(espn_league_id, year, espn_s2=espn_s2, swid=swid)

    league_id = ensure_league(espn_league_id)
    playoff_start_week = get_playoff_start_week(year)
    playoff_team_count = getattr(league.settings, 'playoff_team_count', None)
    last_week = _last_completed_week(league, year)
    regular_season_complete = last_week >= playoff_start_week
    dedicated_slots, flex_slots = _slot_structure_from_league(league)
    scoring_settings = {
        str(item['id']): item['points']
        for item in getattr(league.settings, 'scoring_format', [])
    }

    owner_cache = {}
    players_seen = {}  # player_id -> (name, position)
    game_rows = []
    player_week_rows = []
    draft_rows = []

    # --- Per-week box scores (concurrent fetch, same proven-safe pattern as
    # espn_data._compute_season_box_scores/_compute_front_office_year) -----
    def _fetch_week(week):
        try:
            return week, league.box_scores(week=week)
        except Exception as e:
            print(f"Error loading box scores {year} week {week}: {e}")
            return week, []

    box_scores_by_week = {}
    if last_week >= 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(last_week, 8)) as executor:
            for week, box_scores in executor.map(_fetch_week, range(1, last_week + 1)):
                box_scores_by_week[week] = box_scores

    with _cursor(commit=True) as cur:
        # owners first, from league.teams (covers everyone with a roster this
        # season even if a bye or an unplayed week means they don't show up
        # in every week's box scores)
        for team in league.teams:
            _ensure_owner(cur, league_id, get_owner_name(team), owner_cache)

        actual_week_is_playoff_week = lambda w: (w + 1) >= playoff_start_week  # noqa: E731

        for week in range(1, last_week + 1):
            is_playoff_week = actual_week_is_playoff_week(week - 1)
            for bs in box_scores_by_week.get(week, []):
                if bs.home_team is None or bs.away_team is None:
                    continue
                if bs.home_team.team_id == bs.away_team.team_id:
                    continue  # bye week - ESPN schedules a team against itself

                home_owner = _ensure_owner(cur, league_id, get_owner_name(bs.home_team), owner_cache)
                away_owner = _ensure_owner(cur, league_id, get_owner_name(bs.away_team), owner_cache)

                home_made_playoffs = playoff_team_count is not None and bs.home_team.standing <= playoff_team_count
                away_made_playoffs = playoff_team_count is not None and bs.away_team.standing <= playoff_team_count
                is_playoff = is_playoff_week and home_made_playoffs and away_made_playoffs

                if bs.home_score > bs.away_score:
                    winner = home_owner
                elif bs.away_score > bs.home_score:
                    winner = away_owner
                else:
                    winner = None

                game_rows.append((
                    league_id, year, week, is_playoff,
                    home_owner, bs.home_score, away_owner, bs.away_score, winner,
                ))

                for owner_id, lineup in ((home_owner, bs.home_lineup), (away_owner, bs.away_lineup)):
                    for p in (lineup or []):
                        players_seen[p.playerId] = (p.name, p.position)
                        player_week_rows.append((
                            league_id, year, week, p.playerId, owner_id,
                            p.position, p.slot_position, getattr(p, 'proTeam', None),
                            p.points, p.projected_points,
                        ))

        # --- Draft picks -----------------------------------------------------
        try:
            for pick in league.draft:
                owner_id = _ensure_owner(cur, league_id, get_owner_name(pick.team), owner_cache)
                players_seen.setdefault(pick.playerId, (pick.playerName, None))
                draft_rows.append((league_id, year, pick.playerId, owner_id, pick.round_num, pick.round_pick))
        except Exception as e:
            print(f"Draft sync skipped for {year}: {e}")

        # --- season_teams: bulk team.schedule/.scores walk, same source and
        # tiebreak logic as espn_data._compute_league_history_year, just
        # written to a row instead of an in-memory dict --------------------
        regular_records = []  # for DFL/best-record tiebreak: {'owner_id','wins','points'}
        points_records = []   # for most-points tiebreak

        season_team_rows = []
        for team in league.teams:
            owner_id = _ensure_owner(cur, league_id, get_owner_name(team), owner_cache)
            made_playoffs = playoff_team_count is not None and team.standing <= playoff_team_count
            wins = losses = ties = bye_weeks = 0
            points_for = 0.0
            reg_wins = reg_losses = reg_ties = 0
            reg_points = 0.0

            for week in range(last_week):
                if week >= len(team.schedule) or week >= len(team.scores):
                    continue
                opponent = team.schedule[week]
                team_score = team.scores[week]
                if team_score is None or not hasattr(opponent, 'scores') or week >= len(opponent.scores):
                    continue
                if opponent.team_id == team.team_id:
                    bye_weeks += 1
                    continue
                opp_score = opponent.scores[week]
                if opp_score is None:
                    continue

                if team_score > opp_score:
                    wins += 1
                elif team_score < opp_score:
                    losses += 1
                else:
                    ties += 1
                points_for += team_score

                if not actual_week_is_playoff_week(week):
                    reg_points += team_score
                    if team_score > opp_score:
                        reg_wins += 1
                    elif team_score < opp_score:
                        reg_losses += 1
                    else:
                        reg_ties += 1

            season_finalized = getattr(team, 'final_standing', 0) not in (0, None)
            is_champion = season_finalized and team.final_standing == 1
            is_runner_up = season_finalized and team.final_standing == 2

            if reg_wins + reg_losses + reg_ties > 0:
                regular_records.append({'owner_id': owner_id, 'wins': reg_wins, 'points': reg_points})
            if wins + losses + ties > 0:
                points_records.append({'owner_id': owner_id, 'points': points_for})

            season_team_rows.append([
                league_id, year, owner_id, team.team_id, team.team_name,
                wins, losses, ties, points_for,
                team.standing, team.final_standing, made_playoffs,
                is_champion, is_runner_up,
                False, False, False,  # is_dfl / is_best_record / is_most_points, resolved below
                bye_weeks,
            ])

        if regular_season_complete and regular_records:
            dfl_owner = min(regular_records, key=lambda r: (r['wins'], r['points']))['owner_id']
            best_owner = max(regular_records, key=lambda r: (r['wins'], r['points']))['owner_id']
            for row in season_team_rows:
                if row[2] == dfl_owner:
                    row[13] = True
                if row[2] == best_owner:
                    row[14] = True
        if points_records:
            most_points_owner = max(points_records, key=lambda r: r['points'])['owner_id']
            for row in season_team_rows:
                if row[2] == most_points_owner:
                    row[15] = True

        # --- Write everything ------------------------------------------------
        cur.execute(
            """
            INSERT INTO seasons
                (league_id, year, playoff_start_week, playoff_team_count,
                 scoring_settings, dedicated_slots, flex_slots, is_final,
                 synced_through_week, last_synced_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (league_id, year) DO UPDATE SET
                playoff_start_week = EXCLUDED.playoff_start_week,
                playoff_team_count = EXCLUDED.playoff_team_count,
                scoring_settings = EXCLUDED.scoring_settings,
                dedicated_slots = EXCLUDED.dedicated_slots,
                flex_slots = EXCLUDED.flex_slots,
                is_final = EXCLUDED.is_final,
                synced_through_week = EXCLUDED.synced_through_week,
                last_synced_at = now()
            """,
            (league_id, year, playoff_start_week, playoff_team_count,
             psycopg2.extras.Json(scoring_settings),
             psycopg2.extras.Json(dedicated_slots), psycopg2.extras.Json(flex_slots),
             year < datetime.now().year, last_week),
        )

        _ensure_players(cur, players_seen)

        if season_team_rows:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO season_teams
                    (league_id, year, owner_id, espn_team_id, team_name,
                     wins, losses, ties, points_for, standing, final_standing,
                     made_playoffs, is_champion, is_runner_up, is_dfl,
                     is_best_record, is_most_points, bye_weeks)
                VALUES %s
                ON CONFLICT (league_id, year, owner_id) DO UPDATE SET
                    espn_team_id = EXCLUDED.espn_team_id, team_name = EXCLUDED.team_name,
                    wins = EXCLUDED.wins, losses = EXCLUDED.losses, ties = EXCLUDED.ties,
                    points_for = EXCLUDED.points_for, standing = EXCLUDED.standing,
                    final_standing = EXCLUDED.final_standing, made_playoffs = EXCLUDED.made_playoffs,
                    is_champion = EXCLUDED.is_champion, is_runner_up = EXCLUDED.is_runner_up,
                    is_dfl = EXCLUDED.is_dfl, is_best_record = EXCLUDED.is_best_record,
                    is_most_points = EXCLUDED.is_most_points, bye_weeks = EXCLUDED.bye_weeks
                """,
                season_team_rows,
            )

        if game_rows:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO games
                    (league_id, year, week, is_playoff, home_owner_id, home_score,
                     away_owner_id, away_score, winner_owner_id)
                VALUES %s
                ON CONFLICT (league_id, year, week, home_owner_id, away_owner_id) DO UPDATE SET
                    is_playoff = EXCLUDED.is_playoff, home_score = EXCLUDED.home_score,
                    away_score = EXCLUDED.away_score, winner_owner_id = EXCLUDED.winner_owner_id
                """,
                game_rows,
            )

        if player_week_rows:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO player_weeks
                    (league_id, year, week, player_id, owner_id, position, slot,
                     pro_team, actual_points, projected_points)
                VALUES %s
                ON CONFLICT (league_id, year, week, player_id) DO UPDATE SET
                    owner_id = EXCLUDED.owner_id, position = EXCLUDED.position,
                    slot = EXCLUDED.slot, pro_team = EXCLUDED.pro_team,
                    actual_points = EXCLUDED.actual_points,
                    projected_points = EXCLUDED.projected_points
                """,
                player_week_rows,
            )

        if draft_rows:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO draft_picks (league_id, year, player_id, owner_id, round_num, round_pick)
                VALUES %s
                ON CONFLICT (league_id, year, player_id) DO UPDATE SET
                    owner_id = EXCLUDED.owner_id, round_num = EXCLUDED.round_num,
                    round_pick = EXCLUDED.round_pick
                """,
                draft_rows,
            )

        _sync_roster_moves(cur, league, league_id, year, owner_cache)

    return {
        'games': len(game_rows), 'player_weeks': len(player_week_rows),
        'draft_picks': len(draft_rows), 'players': len(players_seen),
        'last_week': last_week,
    }


def ensure_synced(espn_league_id, year, espn_s2, swid):
    """Sync-if-stale: called once per session per (league, year) before any
    page reads from the DB. Cheap when already caught up (one lightweight
    League() construction to read the live current week, one indexed
    lookup) - only pays the real sync cost when the DB is actually behind."""
    session_key = f'db_synced_{espn_league_id}_{year}'
    if st.session_state.get(session_key):
        return

    try:
        league = League(espn_league_id, year, espn_s2=espn_s2, swid=swid)
        target_week = _last_completed_week(league, year)
    except Exception as e:
        print(f"ensure_synced: couldn't check live state for {year}: {e}")
        st.session_state[session_key] = True
        return

    with _cursor() as cur:
        cur.execute(
            """
            SELECT s.synced_through_week FROM seasons s
            JOIN leagues l ON l.id = s.league_id
            WHERE l.espn_league_id = %s AND s.year = %s
            """,
            (espn_league_id, year),
        )
        row = cur.fetchone()
    synced_through = row[0] if row else -1

    if synced_through < target_week:
        with st.spinner(f"Syncing {year} season data..."):
            sync_season(espn_league_id, year, espn_s2, swid, league=league)

    st.session_state[session_key] = True


# --- Read functions (page migrations) ---------------------------------------
# Each of these reassembles the exact shape the page/consuming *_stats.py
# function already expects, so callers need no changes beyond swapping which
# function they call.

def get_h2h_matrix(espn_league_id, start_year, end_year, record_type='all'):
    """Replaces espn_data.create_h2h_matrix - a single indexed query over
    `games` instead of a full live re-walk of every season with no caching at
    all (the original had none, even for long-final years - the worst
    offender in the app, which is why this page migrates first). Same output
    shape: a pandas DataFrame, index/columns = every owner active in the
    range, cell = "wins-losses" (row's record against column, ties excluded -
    matches get_all_time_h2h_by_scores_fixed's existing behavior of skipping
    ties entirely rather than counting them either way), diagonal = "-"."""
    playoff_filter = ""
    if record_type == 'regular':
        playoff_filter = "AND v.is_playoff = false"
    elif record_type == 'playoffs':
        playoff_filter = "AND v.is_playoff = true"

    with _cursor() as cur:
        cur.execute(
            f"""
            SELECT o.display_name, opp.display_name,
                   count(*) FILTER (WHERE v.result = 'W'),
                   count(*) FILTER (WHERE v.result = 'L')
            FROM v_owner_game_log v
            JOIN leagues l ON l.id = v.league_id
            JOIN owners o ON o.id = v.owner_id
            JOIN owners opp ON opp.id = v.opponent_id
            WHERE l.espn_league_id = %s AND v.year BETWEEN %s AND %s
                AND v.result != 'T' {playoff_filter}
            GROUP BY o.display_name, opp.display_name
            """,
            (espn_league_id, start_year, end_year),
        )
        pair_records = {(row[0], row[1]): (row[2], row[3]) for row in cur.fetchall()}

    # Owner set is derived from who actually has a game of this record_type,
    # not from season_teams - matches create_h2h_matrix's original behavior
    # exactly: an owner who never made the playoffs simply doesn't appear in
    # the "Playoffs Only" matrix at all, rather than showing an all-zero row.
    owners = sorted({name for pair in pair_records for name in pair})

    matrix_data = {}
    for row_owner in owners:
        matrix_data[row_owner] = {}
        for col_owner in owners:
            if row_owner == col_owner:
                matrix_data[row_owner][col_owner] = "-"
            else:
                wins, losses = pair_records.get((row_owner, col_owner), (0, 0))
                matrix_data[row_owner][col_owner] = f"{wins}-{losses}"

    return pd.DataFrame(matrix_data).T[owners]
