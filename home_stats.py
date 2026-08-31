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
