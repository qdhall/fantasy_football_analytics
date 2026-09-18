"""
Pure computations over the per-owner history built by espn_data.build_league_history().
Nothing here talks to the ESPN API or Streamlit - just stats derivation, so it's easy
to unit-test or tweak the GOAT weighting/tiers without touching data-fetching code.
"""

from datetime import datetime

# Minimum sample sizes so a single lucky/unlucky stretch can't claim a percentage record
MIN_GAMES_FOR_RECORD = 10
MIN_PLAYOFF_GAMES_FOR_RECORD = 2
MIN_RIVALRY_GAMES = 5
CLOSE_GAME_MARGIN = 10.0
DOMINANT_WIN_MARGIN = 40.0

GOAT_WEIGHTS = {
    'championships': 4,
    'championship_appearances': 2.5,
    'playoff_appearances': 2,
    'bye_weeks': 1,
    'best_record_seasons': 2,
    'most_points_seasons': 2,
    'dfl_finishes': -2.5,
    'playoff_wins': 1.5,
    'total_wins': 3,
    'total_points': 3,
}

# Display labels for the weighted metrics, used to render the score rubric
GOAT_METRIC_LABELS = {
    'championships': 'Titles',
    'championship_appearances': 'Finals',
    'playoff_appearances': 'Playoff Apps',
    'bye_weeks': 'Byes',
    'best_record_seasons': 'Best Record Seasons',
    'most_points_seasons': 'Most Points Seasons',
    'dfl_finishes': 'DFL Finishes',
    'playoff_wins': 'Playoff Wins',
    'total_wins': 'Wins',
    'total_points': 'Points',
}


def _win_pct(wins, losses, ties):
    total = wins + losses + ties
    return (wins / total) if total > 0 else None


def _record_detail(owners, holders, wins_key, losses_key, ties_key):
    """W-L(-T) for the first holder, shown so a lower record can't look higher than
    a rival's just because its display hid a chunk of tie games from the ratio."""
    rec = owners[holders[0]]
    wins, losses, ties = rec[wins_key], rec[losses_key], rec[ties_key]
    record = f"{wins}-{losses}"
    if ties:
        record += f"-{ties}"
    return record


def format_score_rubric():
    """Human-readable breakdown of how Score is computed, built straight from
    GOAT_WEIGHTS so the displayed rubric can never drift out of sync with the math."""
    terms = []
    for metric, weight in GOAT_WEIGHTS.items():
        label = GOAT_METRIC_LABELS[metric]
        sign = "+" if weight >= 0 else "−"
        terms.append(f"{sign} {abs(weight):g}×{label}")
    formula = " ".join(terms).lstrip("+ ").strip()
    return f"Score = {formula} (each metric scaled 0-1 across the league, then weighted)"


def compute_goat_rankings(owners):
    """Composite all-time ranking: each metric is min-max normalized across owners,
    weighted (DFL finishes count negatively), and summed to a Score - 100 is the max
    a clean sweep of every positive metric with zero DFL finishes would produce."""
    if not owners:
        return []

    metric_values = {
        metric: [rec[metric] for rec in owners.values()]
        for metric in GOAT_WEIGHTS
    }
    metric_ranges = {
        metric: (min(vals), max(vals))
        for metric, vals in metric_values.items()
    }

    positive_weight_total = sum(w for w in GOAT_WEIGHTS.values() if w > 0)
    rows = []
    for owner, rec in owners.items():
        score = 0.0
        for metric, weight in GOAT_WEIGHTS.items():
            lo, hi = metric_ranges[metric]
            normalized = ((rec[metric] - lo) / (hi - lo)) if hi > lo else 0.0
            score += weight * normalized
        final_score = (score / positive_weight_total) * 100

        rows.append({
            'owner': owner,
            'score': round(final_score, 1),
            'championships': rec['championships'],
            'championship_appearances': rec['championship_appearances'],
            'playoff_appearances': rec['playoff_appearances'],
            'dfl_finishes': rec['dfl_finishes'],
            'playoff_wins': rec['playoff_wins'],
            'playoff_losses': rec['playoff_losses'],
            'playoff_ties': rec['playoff_ties'],
            'total_wins': rec['total_wins'],
            'total_losses': rec['total_losses'],
            'total_ties': rec['total_ties'],
            'total_points': rec['total_points'],
            'years_played': len(rec['years']),
            'bye_weeks': rec['bye_weeks'],
            'best_record_seasons': rec['best_record_seasons'],
            'most_points_seasons': rec['most_points_seasons'],
        })

    rows.sort(key=lambda r: r['score'], reverse=True)
    for i, row in enumerate(rows):
        row['rank'] = i + 1

    return rows


def _extreme_items(items, key_fn, best='max'):
    """Return (target_value, [all items tied at that extreme]) - unlike Python's
    built-in max()/min(), which silently returns only the first match, this
    surfaces every tie so single-game/season record cards don't under-report
    co-holders."""
    if not items:
        return None, []
    target = (max if best == 'max' else min)(key_fn(i) for i in items)
    holders = [i for i in items if key_fn(i) == target]
    return target, holders


def _dedupe(seq):
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _tie_detail(items, detail_fn, owner_fn=lambda i: i['owner']):
    """Single item -> its own detail line, unchanged. Multiple tied items ->
    each detail line prefixed with its owner, since a single unqualified
    detail string can't represent two different games/seasons at once."""
    if len(items) == 1:
        return detail_fn(items[0])
    return "; ".join(f"{owner_fn(i)} - {detail_fn(i)}" for i in items)


