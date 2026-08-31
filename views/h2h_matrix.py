import pandas as pd
import streamlit as st

from common import PALETTE, configure_page, render_footer, render_mini_board, render_sidebar_info
from espn_data import create_h2h_matrix, get_credentials

configure_page("H2H Matrix")
league_id, espn_s2, swid = get_credentials()

st.header(":material/swords: H2H Matrix")

start_year, end_year = 2019, 2026

st.sidebar.markdown("---")
st.sidebar.info(
    "**Welcome to the 2026 season!** History from every prior season is already "
    "baked in below - live 2026 games will join it once the season kicks off.",
    icon=":material/celebration:",
)

matrix_type = st.radio(
    "Select records type:",
    ["Regular Season Only", "Playoffs Only", "All Games"],
    horizontal=True,
)

record_type = {"Regular Season Only": "regular", "Playoffs Only": "playoffs", "All Games": "all"}[matrix_type]
cache_key = f'h2h_matrix_{record_type}_{start_year}_{end_year}'

if cache_key not in st.session_state:
    with st.spinner(f"Processing {matrix_type.lower()} data... this may take a few minutes..."):
        try:
            st.session_state[cache_key] = create_h2h_matrix(league_id, start_year, end_year, espn_s2, swid, record_type=record_type)
        except Exception as e:
            st.error(f"Error generating H2H matrix: {e}")

if cache_key not in st.session_state:
    st.info("Matrix generation failed - check your league configuration")
    st.stop()

h2h_matrix = st.session_state[cache_key]

# --- Individual owner H2H record --------------------------------------------
st.subheader(":material/person: Individual H2H Record")
owners = list(h2h_matrix.index)
selected_owner = st.selectbox("Select an owner:", owners)

if selected_owner:
    opponent_rows = []
    for opponent, record in h2h_matrix.loc[selected_owner].items():
        if record == "-":
            continue
        wins, losses = (int(x) for x in record.split("-"))
        total = wins + losses
        opponent_rows.append({
            'owner': opponent,
            'wins': wins,
            'losses': losses,
            'win_pct': (wins / total) if total > 0 else 0.0,
        })
    opponent_rows.sort(key=lambda r: r['win_pct'], reverse=True)

    render_mini_board(
        opponent_rows,
        [("Record", lambda r: f"{r['wins']}-{r['losses']}")],
        key_prefix=f"h2h-{selected_owner}",
    )

st.markdown("---")

# --- Full matrix --------------------------------------------------------------
st.subheader(matrix_type)
st.caption("Row's H2H record vs. column · format: Wins-Losses")


def style_matrix(val):
    if val == "-":
        return f"background-color: {PALETTE['surface']}; text-align: center; font-weight: bold; color: {PALETTE['ink_muted']}"
    else:
        return f"background-color: {PALETTE['page']}; text-align: center; font-weight: bold; color: {PALETTE['ink_primary']}"


styled_matrix = h2h_matrix.style.map(style_matrix)
st.dataframe(styled_matrix, width='stretch')

render_sidebar_info()
render_footer()
