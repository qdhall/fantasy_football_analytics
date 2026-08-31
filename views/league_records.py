import streamlit as st

from common import configure_page, get_league_history, render_footer, render_record_grid, render_sidebar_info
from league_stats import compute_group_records

configure_page("League Records")

st.header(":material/military_tech: League Records")
st.caption("Every 'who has the most' record in league history - titles, streaks, scoring, and tenure.")

owners = get_league_history()

if not owners:
    st.error("Could not load league history. Check your league credentials.")
    st.stop()

records = {k: v for k, v in compute_group_records(owners).items() if v}
render_record_grid("records", records)

render_sidebar_info()
render_footer()