def _unique_games(games):
    """_all_games() lists every physical matchup twice - once per owner's own
    game_log, from that owner's perspective. That's correct for lopsided
    metrics like a team's own score, but a metric that's symmetric between
    both sides (margin magnitude, combined score) would otherwise "tie"
    against its own mirror row and report a single game as a 2-way tie.
    Keeps exactly one row per (year, week, pair-of-owners)."""
    seen = set()
    unique = []
    for g in games:
        key = (g['year'], g['week'], frozenset({g['owner'], g['opponent']}))
        if key in seen:
            continue
        seen.add(key)
        unique.append(g)
    return unique


def _pairwise_records(owners, games_filter=None):
    """[{pair: frozenset({a, b}), games, wins: {owner: count}, ties}, ...] -
    one entry per unique pair of owners who have ever played each other,
    built off _unique_games so a single physical game is counted once."""
    games = _all_games(owners)
    if games_filter:
        games = [g for g in games if games_filter(g)]
    pairs = {}
    for g in _unique_games(games):
        key = frozenset({g['owner'], g['opponent']})
        p = pairs.setdefault(key, {'pair': key, 'games': 0, 'wins': {}, 'ties': 0})
        p['games'] += 1
        if g['result'] == 'W':
            p['wins'][g['owner']] = p['wins'].get(g['owner'], 0) + 1
        elif g['result'] == 'L':
            p['wins'][g['opponent']] = p['wins'].get(g['opponent'], 0) + 1
        else:
            p['ties'] += 1
    return list(pairs.values())


def _rivalry_record_str(p):
    a, b = sorted(p['pair'])
    wa, wb = p['wins'].get(a, 0), p['wins'].get(b, 0)
    tie_str = f"-{p['ties']}" if p['ties'] else ""
    if wa == wb:
        return f"{a} vs {b}, tied {wa}-{wb}{tie_str}"
    leader, trailer = (a, b) if wa > wb else (b, a)
    return f"{leader} leads {trailer} {max(wa, wb)}-{min(wa, wb)}{tie_str}"


def _all_games(owners):
    games = []
    for owner, rec in owners.items():
        for g in rec['game_log']:
            games.append({**g, 'owner': owner})
    return games


def _is_season_final(year):
    """Mirrors espn_data._is_year_final's rule (a season is done once we're
    in a later calendar year than it started in), reimplemented locally so
    this module stays pure computation with no ESPN/Streamlit dependency.
    Any per-season TOTAL (season_points) needs this guard - unlike
    individual game entries, which espn_data already only ever records for
    weeks that have actually finished, a season's running total keeps
    growing all season long, so a season 1-2 weeks in has a tiny partial
    total that isn't comparable to a finished season's real total."""
    return year < datetime.now().year


def _all_seasons(owners):
    seasons = []
    for owner, rec in owners.items():
        for year, points in rec['season_points'].items():
            if not _is_season_final(year):
                continue
            seasons.append({'owner': owner, 'year': year, 'points': points})
    return seasons


def _leaders(owners, value_fn, minimum_fn=None, best='max'):
    """Return (best_value, [owner names]) tied for the best value_fn() result.
    minimum_fn(rec) -> bool gates eligibility (e.g. minimum sample size)."""
    values = {}
    for owner, rec in owners.items():
        if minimum_fn and not minimum_fn(rec):
            continue
        v = value_fn(rec)
        if v is None:
            continue
        values[owner] = v

    if not values:
        return None, []

    target = max(values.values()) if best == 'max' else min(values.values())
    holders = [owner for owner, v in values.items() if v == target]
    return target, holders


def _longest_streak(game_log, result):
    best = current = 0
    for g in sorted(game_log, key=lambda g: (g['year'], g['week'])):
        if g['result'] == result:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _close_game_streak(game_log):
    """Longest run of consecutive games (regardless of W/L) decided by under
    CLOSE_GAME_MARGIN - a streak of nail-biters, win or lose."""
    best = current = 0
    for g in sorted(game_log, key=lambda g: (g['year'], g['week'])):
        if abs(g['points'] - g['opp_points']) < CLOSE_GAME_MARGIN:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _longest_non_playoff_streak(years, playoff_years):
    best = current = 0
    prev_year = None
    for y in sorted(years):
        if prev_year is not None and y != prev_year + 1:
            current = 0  # a gap in participation breaks the streak
        current = 0 if y in playoff_years else current + 1
        best = max(best, current)
        prev_year = y
    return best


def _longest_playoff_streak(years, playoff_years):
    """Mirror of _longest_non_playoff_streak - longest run of consecutive
    years MAKING the playoffs rather than missing them."""
    best = current = 0
    prev_year = None
    for y in sorted(years):
        if prev_year is not None and y != prev_year + 1:
            current = 0
        current = current + 1 if y in playoff_years else 0
        best = max(best, current)
        prev_year = y
    return best


def _season_games_and_wins(owners):
    """Per (owner, year): games played and wins that season - derived from
    game_log, used for points-per-game and losing-season-streak records."""
    seasons = {}
    for owner, rec in owners.items():
        for g in rec['game_log']:
            key = (owner, g['year'])
            s = seasons.setdefault(key, {'games': 0, 'wins': 0})
            s['games'] += 1
            if g['result'] == 'W':
                s['wins'] += 1
    return seasons


