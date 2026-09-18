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
                if bs.home_team is None:
                    continue
                # A bye (regular-season self-matchup, or a playoff bye where
                # ESPN sets away_team to None entirely - seen for a top seed's
                # first-round bye) still has a real lineup worth capturing.
                is_bye = bs.away_team is None or bs.home_team.team_id == bs.away_team.team_id

                home_owner = _ensure_owner(cur, league_id, get_owner_name(bs.home_team), owner_cache)
                away_owner = _ensure_owner(cur, league_id, get_owner_name(bs.away_team), owner_cache) if not is_bye else None

                # player_weeks captures a bye team's own lineup too (unlike
                # games, which only ever represents real matchups) - matches
                # _compute_front_office_year's original behavior of crediting/
                # debiting that week's coach and GM stats even on a bye,
                # since ESPN still returns a real lineup+scores for it.
                for owner_id, lineup in ((home_owner, bs.home_lineup), (away_owner, bs.away_lineup)):
                    if owner_id is None:
                        continue
                    for p in (lineup or []):
                        players_seen[p.playerId] = (p.name, p.position)
                        player_week_rows.append((
                            league_id, year, week, p.playerId, owner_id,
                            p.position, p.slot_position, getattr(p, 'proTeam', None),
                            p.points, p.projected_points,
                        ))

                if is_bye:
                    continue

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

        # Row layout: [..., 11=made_playoffs, 12=is_champion, 13=is_runner_up,
        # 14=is_dfl, 15=is_best_record, 16=is_most_points, 17=bye_weeks]
        if regular_season_complete and regular_records:
            dfl_owner = min(regular_records, key=lambda r: (r['wins'], r['points']))['owner_id']
            best_owner = max(regular_records, key=lambda r: (r['wins'], r['points']))['owner_id']
            for row in season_team_rows:
                if row[2] == dfl_owner:
                    row[14] = True
                if row[2] == best_owner:
                    row[15] = True
        if points_records:
            most_points_owner = max(points_records, key=lambda r: r['points'])['owner_id']
            for row in season_team_rows:
                if row[2] == most_points_owner:
                    row[16] = True

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


ENSURE_SYNCED_GRACE_MINUTES = 20


def ensure_synced(espn_league_id, year, espn_s2, swid):
    """Sync-if-stale: called once per session per (league, year) before any
    page reads from the DB. The actual staleness check is a plain DB read of
    seasons.last_synced_at - if it's within ENSURE_SYNCED_GRACE_MINUTES, that's
    trusted outright and this returns immediately, no live ESPN call at all.
    A live League() construction (to read the real current week) only
    happens once that grace window has passed - same tradeoff already made
    for odds/matchups/snapshot's own short TTL caches: a few minutes of
    possible staleness in exchange for not paying a live ESPN round trip on
    every single fresh session. Constructing a League object was measured at
    ~3-4s on its own, entirely sequential before any of a page's other
    (parallelized) live calls even start - this was the single biggest
    remaining latency source on every page that calls it."""
    session_key = f'db_synced_{espn_league_id}_{year}'
    if st.session_state.get(session_key):
        return

    with _cursor() as cur:
        cur.execute(
            """
            SELECT s.synced_through_week, s.last_synced_at FROM seasons s
            JOIN leagues l ON l.id = s.league_id
            WHERE l.espn_league_id = %s AND s.year = %s
            """,
            (espn_league_id, year),
        )
        row = cur.fetchone()

    if row is not None:
        synced_through, last_synced_at = row
        if last_synced_at is not None:
            age_minutes = (datetime.now(last_synced_at.tzinfo) - last_synced_at).total_seconds() / 60
            if age_minutes < ENSURE_SYNCED_GRACE_MINUTES:
                st.session_state[session_key] = True
                return
    else:
        synced_through = -1

    try:
        league = League(espn_league_id, year, espn_s2=espn_s2, swid=swid)
        target_week = _last_completed_week(league, year)
    except Exception as e:
        print(f"ensure_synced: couldn't check live state for {year}: {e}")
        st.session_state[session_key] = True
        return

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


_ROSTER_MOVE_ACTION_LABEL = {v: k for k, v in ACTION_KIND_MAP.items()}


