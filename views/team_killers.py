import streamlit as st

from common import PALETTE, configure_page, get_league_history, render_footer, render_leaderboard, render_sidebar_info
from do_not_draft_stats import compute_do_not_draft_candidates, format_curse_rubric
from espn_data import build_front_office_history, get_active_player_ids, get_credentials

DISPLAY_COUNT = 50

configure_page("Team Killers")

st.header(":material/block: Team Killers")
st.markdown(f'<div style="color:{PALETTE["ink_primary"]};font-weight:600">Do Not Draft!</div>', unsafe_allow_html=True)
st.caption(format_curse_rubric())

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

candidates = compute_do_not_draft_candidates(gm_history, owners)

if 'dnd_active_ids' not in st.session_state:
    with st.spinner("Checking which of these players are still active for 2026..."):
        st.session_state['dnd_active_ids'] = get_active_player_ids(
            league_id, 2026, espn_s2, swid, [c['player_id'] for c in candidates])

active_ids = st.session_state['dnd_active_ids']
active_candidates = [c for c in candidates if c['player_id'] in active_ids]

st.caption(
    f"{len(active_candidates)} of {len(candidates)} historically-cursed players are still "
    "active AND draft-relevant for 2026 - retired, unrosterable, and deep-waiver-tier "
    "players (under a 100-point season projection) are left off this list entirely."
)

display_rows = [
    {**r, 'owner': r['player_name'], 'score': r['curse_score'], 'rank': i + 1}
    for i, r in enumerate(active_candidates[:DISPLAY_COUNT])
]

render_leaderboard(display_rows, [
    ("Seasons", "seasons"),
    ("Teams' Win %", "team_win_pct"),
    ("Teams' Record", "team_record"),
    ("Bad Week Rate", "bad_week_rate"),
    ("% Playoff Seasons", "playoff_rate"),
    ("% DFL Seasons", "dfl_rate"),
    ("Championships", "championships"),
    ("IR Weeks/Season", "ir_weeks_per_season"),
], score_fmt="{:.1f}")

render_sidebar_info()
render_footer()