def _points_per_game_season_entries(owners):
    """[{owner, year, ppg}, ...] for every (owner, season) with at least
    MIN_GAMES_FOR_RECORD games that season."""
    entries = []
    for owner, rec in owners.items():
        for year, points in rec['season_points'].items():
            if not _is_season_final(year):
                continue
            games = sum(1 for g in rec['game_log'] if g['year'] == year)
            if games < MIN_GAMES_FOR_RECORD:
                continue
            entries.append({'owner': owner, 'year': year, 'ppg': points / games})
    return entries


def _longest_losing_season_streak(owner, rec, season_games):
    """Longest run of consecutive years with a sub-.500 record for this owner."""
    best = current = 0
    prev_year = None
    for y in sorted(rec['years']):
        if prev_year is not None and y != prev_year + 1:
            current = 0
        s = season_games.get((owner, y))
        is_losing_season = bool(s) and s['games'] > 0 and s['wins'] / s['games'] < 0.5
        current = current + 1 if is_losing_season else 0
        best = max(best, current)
        prev_year = y
    return best


def _current_playoff_drought(years, playoff_years):
    """Consecutive seasons missed out of the playoffs, ending at the most
    recent year played - the ACTIVE drought, unlike longest_playoff_drought's
    all-time historical max, which might be from years ago for a team that's
    since turned things around."""
    if not years:
        return 0
    streak = 0
    for y in sorted(years, reverse=True):
        if y in playoff_years:
            break
        streak += 1
    return streak


