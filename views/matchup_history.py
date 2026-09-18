from datetime import datetime

import pandas as pd
import streamlit as st

from common import PALETTE, configure_page, get_league_history, render_footer, render_sidebar_info
from db import ensure_synced, get_season_box_scores
from espn_data import get_credentials, get_slot_structure, optimal_lineup_points_from_dicts

configure_page("Matchup History")

st.header(":material/history: Matchup History")
st.caption(
    "A full week-by-week record of every matchup ever played - browse one team's "
    "season, or filter down to the head-to-head history between any two owners. "
    "Pick a week to pull up the complete box score: every starter and bench spot "
    "for both teams."
)

owners = get_league_history()
if not owners:
    st.error("Could not load league history. Check your league credentials.")
    st.stop()

league_id, espn_s2, swid = get_credentials()

FILTER_OPTIONS = ["All Games", "Regular Season", "Playoffs"]


def _filter_games(games, filter_choice):
    if filter_choice == "Regular Season":
        return [g for g in games if not g['is_playoff']]
    if filter_choice == "Playoffs":
        return [g for g in games if g['is_playoff']]
    return games


def _games_dataframe(games):
    return pd.DataFrame([
        {
            'Week': g['week'],
            'Opponent': g['opponent'],
            'Points': g['points'],
            'Opp Points': g['opp_points'],
            'Result': g['result'],
            'Type': "Playoff" if g['is_playoff'] else "Regular",
        }
        for g in games
    ])


def _zebra_stripe(row):
    color = PALETTE['surface'] if row.name % 2 == 0 else 'transparent'
    return [f'background-color: {color}'] * len(row)


def _result_color(val):
    color = {'W': PALETTE['status']['good'], 'L': PALETTE['status']['critical']}.get(val, PALETTE['ink_muted'])
    return f'color: {color}; font-weight: 700'


def _style_games(df):
    styled = df.style.apply(_zebra_stripe, axis=1).format({'Points': '{:,.1f}', 'Opp Points': '{:,.1f}'})
    if 'Result' in df.columns:
        styled = styled.map(_result_color, subset=['Result'])
    return styled


def _get_season_box_scores(year):
    if year >= datetime.now().year:
        ensure_synced(league_id, year, espn_s2, swid)
    cache = st.session_state.setdefault('season_box_scores_cache', {})
    if year not in cache:
        cache[year] = get_season_box_scores(league_id, year)
    return cache[year]


def _get_slot_structure(year):
    cache = st.session_state.setdefault('slot_structure_cache', {})
    if year not in cache:
        cache[year] = get_slot_structure(league_id, year, espn_s2, swid)
    return cache[year]


def _lineup_table(players, show_projected):
    if not players:
        st.caption("No players.")
        return
    rows = [
        {
            'Slot': p['slot'],
            'Player': p['name'],
            'Pos': p['position'],
            'Team': p['pro_team'] or '-',
            'Points': p['points'],
            **({'Projected': p['projected']} if show_projected else {}),
        }
        for p in players
    ]
    df = pd.DataFrame(rows)
    fmt = {'Points': '{:,.1f}'}
    if show_projected:
        fmt['Projected'] = '{:,.1f}'
    styled = df.style.apply(_zebra_stripe, axis=1).format(fmt)
    st.dataframe(styled, width='stretch', hide_index=True)


def _optimal_points(lineup, dedicated_slots, flex_slots):
    starters = [p for p in lineup if p['slot'] not in ('BE', 'IR')]
    bench = [p for p in lineup if p['slot'] in ('BE', 'IR')]
    if not dedicated_slots and not flex_slots:
        return sum(p['points'] for p in starters)
    return optimal_lineup_points_from_dicts(starters + bench, dedicated_slots, flex_slots)


