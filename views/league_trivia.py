import streamlit as st

from common import configure_page, get_league_history, render_footer, render_record_grid, render_sidebar_info
from espn_data import build_front_office_history, get_credentials
from front_office_stats import compute_front_office_trivia
from league_stats import compute_league_trivia

configure_page("League Trivia")

st.header(":material/casino: League Trivia")

owners = get_league_history()

if not owners:
    st.error("Could not load league history. Check your league credentials.")
    st.stop()

records = {k: v for k, v in compute_league_trivia(owners).items() if v}

league_id, espn_s2, swid = get_credentials()
if 'front_office_history' not in st.session_state:
    with st.spinner(
        "Crunching draft picks and weekly box scores (2019-2026)... this pulls a LOT "
        "more data than the rest of this page, so it can take a few minutes the first time"
    ):
        st.session_state['front_office_history'] = build_front_office_history(
            league_id, 2019, 2026, espn_s2, swid)

gm_history, coach_history, draft_log, luck_history = st.session_state['front_office_history']
if gm_history:
    fo_records = {k: v for k, v in compute_front_office_trivia(gm_history, coach_history, owners).items() if v}
    records.update(fo_records)

render_record_grid("trivia", records)

render_sidebar_info()
render_footer()
