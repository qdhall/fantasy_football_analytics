import concurrent.futures
from datetime import datetime

import streamlit as st

from common import (
    configure_page,
    get_league_history,
    render_footer,
    render_matchup_carousel,
    render_mini_board,
    render_sidebar_info,
    render_trivia_carousel,
)
from espn_data import (
    get_credentials,
    get_current_season_snapshot,
    get_current_week_matchups,
    get_league_scoring_settings,
)
from home_stats import compute_award_races
from league_stats import compute_league_trivia
from matchup_predictor_stats import compute_espn_only_prediction, compute_matchup_prediction, estimate_score_std
from odds_data import fetch_current_nfl_odds, parse_player_props, parse_team_implied_totals

configure_page("Fantasy Football Analytics")

# A slightly greyer tint than the rest of the app's warm-white pages, so the
# portal reads as its own "landing" space rather than just another stats page.
st.markdown(
    '<style>[data-testid="stAppViewContainer"] { background-color: #ececea; }</style>',
    unsafe_allow_html=True,
)

st.title(":material/sports_football: League Portal")
st.caption("Athletic Enough to Play Fantasy Football")

current_year = datetime.now().year

owners = get_league_history()

if not owners:
    st.error("Could not load league history. Check your league credentials.")
    st.stop()

# --- League Trivia carousel ---------------------------------------------------
header_col, link_col = st.columns([5, 1.4])
with header_col:
    st.markdown("### :material/casino: League Trivia")
    st.caption("A few of the league's all-time numbers - cycling automatically.")
with link_col:
    st.write("")
    st.page_link("views/league_trivia.py", label="View All Trivia", icon=":material/casino:")

trivia = {k: v for k, v in compute_league_trivia(owners).items() if v}
render_trivia_carousel(trivia)

st.markdown("---")

# --- Live data: fetched once per session, in parallel -------------------------
# get_current_week_matchups, fetch_current_nfl_odds, get_league_scoring_settings,
# and get_current_season_snapshot are four independent live calls - none of them
# need each other's result, they were just being awaited one after another
# (measured ~10s combined), which is why everything below League Trivia (whose
# data is cheap and already disk/R2-cached) used to sit there blank for a
# beat. Running them concurrently cuts that to roughly the slowest single call,
# and caching the bundle in session_state means every rerun after the first
# (clicking anything, anywhere in the app) is instant instead of re-paying that
# cost on every single interaction.
league_id, espn_s2, swid = get_credentials()

if 'home_live_data' not in st.session_state:
    with st.spinner(f"Pulling live {current_year} matchups, odds, and standings..."):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            matchups_future = executor.submit(get_current_week_matchups, league_id, current_year, espn_s2, swid)
            odds_future = executor.submit(fetch_current_nfl_odds)
            scoring_future = executor.submit(get_league_scoring_settings, league_id, current_year, espn_s2, swid)
            snapshot_future = executor.submit(get_current_season_snapshot, league_id, current_year, espn_s2, swid)

            st.session_state['home_live_data'] = {
                'matchups': matchups_future.result(),
                'odds_events': odds_future.result(),
                'scoring_settings': scoring_future.result(),
                'snapshot': snapshot_future.result(),
            }

live_data = st.session_state['home_live_data']
# current_season_snapshot is also used standalone elsewhere in this session
# (e.g. League News' Rumor Mill) - keep that key populated too.
st.session_state['current_season_snapshot'] = live_data['snapshot']

# --- Matchups and Predictions carousel ------------------------------------------
header_col, link_col = st.columns([5, 1.4])
with header_col:
    st.markdown("### :material/insights: Matchups and Predictions")
    st.caption("This week's Vegas line vs. ESPN's own projection, cycling automatically.")
with link_col:
    st.write("")
    st.page_link("views/matchup_predictor.py", label="Full Scoreboard", icon=":material/insights:")

matchups = live_data['matchups']
if matchups:
    odds_lookup = parse_player_props(live_data['odds_events'])
    team_implied_totals = parse_team_implied_totals(live_data['odds_events'])
    scoring_settings = live_data['scoring_settings']
    score_std = estimate_score_std(owners)

    predictions = []
    for m in matchups:
        vegas_pred = compute_matchup_prediction(
            m['home_lineup'], m['away_lineup'], odds_lookup, scoring_settings, team_implied_totals, score_std)
        espn_pred = compute_espn_only_prediction(m['home_projected'], m['away_projected'], score_std)
        predictions.append((m, vegas_pred, espn_pred))

    render_matchup_carousel(predictions)
else:
    st.info("No live matchups yet this week.", icon=":material/schedule:")

st.markdown("---")

# --- Award races & playoff picture ---------------------------------------------
st.markdown("### :material/emoji_events: Award Races & Playoff Picture")

snapshot = live_data['snapshot']

if not snapshot['season_started']:
    st.info(
        f"The {current_year} season hasn't kicked off yet - once Week 1 is in the books, "
        f"this section will show the live Playoff Race, Top Scoring Teams, and MVP Race.",
        icon=":material/campaign:",
    )
else:
    races = compute_award_races(snapshot)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("##### :material/swords: Playoff Race")
        playoff_rows = races['playoff_race'][:races['playoff_team_count'] + 2]
        render_mini_board(
            playoff_rows,
            [("W-L", lambda r: f"{r['wins']}-{r['losses']}" + (f"-{r['ties']}" if r['ties'] else "")),
             ("PF", lambda r: f"{r['points_for']:,.1f}")],
            subtitle_key='team_name', key_prefix='playoff',
        )

    with col2:
        st.markdown("##### :material/bar_chart: Top Scoring Teams")
        render_mini_board(
            races['top_scoring'],
            [("PF", lambda r: f"{r['points_for']:,.1f}")],
            subtitle_key='team_name', key_prefix='scoring',
        )

    with col3:
        st.markdown("##### :material/military_tech: MVP Race")
        render_mini_board(
            races['mvp_race'],
            [("Pts", lambda r: f"{r['points']:,.1f}")],
            name_key='player', subtitle_key='owner', key_prefix='mvp',
        )

render_sidebar_info()
render_footer()
