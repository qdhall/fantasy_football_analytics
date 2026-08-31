"""
Pure computations over the GM (draft) and Coach (lineup) histories built by
espn_data.build_front_office_history(). Nothing here talks to the ESPN API or
Streamlit - just stats derivation, same separation as league_stats.py.
"""

import statistics

# Every GM decision - a draft pick's or an acquisition's (trade/waiver/free agent)
# value while on that owner's roster - gets bucketed the same way, percentage-based
# against the decision's own "scale" (its total projected points) so a bust RB1 and
# a bust kicker are judged on a comparable footing. Below MIN_SCALE_FOR_PCT the scale
# is too small for a percentage to mean anything, so an absolute-point threshold
# takes over instead.
GOOD_THRESHOLD_PCT = 0.15
BAD_THRESHOLD_PCT = -0.15
MIN_SCALE_FOR_PCT = 20.0
GOOD_THRESHOLD_ABS = 5.0
BAD_THRESHOLD_ABS = -5.0

# GM net rate (%Good - %Bad) is a percentage over a wildly uneven number of
# decisions per owner (a rebuilding-year owner might have 20 decisions, a
# long-tenured one 300+), and a rate from 20 decisions is far noisier than one
# from 300 - min-max normalizing the raw rates let a single small, lucky
# sample land at a flat 100 ahead of everyone with a much larger track record.
# GM_SHRINKAGE_K is the fix: blend each owner's rate with the league-wide
# average, weighted as if that average were worth this many decisions of
# evidence - light for a big sample, heavy for a small one. Chosen near this
# league's typical (median-ish) decision count, so it meaningfully tempers the
# 20-40 decision outliers without flattening the 200+ decision regulars.
GM_SHRINKAGE_K = 150

# Score is a z-score of the shrunk rate, not a min-max scaling of it: min-max
# would force whoever's #1 THIS league to a flat 100 (and #last to a flat 0)
# no matter how mediocre or bunched-up everyone's actual rate is - which is
# how an owner whose shrunk rate is still net-negative can end up displayed as
# a "perfect" 100. Anchoring at the league's own mean (score 50 = average GM)
# and scaling by how many standard deviations away someone is means hitting
# 100 requires being a genuine outlier (z ~= +2.5), not just the least-worst
# owner in a small league.
GM_SCORE_POINTS_PER_Z = 20


def _classify_decision(decision):
    value, scale = decision['value'], decision['scale']
    if scale >= MIN_SCALE_FOR_PCT:
        pct = value / scale
        if pct >= GOOD_THRESHOLD_PCT:
            return 'good'
        if pct <= BAD_THRESHOLD_PCT:
            return 'bad'
        return 'expected'
    if value >= GOOD_THRESHOLD_ABS:
        return 'good'
    if value <= BAD_THRESHOLD_ABS:
        return 'bad'
    return 'expected'


def _describe_move(d):
    origin = f"R{d['round_num']}.{d['round_pick']}" if 'round_num' in d else "waiver/trade add"
    return f"{d['player_name']} ({origin}, {d['value']:+.1f}, {d['year']})"


def format_gm_rubric():
    return (
        f"Score = (% Good Picks − % Bad Picks), shrunk toward the league average based "
        f"on how many decisions an owner has (so a handful of decisions can't out-rank "
        f"a much larger track record on small-sample luck alone), then centered on 50 "
        f"(average GM) and scaled by standard deviations from the league mean - not "
        f"min-max'd, so the best owner isn't automatically forced to a flat 100 "
        f"regardless of how mediocre or bunched-together everyone's rate actually is. "
        f"Covers draft picks and every other roster acquisition (trade or waiver/free "
        f"agent - not reliably distinguishable in this league's data, see "
        f"build_front_office_history). A decision is Good if its value while on that "
        f"owner's roster beat expectation by {GOOD_THRESHOLD_PCT:.0%}+ (or "
        f"{GOOD_THRESHOLD_ABS:.0f}+ points when the scale involved is under "
        f"{MIN_SCALE_FOR_PCT:.0f}), Bad if it missed by the same margin, otherwise At "
        f"Expectation - which counts for nothing either way."
    )


