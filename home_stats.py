"""
Pure computations for the Home page: preseason/in-season storylines and the
award/playoff race widgets. Nothing here talks to the ESPN API or Streamlit - same
separation as league_stats.py and front_office_stats.py.

Storylines are template-generated from real league history, not an LLM - every
sentence is a narrative frame wrapped around an actual stat (a championship, a DFL
finish, a scoring title), so it's deterministic, instant, and never invents a detail
that isn't backed by the data.
"""


def _current_drought(rec, upto_year):
    """Consecutive seasons missed out of the playoffs, ending at upto_year - 0 if
    they made the playoffs that year or didn't play it."""
    if upto_year not in rec['years']:
        return 0
    streak = 0
    year = upto_year
    while year in rec['years'] and year not in rec['playoff_years']:
        streak += 1
        year -= 1
    return streak


# Each template takes (owner, lead, **kwargs) - lead=True renders it as the
# opening sentence of a card ("Cade LeMay is gunning..."), lead=False renders it
# as a later sentence in a combined multi-storyline card ("They are gunning...").
# Doing subject/verb agreement per-template like this, instead of generating the
# owner-led sentence once and text-substituting "They" back in after the fact,
# is what keeps "They has been..." from ever happening - a plain string swap
# can't know a "has" needs to become "have" three words later.
def _t_repeat_bid(owner, lead, year):
    subj, verb = (owner, "is") if lead else ("They", "are")
    return (f"{subj} {verb} gunning for back-to-back titles after hoisting the trophy in "
            f"{year} - word on the street says the league's ready for a fight.")


def _t_revenge_tour(owner, lead):
    subj, verb = (owner, "is") if lead else ("They", "are")
    return f"{subj} {verb} looking to get back on track this year after a last-place finish last season."


def _t_unfinished_business(owner, lead):
    subj = owner if lead else "They"
    return (f"{subj} put up the league's best regular-season record last year but still "
            f"walked away without a ring - sources say they're not happy about it.")


def _t_firepower(owner, lead):
    subj, verb = (owner, "has") if lead else ("They", "have")
    return f"{subj} led the league in scoring last season and, by all accounts, {verb} no plans of slowing down."


def _t_bounce_back(owner, lead):
    subj = owner if lead else "They"
    return (f"{subj} watched the playoffs from home last year after qualifying the season "
            f"before - a bounce-back is due.")


def _t_drought(owner, lead, drought):
    subj, verb = (owner, "hasn't") if lead else ("They", "haven't")
    return f"{subj} {verb} made the playoffs in {drought} straight seasons - patience is reportedly wearing thin."


def _t_breakout(owner, lead, delta):
    subj = owner if lead else "They"
    return (f"{subj} put up the biggest year-over-year points jump in the league last season "
            f"({delta:+.1f}) - can they keep it rolling?")


def _t_og_status(owner, lead, seasons):
    subj, have, havent = (owner, "has", "hasn't") if lead else ("They", "have", "haven't")
    return (f"{subj} {have} been in this league for {seasons} seasons and still {havent} won "
            f"it all - still searching for the first ring.")


def compute_storylines(owners, last_season_year):
    """'Word on the street' headlines about each owner's situation coming out of
    last_season_year, video-game-news-ticker style. Returns a list of
    {owner, tags, text} dicts, one per owner - an owner who qualifies for more
    than one storyline gets a single combined card (see _combine_by_owner)
    rather than several separate ones repeating their name."""
    raw = []

    def add(owner, tag, template, **kwargs):
        raw.append({'owner': owner, 'tag': tag, 'template': template, 'kwargs': kwargs})

    for owner, rec in owners.items():
        if last_season_year not in rec['years']:
            continue

        champion_last_season = last_season_year in rec.get('champion_years', set())

        if champion_last_season:
            add(owner, "REPEAT BID", _t_repeat_bid, year=last_season_year)

        if last_season_year in rec.get('dfl_years', set()):
            add(owner, "REVENGE TOUR", _t_revenge_tour)

        if last_season_year in rec.get('best_record_years', set()) and not champion_last_season:
            add(owner, "UNFINISHED BUSINESS", _t_unfinished_business)

        if last_season_year in rec.get('most_points_years', set()) and not champion_last_season:
            add(owner, "FIREPOWER", _t_firepower)

        if (last_season_year not in rec.get('playoff_years', set())
                and (last_season_year - 1) in rec.get('playoff_years', set())):
            add(owner, "BOUNCE-BACK WATCH", _t_bounce_back)

        drought = _current_drought(rec, last_season_year)
        if drought >= 2:
            add(owner, "DROUGHT WATCH", _t_drought, drought=drought)

    # Biggest single-season point jump into last_season_year, league-wide
    improvements = [
        {'owner': owner, 'delta': rec['season_points'][last_season_year] - rec['season_points'][last_season_year - 1]}
        for owner, rec in owners.items()
        if last_season_year in rec['season_points'] and (last_season_year - 1) in rec['season_points']
    ]
    if improvements:
        best_jump = max(improvements, key=lambda i: i['delta'])
        if best_jump['delta'] > 0:
            add(best_jump['owner'], "BREAKOUT", _t_breakout, delta=best_jump['delta'])

    # Longest-tenured owner still chasing a first championship
    ringless = [(owner, len(rec['years'])) for owner, rec in owners.items() if rec['championships'] == 0]
    if ringless:
        owner, seasons = max(ringless, key=lambda x: x[1])
        if seasons >= 3:
            add(owner, "OG STATUS", _t_og_status, seasons=seasons)

    return _combine_by_owner(raw)


