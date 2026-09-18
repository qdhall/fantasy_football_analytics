"""Pure computation for the Matchup Predictor - blends Vegas odds
(odds_data.py) with ESPN's own per-player projections (espn_data.py) into a
per-matchup projected score, spread, and win probability. No ESPN/HTTP calls
here, same separation as league_stats.py/front_office_stats.py."""

import math
import statistics

from odds_data import normalize_player_name

# A SportsGameOdds per-stat prop line converts to fantasy points via this
# league's own scoring settings - mapped through espn_api's numeric stat IDs
# (see PLAYER_STATS_MAP in the installed espn_api package). Not exhaustive:
# covers the handful of yardage/TD/reception/INT categories that drive the
# large majority of a skill player's score. A prop stat with no mapping here
# (longest reception, 40+/50+ yard bonuses, etc.) simply doesn't contribute
# to the tier-2 conversion below, the same as if this league didn't score it.
SGO_STAT_TO_ESPN_IDS = {
    'passing_yards': ['3', '22'],
    'passing_touchdowns': ['4'],
    'passing_interceptions': ['20'],
    'rushing_yards': ['24', '40'],
    'receiving_yards': ['42', '61'],
    'receiving_receptions': ['41', '53'],
    # SportsGameOdds offers one unified "touchdowns" prop (any TD) rather
    # than splitting rushing vs. receiving - use whichever this league
    # actually scores; if both are set (the normal case) they're equal in
    # every standard scoring format, so the first hit is fine.
    'touchdowns': ['25', '43'],
}

VEGAS_WEIGHTS = {
    'vegas_direct': 0.75,       # a direct fantasyScore prop line
    'vegas_stats': 0.65,        # summed from granular per-stat props
    'vegas_team_share': 0.40,   # this player's share of the team's implied total
}


def _espn_points_per_unit(stat_id, scoring_settings):
    for espn_id in SGO_STAT_TO_ESPN_IDS.get(stat_id, []):
        if espn_id in scoring_settings:
            return scoring_settings[espn_id]
    return None


def convert_stat_props_to_points(stat_props, scoring_settings):
    """Sum of (prop line * this league's points-per-unit) across every
    mapped stat category present - the tier-2 Vegas signal for a player who
    has granular props but no direct fantasyScore line."""
    total = 0.0
    matched_any = False
    for stat_id, line in stat_props.items():
        per_unit = _espn_points_per_unit(stat_id, scoring_settings)
        if per_unit is None:
            continue
        total += line * per_unit
        matched_any = True
    return total if matched_any else None


def project_player_points(player, odds_lookup, scoring_settings, team_implied_totals, teammates_espn_total):
    """(points, tier) for one starter, following the 5-tier cascade:
    already-played -> direct Vegas fantasyScore -> Vegas per-stat conversion
    -> Vegas team-implied-total share -> ESPN's own projection alone."""
    espn_projected = player.get('projected') or 0.0

    if player.get('game_played') == 100:
        return player.get('points', 0.0), 'actual'

    props = odds_lookup.get(normalize_player_name(player['name']))

    if props and props.get('fantasy_score_line') is not None:
        vegas = props['fantasy_score_line']
        weight = VEGAS_WEIGHTS['vegas_direct']
        return weight * vegas + (1 - weight) * espn_projected, 'vegas_direct'

    if props and props.get('stat_props'):
        vegas = convert_stat_props_to_points(props['stat_props'], scoring_settings)
        if vegas is not None:
            weight = VEGAS_WEIGHTS['vegas_stats']
            return weight * vegas + (1 - weight) * espn_projected, 'vegas_stats'

    # A team's implied offensive point total is not a meaningful proxy for a
    # kicker (scoring depends on field-goal chances/distance, not team
    # points) or a defense/special-teams unit (scoring tracks the OPPONENT's
    # points allowed, not this team's own total) - skip tier 3 for both and
    # fall straight to ESPN's own projection. This also sidesteps a sharper
    # bug: a K/D-ST is almost always the *only* player from their NFL team on
    # a fantasy roster, which made "this player's share of teammates'
    # projected points" collapse to 1.0 - crediting a kicker with nearly
    # their entire team's implied score.
    if player.get('position') not in ('K', 'D/ST'):
        team_total = team_implied_totals.get(player.get('pro_team'))
        if team_total is not None and teammates_espn_total:
            share = espn_projected / teammates_espn_total
            vegas = share * team_total
            weight = VEGAS_WEIGHTS['vegas_team_share']
            return weight * vegas + (1 - weight) * espn_projected, 'vegas_team_share'

    return espn_projected, 'espn_only'