def compute_gm_rankings(gm_history):
    """Rank owners by net rate of Good vs. Bad GM decisions - draft picks AND every
    other acquisition (trade or waiver/free agent) combined, since building a roster
    well isn't just about draft day: a GM gains ground for any decision that beat
    expectation, loses ground for one that missed, and gets nothing either way for
    one that landed about where expected. Each decision's value is counted only for
    the weeks that specific player was actually on that owner's roster. A season lost
    to injury already shows up here as a string of near-zero actual weeks against a
    normal projection, so it's folded into the classification without a separate
    injury stat. The raw net rate (%Good - %Bad) is shrunk toward the league-wide
    average based on sample size (see GM_SHRINKAGE_K) - otherwise an owner with a
    handful of decisions can out-rank a large, established track record purely on
    small-sample variance - and then turned into a 0-100 score via a z-score against
    the league (see GM_SCORE_POINTS_PER_Z), not a min-max scaling: min-max would force
    the best owner to a flat 100 and the worst to a flat 0 regardless of how mediocre
    or tightly bunched everyone's actual rate is."""
    rows = []
    for owner, data in gm_history.items():
        picks = data['picks']
        acquisitions = data.get('acquisitions', [])
        decisions = picks + acquisitions
        if not decisions:
            continue

        n = len(decisions)
        total_actual = sum(d['total_actual'] for d in decisions)
        total_projected = sum(d['total_projected'] for d in decisions)
        players_on_ir = sum(1 for d in decisions if d['ir_weeks'] > 0)

        counts = {'good': 0, 'expected': 0, 'bad': 0}
        for d in decisions:
            counts[_classify_decision(d)] += 1

        net_rate = (counts['good'] - counts['bad']) / n * 100

        best_move = max(decisions, key=lambda d: d['value'])
        worst_move = min(decisions, key=lambda d: d['value'])

        rows.append({
            'owner': owner,
            '_net_rate': net_rate,
            '_n': n,
            'picks': len(picks),
            'acquisitions': len(acquisitions),
            'total_actual': round(total_actual, 1),
            'total_projected': round(total_projected, 1),
            'good_pct': round(counts['good'] / n * 100, 1),
            'expected_pct': round(counts['expected'] / n * 100, 1),
            'bad_pct': round(counts['bad'] / n * 100, 1),
            'players_on_ir': players_on_ir,
            'best_move': _describe_move(best_move),
            'worst_move': _describe_move(worst_move),
        })

    total_n = sum(r['_n'] for r in rows)
    league_avg_rate = sum(r['_n'] * r['_net_rate'] for r in rows) / total_n if total_n else 0.0
    for r in rows:
        r['_shrunk_rate'] = (r['_n'] * r['_net_rate'] + GM_SHRINKAGE_K * league_avg_rate) / (r['_n'] + GM_SHRINKAGE_K)

    shrunk_rates = [r['_shrunk_rate'] for r in rows]
    mean = statistics.mean(shrunk_rates) if shrunk_rates else 0.0
    stdev = statistics.pstdev(shrunk_rates) if len(shrunk_rates) > 1 else 0.0
    for r in rows:
        z = (r['_shrunk_rate'] - mean) / stdev if stdev else 0.0
        r['score'] = round(max(0.0, min(100.0, 50 + z * GM_SCORE_POINTS_PER_Z)), 1)
        del r['_net_rate']
        del r['_n']
        del r['_shrunk_rate']

    rows.sort(key=lambda r: r['score'], reverse=True)
    for i, row in enumerate(rows):
        row['rank'] = i + 1
    return rows