def get_roster_moves(espn_league_id, year, size=25):
    """Replaces espn_data.get_recent_activity - same output shapes
    ({'date','kind':'trade','team_a','players_a','team_b','players_b'} or
    {'date','kind':'move','team','action','player','bid_amount'}), read from
    the roster_moves table (populated as a side effect of sync_season) instead
    of a live league.recent_activity() call, which is consistently the
    slowest single ESPN call in the app (several seconds) - a DB read here is
    what actually gets League News/Rumor Mill under the page-load target,
    where a short TTL cache alone only helps repeat hits, not the first one."""
    with _cursor() as cur:
        cur.execute(
            """
            SELECT rm.kind, rm.occurred_at, o.display_name, cp.display_name,
                   p.name, rm.bid_amount, rm.trade_group_id
            FROM roster_moves rm
            JOIN leagues l ON l.id = rm.league_id
            JOIN owners o ON o.id = rm.owner_id
            LEFT JOIN owners cp ON cp.id = rm.counterparty_owner_id
            JOIN players p ON p.id = rm.player_id
            WHERE l.espn_league_id = %s AND rm.year = %s
            ORDER BY rm.occurred_at DESC
            LIMIT %s
            """,
            (espn_league_id, year, size * 3),  # a trade is 2 rows per event - oversample, trim after grouping
        )
        rows = cur.fetchall()

    trades = {}
    entries = []
    for kind, occurred_at, owner, counterparty, player, bid_amount, trade_group_id in rows:
        if kind == 'trade':
            entry = trades.get(trade_group_id)
            if entry is None:
                entry = {'date': occurred_at, 'kind': 'trade', 'team_a': owner,
                          'players_a': [], 'team_b': counterparty, 'players_b': []}
                trades[trade_group_id] = entry
                entries.append(entry)
            (entry['players_a'] if owner == entry['team_a'] else entry['players_b']).append(player)
        else:
            entries.append({
                'date': occurred_at, 'kind': 'move', 'team': owner,
                'action': _ROSTER_MOVE_ACTION_LABEL[kind], 'player': player, 'bid_amount': bid_amount,
            })

    entries.sort(key=lambda e: e['date'], reverse=True)
    return entries[:size]


