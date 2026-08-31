import pandas as pd
import plotly.express as px
import streamlit as st

from common import PALETTE, configure_page, render_footer, render_sidebar_info, theme_plotly

configure_page("Matchup Predictor")

st.header(":material/insights: Matchup Predictor")

# Note about 2026 season
st.info("**2026 Season Ready!** Matchup predictor will use current season data as it becomes available.",
        icon=":material/sports_football:")

col1, col2 = st.columns(2)

with col1:
    st.subheader("Your Team")
    st.write("Projected Points: **147.5**")
    st.write("Confidence: **78%**")

with col2:
    st.subheader("Opponent")
    opponent = st.selectbox("Select opponent:", ["Team Alpha", "Team Beta", "Team Gamma"])
    st.write("Projected Points: **142.3**")
    st.write("Win Probability: **62%**")

# Matchup visualization
matchup_data = pd.DataFrame({
    'Position': ['QB', 'RB1', 'RB2', 'WR1', 'WR2', 'TE', 'FLEX', 'K', 'DST'],
    'Your_Team': [22, 18, 12, 16, 14, 11, 13, 9, 8],
    'Opponent': [19, 16, 14, 17, 15, 10, 11, 8, 7]
})

fig = px.bar(matchup_data, x='Position', y=['Your_Team', 'Opponent'],
             title='Position-by-Position Matchup Projection',
             barmode='group',
             color_discrete_sequence=PALETTE["categorical"])
st.plotly_chart(theme_plotly(fig), use_container_width=True)

render_sidebar_info()
render_footer()