def _combine_by_owner(raw):
    """Merge every storyline hit for the same owner into a single card - the
    first sentence renders lead=True (keeps their name), every sentence after it
    renders lead=False (opens with a grammatically-correct 'They') so a
    multi-storyline owner doesn't read like three separate headlines stapled
    together."""
    grouped, order = {}, []
    for item in raw:
        owner = item['owner']
        if owner not in grouped:
            grouped[owner] = []
            order.append(owner)
        grouped[owner].append(item)

    combined = []
    for owner in order:
        items = grouped[owner]
        sentences = [
            item['template'](owner, i == 0, **item['kwargs'])
            for i, item in enumerate(items)
        ]
        combined.append({
            'owner': owner,
            'tags': [item['tag'] for item in items],
            'text': " ".join(sentences),
        })
    return combined


def _current_season_streak(rec, year):
    """(result, length) for an owner's trailing run of same-result games
    within `year` only, sorted by week - e.g. ('W', 3) for three straight
    wins. (None, 0) if they haven't played `year` at all or have no games
    yet (the weeks that exist are already bounded to completed ones by
    espn_data._last_completed_week, so this only ever reflects real,
    decided games)."""
    season_games = sorted(
        (g for g in rec['game_log'] if g['year'] == year),
        key=lambda g: g['week'],
    )
    if not season_games:
        return None, 0
    result = season_games[-1]['result']
    length = 0
    for g in reversed(season_games):
        if g['result'] != result:
            break
        length += 1
    return result, length


# Rumors are attributed to a fixed set of "insider account" handles by
# category, not to any real league member - these are gossip ABOUT owners,
# never gossip framed as coming FROM one.
_RUMOR_HANDLES = {
    'trade': '@LeagueWire',
    'waiver': '@WaiverWatch',
    'streak': '@HotColdTracker',
    'playoff_race': '@PlayoffPulse',
}

# A waiver pickup only reads as rumor-worthy "tea" past some real spend - a
# $0 free-agent add isn't gossip, a $40 FAAB bid on a bench piece is.
BIG_WAIVER_BID_THRESHOLD = 15

# Below this point-differential, a trade grade reads as noise rather than a
# real early lean - the rumor hedges instead of crowning a winner.
TRADE_GRADE_MARGIN = 3.0


def compute_player_season_totals(season_box_scores):
    """{player_name: total fantasy points scored so far this season}, summed
    across every completed week's box scores (starters and bench both, since
    a player's real stat line doesn't care whether they were benched) - lets
    the Rumor Mill grade a trade by actual, on-field production instead of
    just announcing it happened. `season_box_scores` is the
    {week: [matchup, ...]} shape espn_data.build_season_box_scores returns."""
    totals = {}
    for week_matchups in season_box_scores.values():
        for m in week_matchups:
            for lineup in (m['home_lineup'], m['away_lineup']):
                for p in lineup:
                    totals[p['name']] = totals.get(p['name'], 0.0) + p['points']
    return totals


def _trade_rumor(entry, player_points):
    """A trade rumor takes a side, the way a real hot-take account would -
    each traded player's season point total (player_points, from
    compute_player_season_totals) decides who's actually winning the deal so
    far, instead of just announcing that a trade happened."""
    team_a, gave_a = entry['team_a'], entry['players_a']
    team_b, gave_b = entry['team_b'], entry['players_b']
    players_a_str = ", ".join(gave_a)
    players_b_str = ", ".join(gave_b)
    headline = f"🚨 TRADE ALERT: {team_a} sent {players_a_str} to {team_b} for {players_b_str}"

    # team_a now holds gave_b, team_b now holds gave_a - compare what each
    # side actually walked away with, not what they gave up.
    pts_a_holds = sum(player_points.get(name, 0.0) for name in gave_b)
    pts_b_holds = sum(player_points.get(name, 0.0) for name in gave_a)

    if pts_a_holds == 0 and pts_b_holds == 0:
        text = (
            f"{headline}. Nobody's played a snap yet, so there's no verdict - just vibes. "
            f"We'll be grading this one hard once the sample size catches up."
        )
    else:
        diff = abs(pts_a_holds - pts_b_holds)
        winner, winner_holds, winner_pts = (
            (team_a, players_b_str, pts_a_holds) if pts_a_holds >= pts_b_holds
            else (team_b, players_a_str, pts_b_holds)
        )
        loser, loser_holds, loser_pts = (
            (team_b, players_a_str, pts_b_holds) if pts_a_holds >= pts_b_holds
            else (team_a, players_b_str, pts_a_holds)
        )
        loser_first = loser.split()[0]
        if diff < TRADE_GRADE_MARGIN:
            text = (
                f"{headline}. Early numbers are basically dead even ({winner_pts:.1f} to "
                f"{loser_pts:.1f}) - too soon to crown a winner, but the receipts are being kept."
            )
        else:
            text = (
                f"{headline} - and it's not close. {winner_holds} has outscored {loser_holds} "
                f"{winner_pts:.1f} to {loser_pts:.1f} this season. {loser_first}, you good?"
            )
    return {'handle': _RUMOR_HANDLES['trade'], 'category': 'trade', 'text': text}