def render_box_score(matchup, year):
    # ESPN stops serving real projected_points for a week once enough time has
    # passed (recent seasons return real numbers, older ones all come back as
    # a flat 0.0) - showing "Projected: 0.0" for every player on an old box
    # score would read as a data bug, so the column is dropped entirely
    # whenever nothing in this matchup actually has a nonzero projection.
    show_projected = any(
        p['projected'] > 0
        for lineup in (matchup['home_lineup'], matchup['away_lineup'])
        for p in lineup
    )
    if not show_projected:
        st.caption(
            "ESPN no longer serves pre-game projections for a matchup this old - "
            "only actual points are shown below.")

    # What each team's BEST possible lineup (starters + bench, picked with
    # hindsight) would have scored - answers "who would've won if both teams
    # started their optimal lineup", reusing the same greedy-fill selection
    # already proven correct for Coach Rankings (espn_data.optimal_lineup_points_from_dicts).
    dedicated_slots, flex_slots = _get_slot_structure(year)
    home_optimal = _optimal_points(matchup['home_lineup'], dedicated_slots, flex_slots)
    away_optimal = _optimal_points(matchup['away_lineup'], dedicated_slots, flex_slots)

    actual_winner = matchup['home_owner'] if matchup['home_score'] > matchup['away_score'] else matchup['away_owner']
    optimal_winner = matchup['home_owner'] if home_optimal > away_optimal else matchup['away_owner']
    if matchup['home_score'] != matchup['away_score'] and actual_winner != optimal_winner:
        st.warning(
            f"If both teams had started their optimal lineup, this game would have flipped: "
            f"**{optimal_winner}** would have won instead of {actual_winner}.",
            icon=":material/bolt:",
        )

    sides = [
        (matchup['home_owner'], matchup['home_score'], matchup['away_owner'], matchup['away_score'],
         matchup['home_lineup'], home_optimal),
        (matchup['away_owner'], matchup['away_score'], matchup['home_owner'], matchup['home_score'],
         matchup['away_lineup'], away_optimal),
    ]
    for owner, score, opp_owner, opp_score, lineup, optimal_points in sides:
        won = score > opp_score
        score_color = PALETTE['categorical'][0] if won else PALETTE['ink_muted']
        st.markdown(
            f'<div style="display:flex;align-items:baseline;gap:12px;margin:22px 0 8px;flex-wrap:wrap">'
            f'<span style="font-size:1.15rem;font-weight:700;color:{PALETTE["ink_primary"]}">{owner}</span>'
            f'<span style="font-size:1.5rem;font-weight:800;color:{score_color}">{score:,.1f}</span>'
            f'<span style="font-size:0.85rem;color:{PALETTE["ink_muted"]}">vs {opp_owner} ({opp_score:,.1f})</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        left_on_bench = optimal_points - score
        bench_note = "no points left on the bench" if left_on_bench <= 0.05 else f"{left_on_bench:,.1f} left on the bench"
        st.caption(f"Optimal lineup: {optimal_points:,.1f} pts ({bench_note})")

        starters = [p for p in lineup if p['slot'] not in ('BE', 'IR')]
        bench = [p for p in lineup if p['slot'] in ('BE', 'IR')]
        st.caption("Starters")
        _lineup_table(starters, show_projected)
        if bench:
            st.caption("Bench")
            _lineup_table(bench, show_projected)


def _find_matchup(year, week, owner_a, owner_b):
    week_matchups = _get_season_box_scores(year).get(week, [])
    for m in week_matchups:
        if {m['home_owner'], m['away_owner']} == {owner_a, owner_b}:
            return m
    return None


def _box_score_picker(games, owner_a, key_prefix):
    if not games:
        return
    options = {
        f"Week {g['week']}, {g['year']} vs {g['opponent']}"
        + (" (Playoff)" if g['is_playoff'] else ""): (g['year'], g['week'])
        for g in games
    }
    choice = st.selectbox("View a full box score:", list(options.keys()), key=f"{key_prefix}_box_pick")
    if choice:
        year, week = options[choice]
        opponent = next(g['opponent'] for g in games if g['year'] == year and g['week'] == week)
        matchup = _find_matchup(year, week, owner_a, opponent)
        if matchup:
            render_box_score(matchup, year)
        else:
            st.warning("Couldn't find lineup detail for that week - box score data may not be available for this season.")


tab_season, tab_h2h = st.tabs([":material/calendar_month: By Team & Season", ":material/swords: Head-to-Head"])

with tab_season:
    st.subheader(":material/calendar_month: By Team & Season")
    owner_names = sorted(owners.keys())
    selected_owner = st.selectbox("Owner", owner_names, key="mh_owner")

    years = sorted(owners[selected_owner]['years']) if selected_owner else []
    if not years:
        st.info(f"No season history available for {selected_owner}.", icon=":material/calendar_month:")
    else:
        selected_year = st.selectbox("Season", years, index=len(years) - 1, key="mh_year")
        filter_choice = st.segmented_control("Show:", FILTER_OPTIONS, default="All Games", key="mh_filter")
        filter_choice = filter_choice or "All Games"

        season_games = sorted(
            [g for g in owners[selected_owner]['game_log'] if g['year'] == selected_year],
            key=lambda g: g['week'])
        filtered = _filter_games(season_games, filter_choice)

        if not filtered:
            st.info(f"No {filter_choice.lower()} games found for {selected_owner} in {selected_year}.")
        else:
            record = f"{sum(1 for g in filtered if g['result'] == 'W')}-" \
                     f"{sum(1 for g in filtered if g['result'] == 'L')}-" \
                     f"{sum(1 for g in filtered if g['result'] == 'T')}"
            st.caption(f"{selected_owner} - {selected_year} - {record} across {len(filtered)} game(s)")
            st.dataframe(_style_games(_games_dataframe(filtered)), width='stretch', hide_index=True)

            st.markdown("---")
            _box_score_picker(filtered, selected_owner, key_prefix="season")

with tab_h2h:
    st.subheader(":material/swords: Head-to-Head")
    col_a, col_b = st.columns(2)
    with col_a:
        owner_a = st.selectbox("Owner A", owner_names, key="mh_owner_a")
    with col_b:
        other_owners = [o for o in owner_names if o != owner_a]
        owner_b = st.selectbox("Owner B", other_owners, key="mh_owner_b") if other_owners else None

    if owner_a and owner_b:
        filter_choice_h2h = st.segmented_control("Show:", FILTER_OPTIONS, default="All Games", key="mh_h2h_filter")
        filter_choice_h2h = filter_choice_h2h or "All Games"

        h2h_games = sorted(
            [g for g in owners[owner_a]['game_log'] if g['opponent'] == owner_b],
            key=lambda g: (g['year'], g['week']))
        filtered_h2h = _filter_games(h2h_games, filter_choice_h2h)

        if not filtered_h2h:
            st.info(f"{owner_a} and {owner_b} haven't played any {filter_choice_h2h.lower()} games against each other.")
        else:
            wins = sum(1 for g in filtered_h2h if g['result'] == 'W')
            losses = sum(1 for g in filtered_h2h if g['result'] == 'L')
            ties = sum(1 for g in filtered_h2h if g['result'] == 'T')
            st.caption(f"{owner_a} leads/trails {owner_b} {wins}-{losses}-{ties} across {len(filtered_h2h)} game(s)")
            st.dataframe(_style_games(_games_dataframe(filtered_h2h)), width='stretch', hide_index=True)

            st.markdown("---")
            _box_score_picker(filtered_h2h, owner_a, key_prefix="h2h")

render_sidebar_info()
render_footer()
