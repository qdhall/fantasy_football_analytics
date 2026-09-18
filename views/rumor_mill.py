import concurrent.futures

import streamlit as st

from common import configure_page, get_league_history, render_footer, render_rumor_feed, render_sidebar_info
from espn_data import build_season_box_scores, get_credentials, get_current_season_snapshot, get_recent_activity
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

# recent_activity, this season's box scores (needed to grade a trade), and
# the season snapshot are three independent live calls - box scores in
# particular walks every week played so far, which is the slow one. Same
# fix as the Home page's live-data section: run them concurrently instead of
# one after another.
box_score_cache = st.session_state.setdefault('season_box_scores_cache', {})
with st.spinner("Loading recent activity, this season's box scores, and standings..."):
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        activity_future = executor.submit(get_recent_activity, league_id, current_year, espn_s2, swid, 25)
        snapshot_future = executor.submit(get_current_season_snapshot, league_id, current_year, espn_s2, swid)
        # Shared with Matchup History's own per-year cache key, so if that
        # page has already pulled this season's box scores this session,
        # this reuses it for free instead of re-fetching.
        if current_year not in box_score_cache:
            box_scores_future = executor.submit(build_season_box_scores, league_id, current_year, espn_s2, swid)
            box_score_cache[current_year] = box_scores_future.result()

        recent_activity = activity_future.result()
        if 'current_season_snapshot' not in st.session_state:
            st.session_state['current_season_snapshot'] = snapshot_future.result()

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
