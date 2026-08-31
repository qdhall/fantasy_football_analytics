import pandas as pd
import plotly.express as px
import streamlit as st

from common import PALETTE, configure_page, render_footer, render_sidebar_info, theme_plotly

configure_page("Season Stats")

st.header(":material/trending_up: Season Statistics")

# Note about 2026 season
st.info("**2026 Season Ready!** Statistics will populate as the season progresses.",
        icon=":material/sports_football:")

# League standings table
standings = pd.DataFrame({
    'Rank': [1, 2, 3, 4, 5],
    'Team': ['Team Alpha', 'Team Beta', 'Your Team', 'Team Gamma', 'Team Delta'],
    'Wins': [11, 10, 9, 8, 7],
    'Losses': [3, 4, 5, 6, 7],
    'Points For': [2190, 2156, 2145, 2089, 2034],
    'Points Against': [1987, 2023, 2067, 2156, 2178]
})

st.subheader(":material/leaderboard: League Standings")
st.dataframe(standings, width='stretch')

# Points distribution
st.subheader(":material/bar_chart: Points Distribution")
fig = px.histogram(standings, x='Points For', nbins=10,
                    title='League Points Distribution',
                    color_discrete_sequence=PALETTE["categorical"])
st.plotly_chart(theme_plotly(fig), use_container_width=True)

render_sidebar_info()
render_footer()
