import streamlit as st

from common import configure_page, get_league_history, render_footer, render_leaderboard, render_sidebar_info
from espn_data import build_front_office_history, get_credentials
from luck_stats import compute_luck_index, format_luck_rubric

configure_page("Luck Index")

st.header(":material/casino: Luck Index")

st.subheader(":material/schedule: 2026 Season Luck")
st.info(
    "The season hasn't kicked off yet - once games start, this section will break "
    "the same signals down for 2026 alone.",
    icon=":material/schedule:",
)

st.markdown("---")

st.subheader(":material/casino: All-Time Luck Index")
st.caption(format_luck_rubric())

owners = get_league_history()
if not owners:
    st.error("Could not load league history. Check your league credentials.")
    st.stop()

league_id, espn_s2, swid = get_credentials()
if 'front_office_history' not in st.session_state:
    with st.spinner(
        "Crunching draft picks and weekly box scores (2019-2026)... this pulls a LOT "
        "more data than the rest of this page, so it can take a few minutes the first time"
    ):
        st.session_state['front_office_history'] = build_front_office_history(
            league_id, 2019, 2026, espn_s2, swid)

gm_history, coach_history, draft_log, luck_history = st.session_state['front_office_history']

rankings = compute_luck_index(owners, gm_history, luck_history)
render_leaderboard(rankings, [
    ("Pythagorean Luck Share", "pythagorean_luck"),
    ("Boom-Win Share", "boom_win_rate"),
    ("Health Luck", "health_luck"),
    ("Close-Game Luck (context)", "close_game_luck"),
], score_fmt="{:.1f}")

render_sidebar_info()
render_footer()
