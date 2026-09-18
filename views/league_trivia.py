import streamlit as st

from common import configure_page, get_front_office_history, get_league_history, render_footer, render_record_grid, render_sidebar_info
from front_office_stats import compute_front_office_trivia
from league_stats import compute_league_trivia

configure_page("League Trivia")

st.header(":material/casino: League Trivia")

owners = get_league_history()

if not owners:
    st.error("Could not load league history. Check your league credentials.")
    st.stop()

records = {k: v for k, v in compute_league_trivia(owners).items() if v}

gm_history, coach_history, draft_log, luck_history = get_front_office_history()
if gm_history:
    fo_records = {k: v for k, v in compute_front_office_trivia(gm_history, coach_history, owners).items() if v}
    records.update(fo_records)

render_record_grid("trivia", records)

render_sidebar_info()
render_footer()
