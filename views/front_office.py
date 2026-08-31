import streamlit as st

from common import configure_page, render_footer, render_leaderboard, render_sidebar_info
from espn_data import build_front_office_history, get_credentials
from front_office_stats import compute_coach_rankings, compute_gm_rankings, format_gm_rubric

configure_page("Front Office")

st.header(":material/corporate_fare: Front Office")
st.caption(
    "GM Rankings grade roster-building: draft picks AND every other roster "
    "acquisition (trade or waiver/free agent), each classified as a "
    "Good/Bad/At-Expectation decision - working the wire well counts toward being a "
    "good GM just as drafting well does. Coach Rankings grade lineup decisions: how "
    "often the actual starting lineup matched the best possible lineup available "
    "from that week's real roster."
)

league_id, espn_s2, swid = get_credentials()

if 'front_office_history' not in st.session_state:
    with st.spinner(
        "Crunching draft picks and weekly box scores (2019-2026)... this pulls a LOT "
        "more data than the other pages, so it can take a few minutes the first time"
    ):
        st.session_state['front_office_history'] = build_front_office_history(
            league_id, 2019, 2026, espn_s2, swid)

gm_history, coach_history, draft_log, luck_history = st.session_state['front_office_history']

if not gm_history:
    st.error("Could not load draft/box score history. Check your league credentials.")
    st.stop()

st.header(":material/badge: GM Rankings")
st.caption(format_gm_rubric())
gm_rankings = compute_gm_rankings(gm_history)
render_leaderboard(gm_rankings, [
    ("Picks", "picks"),
    ("Acquisitions (Trades + Waiver Wire)", "acquisitions"),
    ("Points Scored", "total_actual"),
    ("Points Projected", "total_projected"),
    ("% Good Picks", "good_pct"),
    ("% At Expectation Picks", "expected_pct"),
    ("% Bad Picks", "bad_pct"),
    ("Players on IR", "players_on_ir"),
    ("Best Move", "best_move"),
    ("Worst Move", "worst_move"),
], score_fmt="{:.1f}")

st.markdown("---")

st.header(":material/sports: Coach Rankings")
st.caption("Score = % of starting-lineup slots that matched the optimal lineup available that week.")
coach_rankings = compute_coach_rankings(coach_history)
render_leaderboard(coach_rankings, [
    ("Correct Calls", "correct_calls"),
    ("Total Calls", "total_calls"),
    ("Weeks", "weeks"),
    ("Pts Left on Bench", "points_left_on_bench"),
    ("Avg Left/Week", "avg_points_left_per_week"),
], score_fmt="{:.1f}%")

render_sidebar_info()
render_footer()
