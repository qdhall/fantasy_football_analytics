import streamlit as st

from common import configure_page, get_league_history, render_footer, render_rumor_feed, render_sidebar_info
from db import ensure_synced, get_roster_moves, get_season_box_scores
from espn_data import get_credentials, get_current_season_snapshot
from home_stats import compute_award_races, compute_player_season_totals, compute_rumors

configure_page("Rumor Mill")

st.header(":material/campaign: Rumor Mill")
st.caption(
    "Hot takes and gossip from around the league - grounded in real trades, real waiver "
    "spend, real streaks, and real standings, delivered the way the league group chat "
    "actually talks trash."
)

owners = get_league_history()
if not owners:
    st.error("Could not load league history. Check your league credentials.")
    st.stop()

league_id, espn_s2, swid = get_credentials()
current_year = 2026

# Box scores and recent activity are now fast DB reads (see db.py), shared
# with Matchup History/Home/Matchup Predictor's own cache keys, so whichever
# page hits them first this session pays the cost once. Only the season
# snapshot is still a genuinely live ESPN call (it's cached process-wide for
# 120s at the espn_data layer, see get_current_season_snapshot).
ensure_synced(league_id, current_year, espn_s2, swid)
box_score_cache = st.session_state.setdefault('season_box_scores_cache', {})
if current_year not in box_score_cache:
    box_score_cache[current_year] = get_season_box_scores(league_id, current_year)

recent_activity = get_roster_moves(league_id, current_year, size=25)
if 'current_season_snapshot' not in st.session_state:
    st.session_state['current_season_snapshot'] = get_current_season_snapshot(league_id, current_year, espn_s2, swid)

player_points = compute_player_season_totals(box_score_cache[current_year])

snapshot = st.session_state['current_season_snapshot']
if snapshot['season_started']:
    award_races = compute_award_races(snapshot)
    rumors = compute_rumors(owners, award_races, recent_activity, current_year, player_points)
else:
    rumors = []

render_rumor_feed(rumors)

render_sidebar_info()
render_footer()