def compute_coach_rankings(coach_history):
    """Rank owners by how often their actual starting lineup matched the
    mathematically optimal lineup available from their own roster that week - derived
    from ESPN's real per-week roster slots, not reverse-engineered from score totals."""
    rows = []
    for owner, data in coach_history.items():
        if data['total_calls'] == 0:
            continue
        correct_pct = data['correct_calls'] / data['total_calls'] * 100
        points_left = data['optimal_points'] - data['actual_points']
        weeks = len(data['weekly_log'])

        rows.append({
            'owner': owner,
            'score': round(correct_pct, 1),
            'correct_calls': data['correct_calls'],
            'total_calls': data['total_calls'],
            'weeks': weeks,
            'points_left_on_bench': round(points_left, 1),
            'avg_points_left_per_week': round(points_left / weeks, 2) if weeks else 0,
        })

    rows.sort(key=lambda r: r['score'], reverse=True)
    for i, row in enumerate(rows):
        row['rank'] = i + 1
    return rows


def list_roster_decisions(gm_history):
    """Flatten every draft pick AND acquisition (one row per player-owner-season) into
    one list for a player-picker drill-down, sorted by |value| descending so the most
    notable performances surface first."""
    decisions = []
    for owner, data in gm_history.items():
        for d in data['picks'] + data.get('acquisitions', []):
            decisions.append({**d, 'owner': owner})
    decisions.sort(key=lambda d: abs(d['value']), reverse=True)
    return decisions


def compute_front_office_trivia(gm_history, coach_history, league_owners):
    """Niche callouts that need the heavy Front Office pull (the full draft log, or
    weekly bench data) rather than the lighter league history alone. league_owners is
    the dict from espn_data.build_league_history, used here only for champion_years."""
    trivia = {}

    decisions = list_roster_decisions(gm_history)
    player_totals = {}
    for d in decisions:
        entry = player_totals.setdefault(d['player_id'], {
            'name': d['player_name'], 'total_value': 0.0, 'ever_champion': False,
        })
        entry['total_value'] += d['total_actual']
        owner_rec = league_owners.get(d['owner'])
        if owner_rec and d['year'] in owner_rec.get('champion_years', set()):
            entry['ever_champion'] = True

    non_champions = [e for e in player_totals.values() if not e['ever_champion']]
    if non_champions:
        best_value, best_items = _fo_extreme(non_champions, lambda e: e['total_value'])
        trivia['best_never_champion'] = _fo_record(
            "Best Player No One Has Won A Championship With",
            best_value, _fo_dedupe(e['name'] for e in best_items),
            fmt="{:,.1f} career points (any roster)")

    weekly_entries = [w for data in coach_history.values() for w in data['weekly_log']]
    if weekly_entries:
        worst_value, worst_items = _fo_extreme(weekly_entries, lambda w: w['points_left'])
        trivia['most_bench_points_left'] = _fo_record(
            "Most Points Left on the Bench in a Single Week",
            worst_value, _fo_dedupe(w['owner'] for w in worst_items),
            fmt="{:,.1f} points",
            detail=_fo_tie_detail(worst_items, lambda w: f"Week {w['week']}, {w['year']}", owner_fn=lambda w: w['owner']))

    return trivia


def _fo_extreme(items, key_fn, best='max'):
    """Same tie-safety as league_stats._extreme_items - Python's max()/min()
    silently returns only the first match on a tie, which would under-report
    genuine co-holders on these front-office callouts."""
    if not items:
        return None, []
    target = (max if best == 'max' else min)(key_fn(i) for i in items)
    return target, [i for i in items if key_fn(i) == target]


def _fo_dedupe(seq):
    return list(dict.fromkeys(seq))


def _fo_tie_detail(items, detail_fn, owner_fn=lambda i: i['name']):
    if len(items) == 1:
        return detail_fn(items[0])
    return "; ".join(f"{owner_fn(i)} - {detail_fn(i)}" for i in items)


def _fo_record(label, value, holders, fmt="{}", detail=None):
    if value is None or not holders:
        return None
    return {
        'label': label,
        'value': value,
        'display_value': fmt.format(value),
        'holders': holders,
        'detail': detail,
    }
