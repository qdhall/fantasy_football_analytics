import streamlit as st

from common import configure_page, get_front_office_history, get_league_history, render_footer, render_leaderboard, render_sidebar_info
from luck_stats import compute_luck_index, format_luck_rubric

configure_page("Luck Index")

st.header(":material/casino: Luck Index")

st.subheader(":material/schedule: 2026 Season Luck")
st.info(
    "2026 Season Luck will be available after Week 4 to allow a fair sample of data.",
    icon=":material/schedule:",
)

st.markdown("---")

st.subheader(":material/casino: All-Time Luck Index")
st.caption(format_luck_rubric())

owners = get_league_history()
if not owners:
    st.error("Could not load league history. Check your league credentials.")
    st.stop()

gm_history, coach_history, draft_log, luck_history = get_front_office_history()

rankings = compute_luck_index(owners, gm_history, luck_history)
render_leaderboard(rankings, [
    ("Pythagorean Luck Share", "pythagorean_luck"),
    ("Boom-Win Share", "boom_win_rate"),
    ("Health Luck", "health_luck"),
    ("Close-Game Luck (context)", "close_game_luck"),
], score_fmt="{:.1f}")

render_sidebar_info()
render_footer()
