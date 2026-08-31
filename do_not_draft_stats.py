"""
Pure computations for the Do Not Draft List: players who perform fine on their
own numbers, but whose rosters in this league just don't win - the "superstition"
metric (a Lamar Jackson type). Nothing here talks to the ESPN API or Streamlit -
same separation as league_stats.py/front_office_stats.py/luck_stats.py.

The key move is treating individual performance as a GATE, not a scoring input:
only players who were at-or-above their own projections on average are eligible
at all, so this never just re-derives "who was a bad pick" (GM Rankings already
covers that) - it isolates players who look fine individually but whose teams
keep missing the playoffs, finishing DFL, or never winning it all.
"""

import statistics

MIN_SEASONS_ROSTERED = 2

# Same anchor-at-50 approach as GM Rankings/Luck Index, but the direction is
# flipped on purpose: 100 here means "the biggest red flag in the league," not
# "the best," since this page's whole point is a ranked warning list.
CURSE_SCORE_POINTS_PER_Z = 20

METRIC_LABELS = {
    'playoff_rate': 'Playoff Rate',
    'dfl_rate': 'DFL Rate',
    'championships': 'Championships',
    'ir_weeks_per_season': 'IR Weeks/Season',
    'team_win_pct': "Teams' Win %",
    'bad_week_rate': 'Bad Week Rate',
}

# A "bad week" is scoring under this fraction of projection - the same idea as
# a boom win's opposite: not just a slight miss, a real no-show relative to
# what was expected that week.
BAD_WEEK_THRESHOLD_PCT = 0.5


def _player_stints(gm_history):
    """Group every decision (draft pick or acquisition) by player, each stint
    tagged with the (owner, year) roster it was actually part of - a player
    traded mid-season already shows up as separate stints per owner, same
    granularity front_office_stats.py works at."""
    players = {}
    for owner, data in gm_history.items():
        for d in data['picks'] + data.get('acquisitions', []):
            entry = players.setdefault(d['player_id'], {'name': d['player_name'], 'stints': []})
            entry['stints'].append({
                'owner': owner, 'year': d['year'], 'value': d['value'], 'scale': d['scale'],
                'ir_weeks': d['ir_weeks'], 'total_actual': d['total_actual'], 'weekly': d['weekly'],
            })
    return players


def _team_record_for_seasons(owners, seasons):
    """Aggregate W-L-T, games-weighted (not season-weighted, so a 2-game stint
    doesn't count as much as a full season), across every (owner, year) this
    player was rostered for - the smoother, continuous counterpart to the
    playoff/DFL booleans: a team can miss the playoffs by one game or by six,
    and this tells the two apart where the binary flags can't."""
    wins = losses = ties = 0
    for owner, year in seasons:
        games = [g for g in owners.get(owner, {}).get('game_log', []) if g['year'] == year]
        wins += sum(1 for g in games if g['result'] == 'W')
        losses += sum(1 for g in games if g['result'] == 'L')
        ties += sum(1 for g in games if g['result'] == 'T')
    return wins, losses, ties


def _bad_week_rate(stints):
    """% of weeks (across every stint) where this player scored under
    BAD_WEEK_THRESHOLD_PCT of their projection - a "disappears when it
    matters" signal, distinct from the season-level value gate: a player can
    be fine ON AVERAGE while still no-showing constantly week to week."""
    weeks = [w for s in stints for w in s['weekly'] if w['projected'] > 0]
    if not weeks:
        return 0.0
    bad = sum(1 for w in weeks if w['actual'] < BAD_WEEK_THRESHOLD_PCT * w['projected'])
    return bad / len(weeks) * 100