def compute_group_records(owners):
    """Leaderboard-style 'who has the most' records."""
    records = {}

    records['most_championships'] = _record(
        "Most Championships", *_leaders(owners, lambda r: r['championships']), fmt="{:.0f}")

    records['most_championship_appearances'] = _record(
        "Most Championship Appearances", *_leaders(owners, lambda r: r['championship_appearances']), fmt="{:.0f}")

    records['most_playoff_appearances'] = _record(
        "Most Playoff Appearances", *_leaders(owners, lambda r: r['playoff_appearances']), fmt="{:.0f}")

    best_record_value, best_record_holders = _leaders(
        owners,
        lambda r: _win_pct(r['total_wins'], r['total_losses'], r['total_ties']),
        minimum_fn=lambda r: (r['total_wins'] + r['total_losses'] + r['total_ties']) >= MIN_GAMES_FOR_RECORD,
    )
    records['best_alltime_record'] = _record(
        "Best All-Time Record", best_record_value, best_record_holders, fmt="{:.1%}",
        detail=_record_detail(owners, best_record_holders, 'total_wins', 'total_losses', 'total_ties')
        if best_record_holders else None)

    best_playoff_value, best_playoff_holders = _leaders(
        owners,
        lambda r: _win_pct(r['playoff_wins'], r['playoff_losses'], r['playoff_ties']),
        minimum_fn=lambda r: (r['playoff_wins'] + r['playoff_losses'] + r['playoff_ties']) >= MIN_PLAYOFF_GAMES_FOR_RECORD,
    )
    records['best_playoff_record'] = _record(
        "Best Playoff Record", best_playoff_value, best_playoff_holders, fmt="{:.1%}",
        detail=_record_detail(owners, best_playoff_holders, 'playoff_wins', 'playoff_losses', 'playoff_ties')
        if best_playoff_holders else None)

    seasons = _all_seasons(owners)
    if seasons:
        top_value, top_items = _extreme_items(seasons, lambda s: s['points'])
        records['most_points_season'] = _record(
            "Most Points in a Season", top_value, _dedupe(i['owner'] for i in top_items),
            fmt="{:,.1f}", detail=_tie_detail(top_items, lambda s: f"{s['year']} season"))

    games = _all_games(owners)
    if games:
        top_value, top_items = _extreme_items(games, lambda g: g['points'])
        records['most_points_game'] = _record(
            "Most Points in a Game", top_value, _dedupe(i['owner'] for i in top_items),
            fmt="{:,.1f}",
            detail=_tie_detail(top_items, lambda g: f"Week {g['week']}, {g['year']} vs {g['opponent']}"))

    win_streak_value, win_streak_holders = _leaders(
        owners, lambda r: _longest_streak(r['game_log'], 'W'))
    records['longest_win_streak'] = _record(
        "Longest Winning Streak", win_streak_value, win_streak_holders, fmt="{:.0f} games")

    records['most_bye_weeks'] = _record(
        "Most Playoff Byes Earned", *_leaders(owners, lambda r: r['bye_weeks']), fmt="{:.0f}")

    records['most_best_record_seasons'] = _record(
        "Most Best-Record Seasons", *_leaders(owners, lambda r: r['best_record_seasons']), fmt="{:.0f}")

    records['most_scoring_leader_seasons'] = _record(
        "Most Scoring-Leader Seasons", *_leaders(owners, lambda r: r['most_points_seasons']), fmt="{:.0f}")

    playoff_streak_value, playoff_streak_holders = _leaders(
        owners, lambda r: _longest_playoff_streak(r['years'], r['playoff_years']))
    records['longest_playoff_streak'] = _record(
        "Longest Playoff Appearance Streak", playoff_streak_value, playoff_streak_holders, fmt="{:.0f} seasons")

    ppg_entries = _points_per_game_season_entries(owners)
    if ppg_entries:
        ppg_value, ppg_items = _extreme_items(ppg_entries, lambda e: e['ppg'])
        records['best_points_per_game_season'] = _record(
            "Best Points-Per-Game Season", ppg_value, _dedupe(i['owner'] for i in ppg_items),
            fmt="{:.1f} pts/game", detail=_tie_detail(ppg_items, lambda e: f"{e['year']} season"))

    games_played_value, games_played_holders = _leaders(
        owners, lambda r: r['total_wins'] + r['total_losses'] + r['total_ties'])
    records['most_career_games'] = _record(
        "Most Career Games Played", games_played_value, games_played_holders, fmt="{:.0f} games")

    # Total points scored minus total points allowed, career-wide - a
    # different axis than raw win totals or point totals: this rewards teams
    # that win AND win big, and penalizes teams propped up by a few
    # razor-thin wins against otherwise-strong opponents.
    point_diff_value, point_diff_holders = _leaders(
        owners, lambda r: r['total_points'] - sum(g['opp_points'] for g in r['game_log']))
    records['best_point_differential'] = _record(
        "Best All-Time Point Differential", point_diff_value, point_diff_holders, fmt="{:+,.1f}")

    # Weeks where an owner's own score was the single highest in the ENTIRE
    # league that week (not just their own matchup) - a weekly-granularity
    # sibling to "Most Scoring-Leader Seasons". Ties share credit, same as a
    # real league would call a shared week's high score.
    weekly_max = {}
    for g in games:
        key = (g['year'], g['week'])
        weekly_max[key] = max(weekly_max.get(key, float('-inf')), g['points'])
    weekly_title_counts = {}
    for g in games:
        if g['points'] == weekly_max[(g['year'], g['week'])]:
            weekly_title_counts[g['owner']] = weekly_title_counts.get(g['owner'], 0) + 1
    if weekly_title_counts:
        title_entries = [{'owner': o, 'count': c} for o, c in weekly_title_counts.items()]
        title_value, title_items = _extreme_items(title_entries, lambda e: e['count'])
        records['most_weekly_scoring_titles'] = _record(
            "Most Weekly Scoring Titles", title_value, _dedupe(i['owner'] for i in title_items),
            fmt="{:.0f} weeks")

    playoff_ppg_entries = []
    for owner, rec in owners.items():
        playoff_games_log = [g for g in rec['game_log'] if g['is_playoff']]
        if len(playoff_games_log) < MIN_PLAYOFF_GAMES_FOR_RECORD:
            continue
        playoff_ppg_entries.append({
            'owner': owner,
            'ppg': sum(g['points'] for g in playoff_games_log) / len(playoff_games_log),
        })
    if playoff_ppg_entries:
        playoff_ppg_value, playoff_ppg_items = _extreme_items(playoff_ppg_entries, lambda e: e['ppg'])
        records['best_playoff_ppg'] = _record(
            "Best Playoff Points-Per-Game", playoff_ppg_value, _dedupe(i['owner'] for i in playoff_ppg_items),
            fmt="{:,.1f} pts/game")

    # "Clutch" wins - decided by a single-digit-to-low-double-digit margin,
    # the kind that come down to a garbage-time flex or a Monday-night kicker.
    close_wins_value, close_wins_holders = _leaders(
        owners,
        lambda r: sum(
            1 for g in r['game_log']
            if g['result'] == 'W' and (g['points'] - g['opp_points']) < CLOSE_GAME_MARGIN
        ),
    )
    records['most_clutch_wins'] = _record(
        "Most Clutch Wins (Under 10 Points)", close_wins_value, close_wins_holders, fmt="{:.0f} wins")

    # A title won while ALSO owning the league's best regular-season record
    # that same year - no fluky bracket runs, no backing in. Gated to owners
    # who've actually done it at least once, so a league where nobody has
    # simply omits the card rather than showing everyone tied at zero.
    wire_to_wire_value, wire_to_wire_holders = _leaders(
        owners,
        lambda r: len(r['champion_years'] & r['best_record_years']),
        minimum_fn=lambda r: len(r['champion_years'] & r['best_record_years']) >= 1,
    )
    records['wire_to_wire_titles'] = _record(
        "Wire-to-Wire Titles (Champion + Best Record, Same Season)",
        wire_to_wire_value, wire_to_wire_holders, fmt="{:.0f}")

    # Championships won per trip to the title game - a RATE, not a raw count,
    # so a 1-for-1 owner can outrank a 2-for-3 owner here even though the
    # latter has more rings; "Most Championships" already covers raw volume.
    conversion_value, conversion_holders = _leaders(
        owners,
        lambda r: (r['championships'] / r['championship_appearances']) if r['championship_appearances'] > 0 else None,
        minimum_fn=lambda r: r['championship_appearances'] >= 1,
    )
    conversion_detail = None
    if conversion_holders:
        rec = owners[conversion_holders[0]]
        conversion_detail = f"{rec['championships']}-for-{rec['championship_appearances']} in title games"
    records['best_championship_conversion'] = _record(
        "Best Championship Conversion Rate", conversion_value, conversion_holders, fmt="{:.0%}",
        detail=conversion_detail)

    playoff_games_played_value, playoff_games_played_holders = _leaders(
        owners, lambda r: r['playoff_wins'] + r['playoff_losses'] + r['playoff_ties'])
    records['most_playoff_games_played'] = _record(
        "Most Playoff Games Played (Career)", playoff_games_played_value, playoff_games_played_holders,
        fmt="{:.0f} games")

    if seasons:
        season_diff_entries = []
        for owner, rec in owners.items():
            for year, points in rec['season_points'].items():
                if not _is_season_final(year):
                    continue
                against = sum(g['opp_points'] for g in rec['game_log'] if g['year'] == year)
                season_diff_entries.append({'owner': owner, 'year': year, 'diff': points - against})
        diff_value, diff_items = _extreme_items(season_diff_entries, lambda e: e['diff'])
        records['best_season_point_differential'] = _record(
            "Best Single-Season Point Differential", diff_value, _dedupe(i['owner'] for i in diff_items),
            fmt="{:+,.1f}", detail=_tie_detail(diff_items, lambda e: f"{e['year']} season"))

    # The mirror image of "Most Clutch Wins" - wins that were never in doubt.
    dominant_wins_value, dominant_wins_holders = _leaders(
        owners,
        lambda r: sum(
            1 for g in r['game_log']
            if g['result'] == 'W' and (g['points'] - g['opp_points']) >= DOMINANT_WIN_MARGIN
        ),
    )
    records['most_dominant_wins'] = _record(
        "Most Dominant Wins (40+ Points)", dominant_wins_value, dominant_wins_holders, fmt="{:.0f} wins")

    # _longest_playoff_streak is a generic "longest consecutive-years run
    # within a qualifying set" despite its name - reused here for
    # best_record_years instead of playoff_years.
    best_record_streak_value, best_record_streak_holders = _leaders(
        owners, lambda r: _longest_playoff_streak(r['years'], r['best_record_years']))
    records['longest_best_record_streak'] = _record(
        "Longest Streak With the League's Best Record", best_record_streak_value, best_record_streak_holders,
        fmt="{:.0f} seasons")

    def _winning_seasons_count(rec):
        by_year = {}
        for g in rec['game_log']:
            s = by_year.setdefault(g['year'], {'w': 0, 'l': 0, 't': 0})
            s['w' if g['result'] == 'W' else 't' if g['result'] == 'T' else 'l'] += 1
        return sum(1 for s in by_year.values() if s['w'] > s['l'])

    winning_seasons_value, winning_seasons_holders = _leaders(owners, _winning_seasons_count)
    records['most_winning_seasons'] = _record(
        "Most Seasons With a Winning Record", winning_seasons_value, winning_seasons_holders, fmt="{:.0f} seasons")

    return records


