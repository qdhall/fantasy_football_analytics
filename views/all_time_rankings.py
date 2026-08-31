import streamlit as st

from common import configure_page, get_league_history, render_footer, render_rankings_table, render_sidebar_info
from league_stats import compute_goat_rankings, format_score_rubric

configure_page("All-Time Rankings")

st.header(":material/leaderboard: All-Time Rankings")
st.caption(format_score_rubric())

owners = get_league_history()

if not owners:
    st.error("Could not load league history. Check your league credentials.")
    st.stop()

rankings = compute_goat_rankings(owners)
render_rankings_table(rankings)

render_sidebar_info()
render_footer()