def compute_do_not_draft_candidates(gm_history, owners, min_seasons=MIN_SEASONS_ROSTERED):
    """Every player with enough in-league history, scored on how much their
    rostering owners' team outcomes lag their own individual performance.
    Returns ALL qualifying players sorted worst-first (most cursed at rank 1) -
    callers filtering to a specific season's relevant player pool (e.g. still
    active in the NFL) should do so on this list, not before, since the curse
    score itself needs the full historical sample to be stable."""
    players = _player_stints(gm_history)

    raw = {}
    for player_id, info in players.items():
        stints = info['stints']
        seasons = {(s['owner'], s['year']) for s in stints}
        if len(seasons) < min_seasons:
            continue

        total_value = sum(s['value'] for s in stints)
        total_scale = sum(s['scale'] for s in stints)
        # Performance gate: only players who were at/above their own projection
        # on net are eligible - this is what keeps the list from just being
        # "worst players," which GM Rankings already covers.
        if total_scale > 0 and total_value / total_scale < 0:
            continue

        playoff_hits = sum(1 for o, y in seasons if y in owners.get(o, {}).get('playoff_years', set()))
        dfl_hits = sum(1 for o, y in seasons if y in owners.get(o, {}).get('dfl_years', set()))
        champ_hits = sum(1 for o, y in seasons if y in owners.get(o, {}).get('champion_years', set()))

        n = len(seasons)
        total_ir_weeks = sum(s['ir_weeks'] for s in stints)

        team_wins, team_losses, team_ties = _team_record_for_seasons(owners, seasons)
        team_games = team_wins + team_losses + team_ties
        team_win_pct = (team_wins / team_games * 100) if team_games > 0 else 50.0
        team_record = f"{team_wins}-{team_losses}" + (f"-{team_ties}" if team_ties else "")

        raw[player_id] = {
            'name': info['name'],
            'seasons': n,
            'playoff_rate': playoff_hits / n * 100,
            'dfl_rate': dfl_hits / n * 100,
            'championships': champ_hits,
            'ir_weeks_per_season': total_ir_weeks / n,
            'team_win_pct': team_win_pct,
            'team_record': team_record,
            'bad_week_rate': _bad_week_rate(stints),
            'total_actual': sum(s['total_actual'] for s in stints),
            'avg_value_pct': (total_value / total_scale * 100) if total_scale > 0 else 0.0,
        }

    if not raw:
        return []

    # Each curse factor flipped/oriented so a HIGHER z-score always means MORE
    # cursed: low playoff rate, high DFL rate, zero championships, more IR
    # time, low team win% while rostered, more bad weeks.
    signals = {
        'playoff_rate': {pid: -v['playoff_rate'] for pid, v in raw.items()},
        'dfl_rate': {pid: v['dfl_rate'] for pid, v in raw.items()},
        'championships': {pid: -v['championships'] for pid, v in raw.items()},
        'ir_weeks_per_season': {pid: v['ir_weeks_per_season'] for pid, v in raw.items()},
        'team_win_pct': {pid: -v['team_win_pct'] for pid, v in raw.items()},
        'bad_week_rate': {pid: v['bad_week_rate'] for pid, v in raw.items()},
    }

    zscores = {name: {} for name in signals}
    for name, values_by_pid in signals.items():
        values = list(values_by_pid.values())
        if len(values) < 2:
            continue
        mean = statistics.mean(values)
        stdev = statistics.pstdev(values)
        for pid, v in values_by_pid.items():
            zscores[name][pid] = (v - mean) / stdev if stdev else 0.0

    rows = []
    for pid, v in raw.items():
        pid_zs = [zscores[name][pid] for name in signals if pid in zscores[name]]
        avg_z = statistics.mean(pid_zs) if pid_zs else 0.0
        curse_score = max(0.0, min(100.0, 50 + avg_z * CURSE_SCORE_POINTS_PER_Z))

        rows.append({
            'player_id': pid,
            'player_name': v['name'],
            'curse_score': round(curse_score, 1),
            'seasons': v['seasons'],
            'playoff_rate': round(v['playoff_rate'], 1),
            'dfl_rate': round(v['dfl_rate'], 1),
            'championships': v['championships'],
            'ir_weeks_per_season': round(v['ir_weeks_per_season'], 1),
            'team_win_pct': round(v['team_win_pct'], 1),
            'team_record': v['team_record'],
            'bad_week_rate': round(v['bad_week_rate'], 1),
            'total_actual': round(v['total_actual'], 1),
            'avg_value_pct': round(v['avg_value_pct'], 1),
        })

    rows.sort(key=lambda r: r['curse_score'], reverse=True)
    for i, row in enumerate(rows):
        row['rank'] = i + 1
    return rows


def format_curse_rubric():
    return (
        "Every player rostered in at least "
        f"{MIN_SEASONS_ROSTERED} different owner-seasons, who was at or above their "
        "own projection on net (this isn't just 'worst players' - GM Rankings "
        "already covers busts), ranked by how much the TEAMS that rostered them "
        "underperformed: low playoff rate, high DFL rate, zero championships, more "
        "IR time, a low team win% in the seasons they were rostered, and a high "
        f"rate of 'bad weeks' (scoring under {BAD_WEEK_THRESHOLD_PCT:.0%} of projection) "
        "- each z-scored against the field and averaged, then centered on 50. "
        "Higher = bigger red flag - #1 is the league's most-cursed player, not "
        "its best. Only shows players still relevant for the upcoming draft."
    )