def compute_wall_of_shame(owners):
    """Leaderboard-style 'who has the least/worst' records."""
    records = {}

    worst_record_value, worst_record_holders = _leaders(
        owners,
        lambda r: _win_pct(r['total_wins'], r['total_losses'], r['total_ties']),
        minimum_fn=lambda r: (r['total_wins'] + r['total_losses'] + r['total_ties']) >= MIN_GAMES_FOR_RECORD,
        best='min',
    )
    records['worst_alltime_record'] = _record(
        "Worst All-Time Record", worst_record_value, worst_record_holders, fmt="{:.1%}",
        detail=_record_detail(owners, worst_record_holders, 'total_wins', 'total_losses', 'total_ties')
        if worst_record_holders else None)

    games = _all_games(owners)
    if games:
        low_value, low_items = _extreme_items(games, lambda g: g['points'], best='min')
        records['least_points_game'] = _record(
            "Least Points in a Game", low_value, _dedupe(i['owner'] for i in low_items),
            fmt="{:,.1f}",
            detail=_tie_detail(low_items, lambda g: f"Week {g['week']}, {g['year']} vs {g['opponent']}"))

    seasons = _all_seasons(owners)
    if seasons:
        low_value, low_items = _extreme_items(seasons, lambda s: s['points'], best='min')
        records['least_points_season'] = _record(
            "Least Points in a Season", low_value, _dedupe(i['owner'] for i in low_items),
            fmt="{:,.1f}", detail=_tie_detail(low_items, lambda s: f"{s['year']} season"))

    drought_value, drought_holders = _leaders(
        owners, lambda r: _longest_non_playoff_streak(r['years'], r['playoff_years']))
    records['longest_playoff_drought'] = _record(
        "Most Consecutive Seasons Without a Playoff Appearance", drought_value, drought_holders, fmt="{:.0f} seasons")

    loss_streak_value, loss_streak_holders = _leaders(
        owners, lambda r: _longest_streak(r['game_log'], 'L'))
    records['longest_losing_streak'] = _record(
        "Most Consecutive Losing Weeks", loss_streak_value, loss_streak_holders, fmt="{:.0f} games")

    records['most_career_losses'] = _record(
        "Most Career Losses", *_leaders(owners, lambda r: r['total_losses']), fmt="{:.0f}")

    worst_playoff_value, worst_playoff_holders = _leaders(
        owners,
        lambda r: _win_pct(r['playoff_wins'], r['playoff_losses'], r['playoff_ties']),
        minimum_fn=lambda r: (r['playoff_wins'] + r['playoff_losses'] + r['playoff_ties']) >= MIN_PLAYOFF_GAMES_FOR_RECORD,
        best='min',
    )
    records['worst_playoff_record'] = _record(
        "Worst Playoff Record", worst_playoff_value, worst_playoff_holders, fmt="{:.1%}",
        detail=_record_detail(owners, worst_playoff_holders, 'playoff_wins', 'playoff_losses', 'playoff_ties')
        if worst_playoff_holders else None)

    records['most_playoff_losses'] = _record(
        "Most Playoff Losses", *_leaders(owners, lambda r: r['playoff_losses']), fmt="{:.0f}")

    season_games = _season_games_and_wins(owners)
    worst_losing_streak, worst_losing_streak_holders = 0, []
    for owner, rec in owners.items():
        streak = _longest_losing_season_streak(owner, rec, season_games)
        if streak > worst_losing_streak:
            worst_losing_streak, worst_losing_streak_holders = streak, [owner]
        elif streak == worst_losing_streak and streak > 0:
            worst_losing_streak_holders.append(owner)
    records['longest_losing_season_streak'] = _record(
        "Most Consecutive Losing Seasons", worst_losing_streak, worst_losing_streak_holders, fmt="{:.0f} seasons")

    current_drought_value, current_drought_holders = _leaders(
        owners, lambda r: _current_playoff_drought(r['years'], r['playoff_years']))
    records['current_playoff_drought'] = _record(
        "Longest ACTIVE Playoff Drought", current_drought_value, current_drought_holders, fmt="{:.0f} seasons")

    point_diff_value, point_diff_holders = _leaders(
        owners, lambda r: r['total_points'] - sum(g['opp_points'] for g in r['game_log']), best='min')
    records['worst_point_differential'] = _record(
        "Worst All-Time Point Differential", point_diff_value, point_diff_holders, fmt="{:+,.1f}")

    if seasons:
        season_diff_entries = []
        for owner, rec in owners.items():
            for year, points in rec['season_points'].items():
                if not _is_season_final(year):
                    continue
                against = sum(g['opp_points'] for g in rec['game_log'] if g['year'] == year)
                season_diff_entries.append({'owner': owner, 'year': year, 'diff': points - against})
        worst_diff_value, worst_diff_items = _extreme_items(season_diff_entries, lambda e: e['diff'], best='min')
        records['worst_season_point_differential'] = _record(
            "Worst Single-Season Point Differential", worst_diff_value, _dedupe(i['owner'] for i in worst_diff_items),
            fmt="{:+,.1f}", detail=_tie_detail(worst_diff_items, lambda e: f"{e['year']} season"))

    career_ppg_entries = []
    for owner, rec in owners.items():
        total_games = rec['total_wins'] + rec['total_losses'] + rec['total_ties']
        if total_games < MIN_GAMES_FOR_RECORD:
            continue
        career_ppg_entries.append({'owner': owner, 'ppg': rec['total_points'] / total_games})
    if career_ppg_entries:
        worst_ppg_value, worst_ppg_items = _extreme_items(career_ppg_entries, lambda e: e['ppg'], best='min')
        records['worst_career_ppg'] = _record(
            "Worst Career Points-Per-Game", worst_ppg_value, _dedupe(i['owner'] for i in worst_ppg_items),
            fmt="{:,.1f} pts/game")

    playoff_ppg_entries_shame = []
    for owner, rec in owners.items():
        playoff_games_log = [g for g in rec['game_log'] if g['is_playoff']]
        if len(playoff_games_log) < MIN_PLAYOFF_GAMES_FOR_RECORD:
            continue
        playoff_ppg_entries_shame.append({
            'owner': owner,
            'ppg': sum(g['points'] for g in playoff_games_log) / len(playoff_games_log),
        })
    if playoff_ppg_entries_shame:
        worst_playoff_ppg_value, worst_playoff_ppg_items = _extreme_items(
            playoff_ppg_entries_shame, lambda e: e['ppg'], best='min')
        records['worst_playoff_ppg'] = _record(
            "Worst Playoff Points-Per-Game", worst_playoff_ppg_value,
            _dedupe(i['owner'] for i in worst_playoff_ppg_items), fmt="{:,.1f} pts/game")

    if games:
        beatdown_value, beatdown_items = _extreme_items(games, lambda g: g['points'] - g['opp_points'], best='min')
        records['worst_beatdown_suffered'] = _record(
            "Worst Beatdown Suffered", beatdown_value, _dedupe(i['owner'] for i in beatdown_items),
            fmt="{:,.1f} pt margin",
            detail=_tie_detail(
                beatdown_items,
                lambda g: f"lost to {g['opponent']} {g['points']:,.1f}-{g['opp_points']:,.1f} "
                          f"(Week {g['week']}, {g['year']})"))

    # The mirror image of "Most Clutch Wins" - losses that came down to the wire.
    heartbreak_losses_value, heartbreak_losses_holders = _leaders(
        owners,
        lambda r: sum(
            1 for g in r['game_log']
            if g['result'] == 'L' and (g['opp_points'] - g['points']) < CLOSE_GAME_MARGIN
        ),
    )
    records['most_heartbreaking_losses'] = _record(
        "Most Heartbreaking Losses (Under 10 Points)", heartbreak_losses_value, heartbreak_losses_holders,
        fmt="{:.0f} losses")

    # _longest_playoff_streak is a generic "longest consecutive-years run
    # within a qualifying set" despite its name - reused here for dfl_years.
    dfl_streak_value, dfl_streak_holders = _leaders(
        owners, lambda r: _longest_playoff_streak(r['years'], r['dfl_years']))
    records['longest_dfl_streak'] = _record(
        "Most Consecutive DFL Finishes", dfl_streak_value, dfl_streak_holders, fmt="{:.0f} seasons")

    # Led the league in scoring that season and STILL missed the playoffs -
    # a career count of League Trivia's "Highest-Scoring Team to Miss the
    # Playoffs" moment, for owners unlucky enough it's happened more than once.
    snake_bitten_value, snake_bitten_holders = _leaders(
        owners, lambda r: len(r['most_points_years'] - r['playoff_years']))
    records['most_snake_bitten_seasons'] = _record(
        "Most Snake-Bitten Seasons (Led League in Scoring, Missed Playoffs)",
        snake_bitten_value, snake_bitten_holders, fmt="{:.0f} seasons")

    return records


