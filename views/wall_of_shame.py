import streamlit as st

from common import configure_page, get_league_history, render_footer, render_record_grid, render_sidebar_info
from league_stats import compute_wall_of_shame

configure_page("Wall of Shame")

st.header(":material/skull: Wall of Shame")
st.caption("Every 'who has the least/worst' record in league history - the flip side of League Records.")

owners = get_league_history()

if not owners:
    st.error("Could not load league history. Check your league credentials.")
    st.stop()

records = {k: v for k, v in compute_wall_of_shame(owners).items() if v}
render_record_grid("shame", records)

render_sidebar_info()
render_footer()