def project_team_score(lineup, odds_lookup, scoring_settings, team_implied_totals):
    """(total_points, [{name, points, tier}, ...]) for the starters in one
    team's current-week lineup."""
    starters = [p for p in lineup if p['slot'] not in ('BE', 'IR')]

    # Each starter's share of their own NFL team's implied score is measured
    # against their ESPN-projected share of teammates ALSO in this fantasy
    # lineup (not their whole real NFL roster) - the tier-3 fallback is only
    # ever used for a player with no odds coverage at all, so this doesn't
    # need to be more precise than "biggest projected role among the
    # starters we're already looking at".
    espn_total_by_pro_team = {}
    for p in starters:
        espn_total_by_pro_team[p['pro_team']] = espn_total_by_pro_team.get(p['pro_team'], 0.0) + (p.get('projected') or 0.0)

    breakdown = []
    total = 0.0
    for p in starters:
        points, tier = project_player_points(
            p, odds_lookup, scoring_settings, team_implied_totals,
            espn_total_by_pro_team.get(p['pro_team'], 0.0),
        )
        total += points
        breakdown.append({'name': p['name'], 'position': p['position'], 'points': points, 'tier': tier})

    return total, breakdown


def estimate_score_std(owners):
    """This league's own empirical standard deviation of an individual
    team's weekly score, from real historical game_log data - used to turn a
    projected margin into a win probability the same way a sportsbook does,
    but calibrated to this league's actual scoring volatility instead of an
    assumed constant."""
    all_scores = [g['points'] for rec in owners.values() for g in rec['game_log']]
    if len(all_scores) < 2:
        return None
    return statistics.stdev(all_scores)


def _margin_to_win_prob(margin, score_std):
    """Win probability for the "home" side of a projected point margin - the
    same math a sportsbook uses to turn a projected spread into a line,
    treating the margin as normally distributed around 0 with a standard
    deviation derived from two independent team-score distributions
    (variance adds: sqrt(2) * a single team's score std)."""
    if score_std and score_std > 0:
        margin_std = math.sqrt(2) * score_std
        return statistics.NormalDist(0, margin_std).cdf(margin)
    return 0.5


def win_prob_to_moneyline(prob):
    """Win probability -> American moneyline odds (e.g. -450 or +350) -
    standard sportsbook conversion, no vig added (this is a projection
    board, not a real book, so there's no house edge to bake in)."""
    prob = min(max(prob, 0.001), 0.999)
    if prob >= 0.5:
        return -100 * prob / (1 - prob)
    return 100 * (1 - prob) / prob


def compute_matchup_prediction(home_lineup, away_lineup, odds_lookup, scoring_settings, team_implied_totals, score_std):
    home_total, home_breakdown = project_team_score(home_lineup, odds_lookup, scoring_settings, team_implied_totals)
    away_total, away_breakdown = project_team_score(away_lineup, odds_lookup, scoring_settings, team_implied_totals)

    margin = home_total - away_total
    win_prob_home = _margin_to_win_prob(margin, score_std)

    return {
        'home_projected': home_total,
        'away_projected': away_total,
        'spread': margin,
        'win_prob_home': win_prob_home,
        'win_prob_away': 1 - win_prob_home,
        'home_breakdown': home_breakdown,
        'away_breakdown': away_breakdown,
    }


def compute_espn_only_prediction(home_espn_projected, away_espn_projected, score_std):
    """Same shape as compute_matchup_prediction's output, but using ESPN's
    own team-level projection (BoxScore.home_projected/away_projected)
    untouched by any Vegas blending - the side-by-side baseline to compare
    our line against. Win probability uses the same score_std-based
    methodology so the two cards differ only in the point estimate, not the
    math used to turn it into odds."""
    margin = home_espn_projected - away_espn_projected
    win_prob_home = _margin_to_win_prob(margin, score_std)
    return {
        'home_projected': home_espn_projected,
        'away_projected': away_espn_projected,
        'spread': margin,
        'win_prob_home': win_prob_home,
        'win_prob_away': 1 - win_prob_home,
    }


def compute_ats_records(all_years_box_scores):
    """{owner: {'beats': n, 'misses': n, 'pushes': n}} - how often a team's
    actual score beat its own ESPN pre-game projection that week, across
    every historical week available. The closest real, computable analog to
    a betting "against the spread" record, since this league has no
    historical Vegas lines to check against - a week is skipped entirely
    (not counted as a "beat") when the projected total is 0, which is ESPN's
    own signal that it no longer has real projection data for that old week
    rather than a real projection of zero."""
    records = {}
    for weeks in all_years_box_scores.values():
        for matchups in weeks.values():
            for m in matchups:
                for owner_key, lineup_key in (('home_owner', 'home_lineup'), ('away_owner', 'away_lineup')):
                    owner = m[owner_key]
                    starters = [p for p in m[lineup_key] if p['slot'] not in ('BE', 'IR')]
                    if not starters:
                        continue
                    actual = sum(p['points'] for p in starters)
                    projected = sum(p['projected'] for p in starters)
                    if projected <= 0:
                        continue
                    rec = records.setdefault(owner, {'beats': 0, 'misses': 0, 'pushes': 0})
                    if actual > projected:
                        rec['beats'] += 1
                    elif actual < projected:
                        rec['misses'] += 1
                    else:
                        rec['pushes'] += 1
    return records
