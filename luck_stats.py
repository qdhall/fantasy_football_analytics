"""
Pure computations for the Luck Index page: how much of an owner's record looks
like variance rather than skill. Nothing here talks to the ESPN API or
Streamlit - same separation as league_stats.py and front_office_stats.py.

Score is a literal 0-100% "share of your success that's luck," built from three
independently-bounded 0-100% components, averaged:
  - Pythagorean luck share: of your ACTUAL WINS, what % are wins your own
    scoring (points for/against) didn't earn - PF^2/(PF^2+PA^2) is the standard
    sports-analytics expected-win-rate from points alone, so any win total
    above that expectation is, by definition, luck rather than production.
  - Boom-win share: of your actual wins, what % were wins where your own
    starters' projected total was actually below what your opponent scored -
    you were "supposed" to lose that one.
  - Health luck: 100 minus IR-weeks-per-season-played as a fraction of a fixed
    "practically lost the season" ceiling - a fixed, absolute reference, not
    relative to the league.

Averaging three independently 0-100-bounded shares keeps the composite
0-100-bounded too, and hitting 100 requires ALL THREE to be simultaneously
maxed out (every win a fluke, zero legitimately-earned wins, and perfect
health) - which is what makes 100 the "literally all of your success is luck"
ceiling the score is supposed to represent, rather than just "best of whoever
happened to be in this league."

Close-game record is reported for context (a large sample of true coin-flip
games should land near 50/50) but isn't part of the score - it measures
largely the same underlying phenomenon as Pythagorean luck from a different
angle, so folding both in would double-count one thing rather than add a
second one.
"""

import statistics

MIN_GAMES_FOR_LUCK = 10
MIN_CLOSE_GAMES = 5
CLOSE_GAME_MARGIN = 10.0

# Fixed, absolute ceiling for the health component - not relative to the
# league. 15 IR-weeks in a season is close to losing a starter for the whole
# year; hitting that (or worse) every season played is the "zero health luck"
# floor, not whatever the unhealthiest owner in this specific league happens
# to be.
MAX_IR_WEEKS_PER_SEASON = 15.0

SCORE_COMPONENTS = ('pythagorean_luck', 'boom_win_rate', 'health_luck')
METRIC_LABELS = {
    'pythagorean_luck': 'Pythagorean Luck',
    'close_game_luck': 'Close-Game Luck',
    'boom_win_rate': 'Boom-Win Rate',
    'health_luck': 'Health Luck',
}


def _pythagorean_luck_share(games):
    """% of actual wins that Pythagorean expectation (from points for/against
    alone) doesn't account for. Clamped at 0 on the low end - being unlucky
    isn't "negative luck share," it's just zero luck-driven success."""
    decided = [g for g in games if g['result'] in ('W', 'L')]
    if len(decided) < MIN_GAMES_FOR_LUCK:
        return None
    pf = sum(g['points'] for g in decided)
    pa = sum(g['opp_points'] for g in decided)
    if pf == 0 and pa == 0:
        return None
    actual_wins = sum(1 for g in decided if g['result'] == 'W')
    if actual_wins == 0:
        return 0.0
    expected_win_pct = (pf ** 2) / (pf ** 2 + pa ** 2)
    expected_wins = expected_win_pct * len(decided)
    luck_wins = max(0.0, actual_wins - expected_wins)
    return min(100.0, luck_wins / actual_wins * 100)


def _close_game_luck(games):
    """Context-only stat (see module docstring) - win% in games decided by
    CLOSE_GAME_MARGIN points or less, relative to the 50% a large sample of
    true coin-flips converges to. Can be negative (unlucky in close games)."""
    close = [g for g in games if g['result'] in ('W', 'L')
             and abs(g['points'] - g['opp_points']) <= CLOSE_GAME_MARGIN]
    if len(close) < MIN_CLOSE_GAMES:
        return None
    win_pct = sum(1 for g in close if g['result'] == 'W') / len(close)
    return (win_pct - 0.5) * 100


def _boom_win_share(games, luck_data):
    """% of actual wins that were boom wins (see espn_data._compute_front_office_year
    for the definition) - wins your own starters weren't projected to earn."""
    decided = [g for g in games if g['result'] in ('W', 'L')]
    if len(decided) < MIN_GAMES_FOR_LUCK or not luck_data:
        return None
    actual_wins = sum(1 for g in decided if g['result'] == 'W')
    if actual_wins == 0:
        return 0.0
    return min(100.0, luck_data['boom_wins'] / actual_wins * 100)


def _health_luck_score(gm_data):
    """100 = zero IR-weeks/season (fully healthy); 0 = MAX_IR_WEEKS_PER_SEASON
    or worse, on average, every season - an absolute scale, not relative."""
    decisions = gm_data['picks'] + gm_data.get('acquisitions', [])
    if not decisions:
        return None
    seasons = len({d['year'] for d in decisions})
    if seasons == 0:
        return None
    ir_per_season = sum(d['ir_weeks'] for d in decisions) / seasons
    return max(0.0, 100.0 - (ir_per_season / MAX_IR_WEEKS_PER_SEASON * 100))


def compute_luck_index(owners, gm_history, luck_history):
    """Composite luck score per owner - see module docstring for the three
    scored components (Pythagorean luck share, boom-win share, health luck)
    and why close-game record is shown but not scored."""
    rows = []
    for owner, rec in owners.items():
        games = rec['game_log']
        gm_data = gm_history.get(owner, {'picks': [], 'acquisitions': []})

        pyth_share = _pythagorean_luck_share(games)
        boom_share = _boom_win_share(games, luck_history.get(owner))
        health_score = _health_luck_score(gm_data)
        close_game = _close_game_luck(games)

        components = [v for v in (pyth_share, boom_share, health_score) if v is not None]
        if not components:
            continue
        score = round(statistics.mean(components), 1)

        rows.append({
            'owner': owner,
            'score': score,
            'pythagorean_luck': _fmt_share(pyth_share),
            'boom_win_rate': _fmt_share(boom_share),
            'health_luck': _fmt_share(health_score),
            'close_game_luck': _fmt_signed(close_game),
        })

    rows.sort(key=lambda r: r['score'], reverse=True)
    for i, row in enumerate(rows):
        row['rank'] = i + 1
    return rows


def _fmt_share(value):
    return f"{value:.1f}%" if value is not None else "—"


def _fmt_signed(value):
    return f"{value:+.1f}%" if value is not None else "—"


def format_luck_rubric():
    return (
        "Score is a literal 0-100% share of your success that's luck, averaging "
        "three independently-bounded percentages: Pythagorean luck share (of your "
        "actual wins, the % that Pythagorean expectation from points for/against "
        "alone doesn't explain), boom-win share (of your actual wins, the % that "
        "were wins your own starters weren't even projected to earn), and health "
        "luck (100 minus IR-weeks-per-season as a fraction of a fixed "
        f"{MAX_IR_WEEKS_PER_SEASON:.0f}-week 'lost the season' ceiling). Hitting 100 "
        "would require every win to be a fluke, zero legitimately-earned wins, and "
        "perfect health, all at once - which is the point: 100% is a theoretical "
        "ceiling, not 'best of whoever's in this league.' Close-game record is shown "
        "for context but isn't scored - it's largely the same phenomenon as "
        "Pythagorean luck seen from another angle."
    )
