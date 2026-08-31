import streamlit as st

from common import render_custom_nav, render_nav_auto_collapse, render_nav_icon_defs

pages = [
    st.Page("views/home.py", title="Home", default=True),
    st.Page("views/all_time_rankings.py", title="All-Time Rankings"),
    st.Page("views/league_records.py", title="League Records"),
    st.Page("views/wall_of_shame.py", title="Wall of Shame"),
    st.Page("views/league_trivia.py", title="League Trivia"),
    st.Page("views/front_office.py", title="Front Office"),
    st.Page("views/team_overview.py", title="Team Overview"),
    st.Page("views/luck_index.py", title="Luck Index"),
    st.Page("views/team_killers.py", title="Team Killers (Do Not Draft)"),
    st.Page("views/h2h_matrix.py", title="H2H Matrix"),
    st.Page("views/player_analysis.py", title="Player Analysis"),
    st.Page("views/matchup_predictor.py", title="Matchup Predictor"),
    st.Page("views/season_stats.py", title="Season Stats"),
    st.Page("views/matchup_history.py", title="Matchup History"),
]

# The native nav is hidden and replaced by render_custom_nav so each page can
# get a gold gradient + bevel + shimmer icon instead of a flat Material one -
# st.page_link still handles the actual routing/active-page state, this only
# changes what's drawn next to the label.
nav = st.navigation(pages, position="hidden")
render_nav_icon_defs()
render_custom_nav(pages)
render_nav_auto_collapse()
nav.run()