def compute_league_trivia(owners):
    """Fun, low-stakes callouts that don't fit the GOAT/records/shame framing."""
    trivia = {}
    games = _all_games(owners)

    if games:
        blowout_value, blowout_items = _extreme_items(games, lambda g: g['points'] - g['opp_points'])
        trivia['biggest_blowout'] = _record(
            "Biggest Blowout",
            blowout_value,
            _dedupe(i['owner'] for i in blowout_items),
            fmt="{:,.1f} pt margin",
            detail=_tie_detail(
                blowout_items,
                lambda g: f"beat {g['opponent']} {g['points']:,.1f}-{g['opp_points']:,.1f} "
                          f"(Week {g['week']}, {g['year']})"))

        decided_games = [g for g in _unique_games(games) if g['result'] != 'T']
        if decided_games:
            nail_value, nail_items = _extreme_items(
                decided_games, lambda g: abs(g['points'] - g['opp_points']), best='min')
            trivia['closest_game'] = _record(
                "Closest Game",
                nail_value,
                _dedupe(i['owner'] for i in nail_items),
                fmt="{:,.2f} pt margin",
                detail=_tie_detail(
                    nail_items,
                    lambda g: f"vs {g['opponent']}, {g['points']:,.2f}-{g['opp_points']:,.2f} "
                              f"(Week {g['week']}, {g['year']})"))

        combined_value, combined_items = _extreme_items(
            _unique_games(games), lambda g: g['points'] + g['opp_points'])
        trivia['highest_combined_score'] = _record(
            "Highest-Scoring Game",
            combined_value,
            _dedupe(i['owner'] for i in combined_items),
            fmt="{:,.1f} combined points",
            detail=_tie_detail(
                combined_items,
                lambda g: f"{g['owner']} {g['points']:,.1f} - {g['opp_points']:,.1f} {g['opponent']} "
                          f"(Week {g['week']}, {g['year']})",
                owner_fn=lambda g: g['owner']))

    tenure_value, tenure_holders = _leaders(owners, lambda r: len(r['years']))
    trivia['most_tenured_owner'] = _record(
        "Longest-Running Owner", tenure_value, tenure_holders, fmt="{:.0f} seasons")

    dfl_value, dfl_holders = _leaders(owners, lambda r: r['dfl_finishes'])
    trivia['most_dfl_finishes'] = _record(
        "Most DFL Finishes", dfl_value, dfl_holders, fmt="{:.0f} times")

    if games:
        losses = [g for g in games if g['result'] == 'L']
        if losses:
            heartbreak_value, heartbreak_items = _extreme_items(losses, lambda g: g['points'])
            trivia['most_points_losing_effort'] = _record(
                "Most Points in a Losing Effort",
                heartbreak_value, _dedupe(i['owner'] for i in heartbreak_items),
                fmt="{:,.1f} points",
                detail=_tie_detail(
                    heartbreak_items,
                    lambda g: f"lost to {g['opponent']} {g['points']:,.1f}-"
                              f"{g['opp_points']:,.1f} (Week {g['week']}, {g['year']})"))

        wins = [g for g in games if g['result'] == 'W']
        if wins:
            backed_in_value, backed_in_items = _extreme_items(wins, lambda g: g['points'], best='min')
            trivia['fewest_points_winning_effort'] = _record(
                "Fewest Points in a Winning Effort",
                backed_in_value, _dedupe(i['owner'] for i in backed_in_items),
                fmt="{:,.1f} points",
                detail=_tie_detail(
                    backed_in_items,
                    lambda g: f"beat {g['opponent']} {g['points']:,.1f}-"
                              f"{g['opp_points']:,.1f} (Week {g['week']}, {g['year']})"))

    non_playoff_seasons = [
        {'owner': owner, 'year': year, 'points': points}
        for owner, rec in owners.items()
        for year, points in rec['season_points'].items()
        if year not in rec['playoff_years'] and _is_season_final(year)
    ]
    if non_playoff_seasons:
        unlucky_value, unlucky_items = _extreme_items(non_playoff_seasons, lambda s: s['points'])
        trivia['unlucky_season'] = _record(
            "Highest-Scoring Team to Miss the Playoffs",
            unlucky_value, _dedupe(i['owner'] for i in unlucky_items),
            fmt="{:,.1f} points", detail=_tie_detail(unlucky_items, lambda s: f"{s['year']} season"))

    bridesmaid_value, bridesmaid_holders = _leaders(
        owners,
        lambda r: r['championship_appearances'] - r['championships'],
        minimum_fn=lambda r: r['championships'] == 0,
    )
    trivia['bridesmaid'] = _record(
        "The Bridesmaid (Most Championship-Game Losses, Never a Champion)",
        bridesmaid_value, bridesmaid_holders, fmt="{:.0f} times")

    improvements = []
    for owner, rec in owners.items():
        for year in sorted(rec['season_points']):
            if not _is_season_final(year):
                continue
            if year - 1 in rec['season_points']:
                improvements.append({
                    'owner': owner, 'year': year,
                    'delta': rec['season_points'][year] - rec['season_points'][year - 1],
                })
    if improvements:
        jump_value, jump_items = _extreme_items(improvements, lambda i: i['delta'])
        trivia['most_improved_season'] = _record(
            "Most Improved Season",
            jump_value, _dedupe(i['owner'] for i in jump_items),
            fmt="{:+,.1f} points",
            detail=_tie_detail(jump_items, lambda i: f"{i['year'] - 1} → {i['year']}"))

        drop_value, drop_items = _extreme_items(improvements, lambda i: i['delta'], best='min')
        trivia['biggest_regression'] = _record(
            "Biggest Regression",
            drop_value, _dedupe(i['owner'] for i in drop_items),
            fmt="{:+,.1f} points",
            detail=_tie_detail(drop_items, lambda i: f"{i['year'] - 1} → {i['year']}"))

    champion_seasons = [
        {'owner': owner, 'year': year, 'points': rec['season_points'][year]}
        for owner, rec in owners.items()
        for year in rec['champion_years']
        if year in rec['season_points']
    ]
    if champion_seasons:
        high_value, high_items = _extreme_items(champion_seasons, lambda s: s['points'])
        trivia['highest_scoring_champion'] = _record(
            "Highest-Scoring Championship Team",
            high_value, _dedupe(i['owner'] for i in high_items),
            fmt="{:,.1f} points", detail=_tie_detail(high_items, lambda s: f"{s['year']} champion"))

        low_value, low_items = _extreme_items(champion_seasons, lambda s: s['points'], best='min')
        trivia['lowest_scoring_champion'] = _record(
            "Lowest-Scoring Championship Team (Backed In)",
            low_value, _dedupe(i['owner'] for i in low_items),
            fmt="{:,.1f} points", detail=_tie_detail(low_items, lambda s: f"{s['year']} champion"))

    all_pairs = _pairwise_records(owners)
    if all_pairs:
        riv_value, riv_items = _extreme_items(all_pairs, lambda p: p['games'])
        trivia['longest_rivalry'] = _record(
            "Longest Rivalry",
            riv_value,
            _dedupe(name for p in riv_items for name in p['pair']),
            fmt="{:.0f} games",
            detail=_tie_detail(
                riv_items, _rivalry_record_str, owner_fn=lambda p: " & ".join(sorted(p['pair']))))

        eligible_pairs = [p for p in all_pairs if p['games'] >= MIN_RIVALRY_GAMES and p['wins']]
        if eligible_pairs:
            def _dominance(p):
                return max(p['wins'].values()) / p['games']

            def _leader_name(p):
                return max(p['wins'], key=p['wins'].get)

            dom_value, dom_items = _extreme_items(eligible_pairs, _dominance)
            trivia['most_lopsided_rivalry'] = _record(
                "Most Lopsided Rivalry",
                dom_value,
                _dedupe(_leader_name(p) for p in dom_items),
                fmt="{:.1%} domination",
                detail=_tie_detail(dom_items, _rivalry_record_str, owner_fn=_leader_name))

    playoff_pairs = _pairwise_records(owners, games_filter=lambda g: g['is_playoff'])
    if playoff_pairs:
        pf_value, pf_items = _extreme_items(playoff_pairs, lambda p: p['games'])
        trivia['most_frequent_playoff_matchup'] = _record(
            "Most Frequent Playoff Matchup",
            pf_value,
            _dedupe(name for p in pf_items for name in p['pair']),
            fmt="{:.0f} playoff games",
            detail=_tie_detail(
                pf_items, _rivalry_record_str, owner_fn=lambda p: " & ".join(sorted(p['pair']))))

    nailbiter_streak_value, nailbiter_streak_holders = _leaders(
        owners, lambda r: _close_game_streak(r['game_log']))
    trivia['nailbiter_streak'] = _record(
        "Longest Nail-Biter Streak (Consecutive Games Under 10 Points)",
        nailbiter_streak_value, nailbiter_streak_holders, fmt="{:.0f} games")

    # A DFL finish immediately followed by a championship the very next
    # season - the ultimate worst-to-first redemption arc. Gated to owners
    # who've actually done it, same reasoning as wire_to_wire_titles.
    worst_to_first_value, worst_to_first_holders = _leaders(
        owners,
        lambda r: len([y for y in r['dfl_years'] if (y + 1) in r['champion_years']]),
        minimum_fn=lambda r: len([y for y in r['dfl_years'] if (y + 1) in r['champion_years']]) >= 1,
    )
    trivia['worst_to_first'] = _record(
        "Worst to First (DFL Finish, Champion the Very Next Year)",
        worst_to_first_value, worst_to_first_holders, fmt="{:.0f} times")

    return trivia


def _record(label, value, holders, fmt="{}", detail=None):
    if value is None or not holders:
        return None
    return {
        'label': label,
        'value': value,
        'display_value': fmt.format(value),
        'holders': holders,
        'detail': detail,
    }