def get_front_office_history(espn_league_id, start_year, end_year):
    """Replaces espn_data.build_front_office_history - same
    (gm_history, coach_history, draft_log, luck_history) tuple shape,
    assembled from player_weeks/draft_picks/games/seasons instead of ~50
    live weekly box-score calls per season (the heaviest fetch in the whole
    app). Reuses espn_data._optimal_lineup_ids completely unchanged for the
    coach-rankings optimal-lineup computation - DB rows are adapted into
    lightweight namedtuples exposing the same .playerId/.position/.points
    attributes it expects, so this is the exact already-verified algorithm,
    not a reimplementation of it."""
    from collections import namedtuple

    from espn_data import _optimal_lineup_ids

    _P = namedtuple('_P', ['playerId', 'position', 'points'])

    with _cursor() as cur:
        cur.execute(
            """
            SELECT s.year, s.dedicated_slots, s.flex_slots FROM seasons s
            JOIN leagues l ON l.id = s.league_id
            WHERE l.espn_league_id = %s AND s.year BETWEEN %s AND %s
            """,
            (espn_league_id, start_year, end_year),
        )
        slot_structure = {
            year: ([tuple(x) for x in dedicated], [tuple(x) for x in flex])
            for year, dedicated, flex in cur.fetchall()
        }

        cur.execute(
            """
            SELECT dp.year, dp.player_id, o.display_name, dp.round_num, dp.round_pick
            FROM draft_picks dp
            JOIN owners o ON o.id = dp.owner_id
            JOIN leagues l ON l.id = dp.league_id
            WHERE l.espn_league_id = %s AND dp.year BETWEEN %s AND %s
            """,
            (espn_league_id, start_year, end_year),
        )
        draft_by_player_year = {(year, pid): (owner, rn, rp) for year, pid, owner, rn, rp in cur.fetchall()}

        cur.execute(
            """
            SELECT dp.year, dp.player_id, p.name
            FROM draft_picks dp
            JOIN players p ON p.id = dp.player_id
            JOIN leagues l ON l.id = dp.league_id
            WHERE l.espn_league_id = %s AND dp.year BETWEEN %s AND %s
            """,
            (espn_league_id, start_year, end_year),
        )
        draft_log = [{'year': y, 'player_id': pid, 'player_name': name} for y, pid, name in cur.fetchall()]

        cur.execute(
            """
            SELECT pw.year, pw.week, pw.player_id, p.name, pw.position,
                   o.display_name, pw.slot, pw.actual_points, pw.projected_points
            FROM player_weeks pw
            JOIN players p ON p.id = pw.player_id
            JOIN owners o ON o.id = pw.owner_id
            JOIN leagues l ON l.id = pw.league_id
            WHERE l.espn_league_id = %s AND pw.year BETWEEN %s AND %s
            """,
            (espn_league_id, start_year, end_year),
        )
        pw_rows = cur.fetchall()

        cur.execute(
            """
            SELECT g.year, g.week, oh.display_name, oa.display_name
            FROM games g
            JOIN owners oh ON oh.id = g.home_owner_id
            JOIN owners oa ON oa.id = g.away_owner_id
            JOIN leagues l ON l.id = g.league_id
            WHERE l.espn_league_id = %s AND g.year BETWEEN %s AND %s
            """,
            (espn_league_id, start_year, end_year),
        )
        game_pairs = cur.fetchall()

    by_year_week_owner = {}
    by_year_player = {}
    for year, week, player_id, name, position, owner, slot, actual, projected in pw_rows:
        row = {'player_id': player_id, 'name': name, 'position': position, 'owner': owner,
               'slot': slot, 'actual': float(actual), 'projected': float(projected)}
        by_year_week_owner.setdefault((year, week, owner), []).append(row)
        by_year_player.setdefault((year, player_id), []).append((week, owner, row))

    def _new_gm_record():
        return {'picks': [], 'acquisitions': []}

    def _new_coach_record():
        return {'correct_calls': 0, 'total_calls': 0, 'actual_points': 0.0, 'optimal_points': 0.0, 'weekly_log': []}

    def _new_luck_record():
        return {'boom_wins': 0, 'games_played': 0}

    gm_history, coach_history, luck_history = {}, {}, {}

    # --- Coach rankings: optimal lineup per (year, week, owner) ------------
    for (year, week, owner), rows in by_year_week_owner.items():
        dedicated_slots, flex_slots = slot_structure.get(year, ([], []))
        starters = [r for r in rows if r['slot'] not in ('BE', 'IR')]
        available = [r for r in rows if r['slot'] != 'IR']
        if not starters:
            continue
        optimal_ids = _optimal_lineup_ids(
            [_P(r['player_id'], r['position'], r['actual']) for r in available], dedicated_slots, flex_slots)
        actual_ids = {r['player_id'] for r in starters}
        week_actual = sum(r['actual'] for r in starters)
        week_optimal = sum(r['actual'] for r in available if r['player_id'] in optimal_ids)

        coach = coach_history.setdefault(owner, _new_coach_record())
        coach['correct_calls'] += len(actual_ids & optimal_ids)
        coach['total_calls'] += len(starters)
        coach['actual_points'] += week_actual
        coach['optimal_points'] += week_optimal
        coach['weekly_log'].append({
            'year': year, 'week': week, 'owner': owner,
            'correct': len(actual_ids & optimal_ids), 'total': len(starters),
            'points_left': week_optimal - week_actual,
        })

    # --- Luck: boom wins need both sides of the same game at once ----------
    for year, week, home_owner, away_owner in game_pairs:
        home_rows = by_year_week_owner.get((year, week, home_owner), [])
        away_rows = by_year_week_owner.get((year, week, away_owner), [])
        home_starters = [r for r in home_rows if r['slot'] not in ('BE', 'IR')]
        away_starters = [r for r in away_rows if r['slot'] not in ('BE', 'IR')]
        if not home_starters or not away_starters:
            continue
        home_actual = sum(r['actual'] for r in home_starters)
        away_actual = sum(r['actual'] for r in away_starters)
        home_projected = sum(r['projected'] for r in home_starters)
        away_projected = sum(r['projected'] for r in away_starters)
        for owner, own_actual, own_projected, opp_actual in (
            (home_owner, home_actual, home_projected, away_actual),
            (away_owner, away_actual, away_projected, home_actual),
        ):
            luck = luck_history.setdefault(owner, _new_luck_record())
            luck['games_played'] += 1
            if own_actual > opp_actual and own_projected < opp_actual:
                luck['boom_wins'] += 1

    # --- GM: each player's weeks grouped by owner within a year, split
    # picks (matches the draft record) vs acquisitions (everyone else) -----
    for (year, player_id), weeks in by_year_player.items():
        weeks_by_owner = {}
        for week, owner, row in weeks:
            weeks_by_owner.setdefault(owner, []).append((week, row))
        drafted = draft_by_player_year.get((year, player_id))
        drafting_owner = drafted[0] if drafted else None

        for owner, owner_weeks in weeks_by_owner.items():
            total_actual = sum(r['actual'] for _, r in owner_weeks)
            total_projected = sum(r['projected'] for _, r in owner_weeks)
            ir_weeks = sum(1 for _, r in owner_weeks if r['slot'] == 'IR')
            decision = {
                'year': year, 'player_id': player_id,
                'player_name': owner_weeks[0][1]['name'], 'position': owner_weeks[0][1]['position'],
                'total_actual': total_actual, 'total_projected': total_projected,
                'value': total_actual - total_projected, 'scale': total_projected,
                'weeks_rostered': len(owner_weeks), 'ir_weeks': ir_weeks,
                'weekly': [
                    {'week': w, 'actual': r['actual'], 'projected': r['projected'], 'slot': r['slot'], 'owner': owner}
                    for w, r in owner_weeks
                ],
            }
            gm = gm_history.setdefault(owner, _new_gm_record())
            if owner == drafting_owner:
                decision['round_num'], decision['round_pick'] = drafted[1], drafted[2]
                gm['picks'].append(decision)
            else:
                gm['acquisitions'].append(decision)

    return gm_history, coach_history, draft_log, luck_history