def compute_rumors(owners, award_races, recent_activity, current_year, player_points=None):
    """The Rumor Mill's Twitter/X-style feed - every entry traces back to a
    real, checkable fact (a real trade, a real waiver bid, a real in-season
    streak, real standings), just delivered in a gossipy, hot-take voice
    instead of the League Insider section's newspaper one. `player_points`
    (compute_player_season_totals' output) is optional - without it, trade
    rumors fall back to the "no verdict yet" framing. Returns
    [{'handle', 'text', 'category'}, ...], newest/most-relevant first."""
    rumors = []
    player_points = player_points or {}

    for entry in recent_activity:
        if entry['kind'] == 'trade':
            rumors.append(_trade_rumor(entry, player_points))
        elif entry['kind'] == 'move' and entry['action'] == 'WAIVER ADDED' \
                and entry['bid_amount'] >= BIG_WAIVER_BID_THRESHOLD:
            rumors.append({
                'handle': _RUMOR_HANDLES['waiver'],
                'category': 'waiver',
                'text': (
                    f"👀 {entry['team']} just dropped ${entry['bid_amount']} in FAAB on "
                    f"{entry['player']}. That's not a casual add - somebody's chasing a title."
                ),
            })

    for owner, rec in owners.items():
        if current_year not in rec['years']:
            continue
        result, length = _current_season_streak(rec, current_year)
        if result == 'W' and length >= 3:
            rumors.append({
                'handle': _RUMOR_HANDLES['streak'],
                'category': 'streak',
                'text': f"🔥 {owner} has won {length} straight. Are we sure this league isn't rigged?",
            })
        elif result == 'L' and length >= 3:
            rumors.append({
                'handle': _RUMOR_HANDLES['streak'],
                'category': 'streak',
                'text': (
                    f"💀 {owner} is on a {length}-game skid. Sources close to the team "
                    f"describe the mood in the war room as \"not great.\""
                ),
            })

    playoff_race = award_races.get('playoff_race', [])
    playoff_team_count = award_races.get('playoff_team_count', 6)
    if len(playoff_race) > playoff_team_count >= 1:
        last_in = playoff_race[playoff_team_count - 1]
        first_out = playoff_race[playoff_team_count]
        games_back = (last_in['wins'] - last_in['losses']) - (first_out['wins'] - first_out['losses'])
        if games_back <= 1:
            rumors.append({
                'handle': _RUMOR_HANDLES['playoff_race'],
                'category': 'playoff_race',
                'text': (
                    f"😬 {last_in['owner']} is clinging to the final playoff spot with "
                    f"{first_out['owner']} breathing down their neck. Expect some desperate "
                    f"waiver moves before this is over."
                ),
            })

    return rumors


def compute_award_races(snapshot):
    """Playoff race, top-scoring teams, and MVP race from a live current-season
    snapshot (espn_data.get_current_season_snapshot). Assumes the caller has
    already checked snapshot['season_started']."""
    teams = snapshot['teams']
    playoff_team_count = snapshot.get('playoff_team_count') or 6

    standings = sorted(
        teams.items(),
        key=lambda kv: (-(kv[1]['wins'] - kv[1]['losses']), -kv[1]['points_for']),
    )
    playoff_race = [
        {
            'owner': owner,
            'team_name': t['team_name'],
            'wins': t['wins'],
            'losses': t['losses'],
            'ties': t['ties'],
            'points_for': t['points_for'],
            'in_playoff_position': i < playoff_team_count,
        }
        for i, (owner, t) in enumerate(standings)
    ]

    top_scoring = sorted(
        ({'owner': owner, 'team_name': t['team_name'], 'points_for': t['points_for']}
         for owner, t in teams.items()),
        key=lambda r: r['points_for'], reverse=True,
    )[:5]

    all_players = [
        {**p, 'owner': owner, 'team_name': t['team_name']}
        for owner, t in teams.items() for p in t['players']
    ]
    mvp_race = sorted(all_players, key=lambda p: p['points'] or 0, reverse=True)[:8]

    return {
        'playoff_race': playoff_race,
        'top_scoring': top_scoring,
        'mvp_race': mvp_race,
        'playoff_team_count': playoff_team_count,
    }
