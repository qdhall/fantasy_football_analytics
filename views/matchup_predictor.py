import concurrent.futures

import pandas as pd
import streamlit as st

from common import (
    ESPN_THEME,
    VEGAS_THEME,
    PALETTE,
    configure_page,
    get_league_history,
    render_footer,
    render_sidebar_info,
    render_sportsbook_card,
)
from espn_data import (
    build_season_box_scores,
    get_credentials,
    get_current_week_matchups,
    get_league_scoring_settings,
)
from matchup_predictor_stats import (
    compute_ats_records,
    compute_espn_only_prediction,
    compute_matchup_prediction,
    estimate_score_std,
)
from odds_data import fetch_current_nfl_odds, get_odds_api_key, parse_player_props, parse_team_implied_totals

configure_page("Scoreboard & Matchup Predictor")

st.header(":material/insights: Scoreboard & Matchup Predictor")
st.caption(
    "A Vegas-style line for every matchup this week, set side by side against ESPN's own projected-points "
    "line so you can see exactly where - and how much - real sportsbook data changes the picture. Each "
    "player's Vegas-side projection blends a real player-prop line (when one exists), a team-level Vegas "
    "game line, and ESPN's own projection, then both sides turn their score gap into a spread and a win "
    "probability using this league's own real scoring volatility - the same math a sportsbook uses to set "
    "a line, calibrated to this league instead of a guess."
)

if not get_odds_api_key():
    st.warning(
        "No odds API key configured (`sportsgameodds_api_key` in secrets) - the Vegas line will fall back "
        "to ESPN-only projections until one is added.",
        icon=":material/key_off:",
    )

owners = get_league_history()
if not owners:
    st.error("Could not load league history. Check your league credentials.")
    st.stop()

league_id, espn_s2, swid = get_credentials()

TIER_LABELS = {
    'actual': 'Actual (game over)',
    'vegas_direct': 'Vegas player prop',
    'vegas_stats': 'Vegas per-stat props',
    'vegas_team_share': 'Vegas team line',
    'espn_only': 'ESPN projection only',
}

# This week's matchups, Vegas odds, scoring settings, and (unless another
# page already cached it this session) the current season's box scores for
# ATS records are four independent live calls - same fix as Home's live-data
# section: run them concurrently instead of one after another, since none
# of them need each other's result.
box_score_cache = st.session_state.setdefault('season_box_scores_cache', {})
with st.spinner("Loading this week's matchups, odds, and Against-the-Spread records..."):
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        matchups_future = executor.submit(get_current_week_matchups, league_id, 2026, espn_s2, swid)
        odds_future = executor.submit(fetch_current_nfl_odds)
        scoring_future = executor.submit(get_league_scoring_settings, league_id, 2026, espn_s2, swid)
        box_scores_future = None
        if 2026 not in box_score_cache:
            box_scores_future = executor.submit(build_season_box_scores, league_id, 2026, espn_s2, swid)

        matchups = matchups_future.result()
        odds_events = odds_future.result()
        scoring_settings = scoring_future.result()
        if box_scores_future is not None:
            box_score_cache[2026] = box_scores_future.result()

if not matchups:
    st.info("No live matchups found for the current week yet.", icon=":material/schedule:")
    render_sidebar_info()
    render_footer()
    st.stop()

odds_lookup = parse_player_props(odds_events)
team_implied_totals = parse_team_implied_totals(odds_events)
score_std = estimate_score_std(owners)

# ATS records are scoped to the current season only - the full 2019-2026
# history was a one-time crunch that only ever gets slower as more seasons
# pile up, for a record that's meant to answer "who's actually beating
# their own projection lately," not an all-time leaderboard.
if 'matchup_predictor_ats' not in st.session_state:
    st.session_state['matchup_predictor_ats'] = compute_ats_records({2026: box_score_cache[2026]})

ats_records = st.session_state['matchup_predictor_ats']

predictions = []
for m in matchups:
    vegas_pred = compute_matchup_prediction(
        m['home_lineup'], m['away_lineup'], odds_lookup, scoring_settings, team_implied_totals, score_std)
    espn_pred = compute_espn_only_prediction(m['home_projected'], m['away_projected'], score_std)
    predictions.append((m, vegas_pred, espn_pred))

st.markdown(
    f"""
    <div style="background:linear-gradient(135deg, #14181f, #1d2430);border-radius:14px;
                padding:14px 22px;display:flex;align-items:center;justify-content:space-between;
                margin:20px 0 22px;border:1px solid #2a2f3d;">
      <div style="display:flex;align-items:center;gap:10px;">
        <span style="width:8px;height:8px;border-radius:50%;background:{PALETTE['categorical'][2]};
                     display:inline-block;box-shadow:0 0 8px {PALETTE['categorical'][2]};"></span>
        <span style="color:#f7f3ea;font-weight:800;letter-spacing:0.08em;text-transform:uppercase;
                     font-size:0.82rem;">This Week's Board</span>
      </div>
      <span style="color:{PALETTE['categorical'][3]};font-weight:700;font-size:0.78rem;">
        {len(predictions)} Matchups</span>
    </div>
    """,
    unsafe_allow_html=True,
)

for i, (m, vegas_pred, espn_pred) in enumerate(predictions):
    st.markdown(
        f'<div style="font-weight:700;color:{PALETTE["ink_muted"]};font-size:0.85rem;'
        f'text-transform:uppercase;letter-spacing:0.04em;margin:18px 0 8px;">'
        f'{m["home_team_name"]} vs {m["away_team_name"]}</div>',
        unsafe_allow_html=True,
    )
    with st.container(key=f"card-matchup-{i}"):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(
                render_sportsbook_card(VEGAS_THEME, "Vegas Projection", m, vegas_pred, True, ats_records),
                unsafe_allow_html=True,
            )
        with col2:
            st.markdown(
                render_sportsbook_card(ESPN_THEME, "ESPN Projection", m, espn_pred, False),
                unsafe_allow_html=True,
            )

st.markdown("---")
st.subheader(":material/query_stats: Full Breakdown")

matchup_labels = [f"{m['home_team_name']} vs {m['away_team_name']}" for m, _, _ in predictions]
selected_label = st.selectbox("Select a matchup:", matchup_labels)
selected_idx = matchup_labels.index(selected_label)
sel_m, sel_pred, _ = predictions[selected_idx]


def _zebra_stripe(row):
    color = PALETTE['surface'] if row.name % 2 == 0 else 'transparent'
    return [f'background-color: {color}'] * len(row)


def _breakdown_table(breakdown):
    df = pd.DataFrame([
        {
            'Player': b['name'],
            'Pos': b['position'],
            'Points': b['points'],
            'Source': TIER_LABELS.get(b['tier'], b['tier']),
        }
        for b in sorted(breakdown, key=lambda b: b['points'], reverse=True)
    ])
    styled = df.style.apply(_zebra_stripe, axis=1).format({'Points': '{:.1f}'})
    st.dataframe(styled, width='stretch', hide_index=True)


col1, col2 = st.columns(2)
with col1:
    st.write(f"**{sel_m['home_team_name']}** ({sel_m['home_owner']}) - {sel_pred['home_projected']:.1f} pts")
    _breakdown_table(sel_pred['home_breakdown'])
with col2:
    st.write(f"**{sel_m['away_team_name']}** ({sel_m['away_owner']}) - {sel_pred['away_projected']:.1f} pts")
    _breakdown_table(sel_pred['away_breakdown'])

render_sidebar_info()
render_footer()