def get_scoring_settings(espn_league_id, year):
    """Replaces espn_data.get_league_scoring_settings - {statID: points},
    read from seasons.scoring_settings instead of a live League() call.
    Scoring rules don't change mid-season, so this is safe to serve straight
    from whatever sync_season last captured; callers should call
    ensure_synced() first the same as any other DB read here."""
    with _cursor() as cur:
        cur.execute(
            """
            SELECT s.scoring_settings FROM seasons s
            JOIN leagues l ON l.id = s.league_id
            WHERE l.espn_league_id = %s AND s.year = %s
            """,
            (espn_league_id, year),
        )
        row = cur.fetchone()
    return row[0] if row else {}


def get_league_history(espn_league_id, start_year, end_year):
    """Replaces espn_data.build_league_history / common.get_league_history -
    same per-owner dict shape (years, total_wins/losses/ties, total_points,
    playoff_wins/losses/ties, playoff_appearances, championships,
    championship_appearances, champion_years, dfl_finishes, dfl_years,
    best_record_seasons/years, most_points_seasons/years, bye_weeks,
    season_points, playoff_years, game_log), assembled from season_teams +
    v_owner_game_log instead of walking ESPN live. The resolved flags
    (is_champion/is_dfl/etc.) were computed once at sync time using the
    exact same tiebreak logic _compute_league_history_year has - see
    db.sync_season."""
    with _cursor() as cur:
        cur.execute(
            """
            SELECT o.display_name, st.year, st.wins, st.losses, st.ties, st.points_for,
                   st.made_playoffs, st.is_champion, st.is_runner_up, st.is_dfl,
                   st.is_best_record, st.is_most_points, st.bye_weeks
            FROM season_teams st
            JOIN owners o ON o.id = st.owner_id
            JOIN leagues l ON l.id = st.league_id
            WHERE l.espn_league_id = %s AND st.year BETWEEN %s AND %s
            ORDER BY o.display_name, st.year
            """,
            (espn_league_id, start_year, end_year),
        )
        season_rows = cur.fetchall()

        cur.execute(
            """
            SELECT o.display_name,
                   count(*) FILTER (WHERE v.result = 'W' AND v.is_playoff),
                   count(*) FILTER (WHERE v.result = 'L' AND v.is_playoff),
                   count(*) FILTER (WHERE v.result = 'T' AND v.is_playoff)
            FROM v_owner_game_log v
            JOIN leagues l ON l.id = v.league_id
            JOIN owners o ON o.id = v.owner_id
            WHERE l.espn_league_id = %s AND v.year BETWEEN %s AND %s
            GROUP BY o.display_name
            """,
            (espn_league_id, start_year, end_year),
        )
        playoff_wlt = {row[0]: row[1:] for row in cur.fetchall()}

        cur.execute(
            """
            SELECT o.display_name, v.year, v.week, v.is_playoff, v.points,
                   v.opp_points, opp.display_name, v.result
            FROM v_owner_game_log v
            JOIN leagues l ON l.id = v.league_id
            JOIN owners o ON o.id = v.owner_id
            JOIN owners opp ON opp.id = v.opponent_id
            WHERE l.espn_league_id = %s AND v.year BETWEEN %s AND %s
            ORDER BY o.display_name, v.year, v.week
            """,
            (espn_league_id, start_year, end_year),
        )
        game_logs = {}
        for owner, year, week, is_playoff, points, opp_points, opponent, result in cur.fetchall():
            game_logs.setdefault(owner, []).append({
                'year': year, 'week': week, 'is_playoff': is_playoff,
                'points': float(points), 'opp_points': float(opp_points),
                'opponent': opponent, 'result': result,
            })

    def _new_owner_record():
        return {
            'years': [], 'total_wins': 0, 'total_losses': 0, 'total_ties': 0, 'total_points': 0.0,
            'playoff_wins': 0, 'playoff_losses': 0, 'playoff_ties': 0, 'playoff_appearances': 0,
            'championships': 0, 'championship_appearances': 0, 'champion_years': set(),
            'dfl_finishes': 0, 'dfl_years': set(),
            'best_record_seasons': 0, 'best_record_years': set(),
            'most_points_seasons': 0, 'most_points_years': set(),
            'season_points': {}, 'playoff_years': set(), 'bye_weeks': 0, 'game_log': [],
        }

    owners = {}
    for (owner, year, wins, losses, ties, points_for, made_playoffs, is_champion,
         is_runner_up, is_dfl, is_best_record, is_most_points, bye_weeks) in season_rows:
        rec = owners.setdefault(owner, _new_owner_record())
        rec['years'].append(year)
        rec['total_wins'] += wins
        rec['total_losses'] += losses
        rec['total_ties'] += ties
        rec['total_points'] += float(points_for)
        rec['bye_weeks'] += bye_weeks
        rec['season_points'][year] = float(points_for)
        if made_playoffs:
            rec['playoff_appearances'] += 1
            rec['playoff_years'].add(year)
        if is_champion:
            rec['championships'] += 1
            rec['championship_appearances'] += 1
            rec['champion_years'].add(year)
        elif is_runner_up:
            rec['championship_appearances'] += 1
        if is_dfl:
            rec['dfl_finishes'] += 1
            rec['dfl_years'].add(year)
        if is_best_record:
            rec['best_record_seasons'] += 1
            rec['best_record_years'].add(year)
        if is_most_points:
            rec['most_points_seasons'] += 1
            rec['most_points_years'].add(year)

    for owner, (pw, pl, pt) in playoff_wlt.items():
        if owner in owners:
            owners[owner]['playoff_wins'] = pw
            owners[owner]['playoff_losses'] = pl
            owners[owner]['playoff_ties'] = pt

    for owner, log in game_logs.items():
        if owner in owners:
            owners[owner]['game_log'] = log

    return owners


def get_season_box_scores(espn_league_id, year):
    """Replaces espn_data.build_season_box_scores - same
    {week: [{home_owner, home_score, home_lineup, away_owner, away_score,
    away_lineup}, ...]} shape, lineup entries matching _lineup_players'
    exact fields. game_played/on_bye_week are hardcoded to their
    always-completed-week values (100/False) since this table only ever
    holds weeks that were already final when synced - same as the original
    function, which only ever fetched completed weeks to begin with."""
    with _cursor() as cur:
        cur.execute(
            """
            SELECT g.week, g.home_owner_id, oh.display_name, g.home_score,
                   g.away_owner_id, oa.display_name, g.away_score
            FROM games g
            JOIN leagues l ON l.id = g.league_id
            JOIN owners oh ON oh.id = g.home_owner_id
            JOIN owners oa ON oa.id = g.away_owner_id
            WHERE l.espn_league_id = %s AND g.year = %s
            ORDER BY g.week
            """,
            (espn_league_id, year),
        )
        game_rows = cur.fetchall()

        cur.execute(
            """
            SELECT pw.week, pw.owner_id, p.name, pw.position, pw.slot,
                   pw.actual_points, pw.projected_points, pw.pro_team
            FROM player_weeks pw
            JOIN players p ON p.id = pw.player_id
            JOIN leagues l ON l.id = pw.league_id
            WHERE l.espn_league_id = %s AND pw.year = %s
            """,
            (espn_league_id, year),
        )
        lineups = {}
        for week, owner_id, name, position, slot, points, projected, pro_team in cur.fetchall():
            lineups.setdefault((week, owner_id), []).append({
                'name': name, 'position': position, 'slot': slot,
                'points': float(points), 'projected': float(projected), 'pro_team': pro_team,
                'game_played': 100, 'on_bye_week': False,
            })

    weeks = {}
    for week, home_owner_id, home_owner, home_score, away_owner_id, away_owner, away_score in game_rows:
        weeks.setdefault(week, []).append({
            'home_owner': home_owner, 'home_score': float(home_score),
            'home_lineup': lineups.get((week, home_owner_id), []),
            'away_owner': away_owner, 'away_score': float(away_score),
            'away_lineup': lineups.get((week, away_owner_id), []),
        })
    return weeks
