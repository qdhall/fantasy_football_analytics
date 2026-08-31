import pandas as pd
import plotly.express as px
import streamlit as st

from common import PALETTE, configure_page, render_footer, render_sidebar_info, theme_plotly
from espn_data import get_credentials, load_real_teams_data_full

configure_page("Player Analysis")
league_id, espn_s2, swid = get_credentials()

st.header(":material/person: Player Analysis")

if 'all_teams_data' not in st.session_state:
    with st.spinner("Loading player data..."):
        for year_to_try in [2026, 2025, 2024]:
            try:
                all_teams_data = load_real_teams_data_full(league_id, year_to_try, espn_s2, swid)

                # Skip years with no rosters yet (e.g. a season before the draft has happened)
                has_players = any(not team['players'].empty for team in all_teams_data.values())
                if all_teams_data and has_players:
                    st.session_state['all_teams_data'] = all_teams_data
                    break
            except Exception:
                continue

        if 'all_teams_data' not in st.session_state:
            st.error("Could not load team data.")
            st.stop()

all_teams_data = st.session_state['all_teams_data']

# Collect all players from all teams
all_players = []
for owner, team_data in all_teams_data.items():
    if not team_data['players'].empty:
        for _, player in team_data['players'].iterrows():
            player_dict = player.to_dict()
            player_dict['Owner'] = owner
            player_dict['Team Name'] = team_data['team_name']
            all_players.append(player_dict)

if not all_players:
    st.warning("No player data available.")
    st.stop()

all_players_df = pd.DataFrame(all_players)

# Player selector
player_options = [f"{row['Player']} ({row['Owner']})" for _, row in all_players_df.iterrows()]
selected_player_option = st.selectbox("Select a player:", player_options)

# Extract player name from selection
selected_player_name = selected_player_option.split(' (')[0]
selected_player_data = all_players_df[all_players_df['Player'] == selected_player_name].iloc[0]

# Display player info
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Position", selected_player_data['Position'], border=True)
with col2:
    st.metric("Total Points", f"{selected_player_data['Points']:.1f}", border=True)
with col3:
    st.metric("Avg Points", f"{selected_player_data['Avg Points']:.1f}", border=True)
with col4:
    st.metric("Pro Team", selected_player_data['Pro Team'], border=True)

# Additional player info
col5, col6 = st.columns(2)
with col5:
    st.metric("Owner", selected_player_data['Owner'], border=True)
with col6:
    st.metric("Injury Status", selected_player_data['Injury Status'], border=True)

# Position comparison chart
st.subheader(":material/leaderboard: Position Comparison")

# Filter players by same position
same_position_players = all_players_df[all_players_df['Position'] == selected_player_data['Position']]

if len(same_position_players) > 1:
    fig_comparison = px.bar(same_position_players.sort_values('Points', ascending=False),
                             x='Player', y='Points',
                             title=f'{selected_player_data["Position"]} Rankings by Total Points',
                             color='Points',
                             color_continuous_scale=PALETTE["sequential"],
                             hover_data=['Owner', 'Avg Points'])
    fig_comparison.update_layout(xaxis_tickangle=45)
    st.plotly_chart(theme_plotly(fig_comparison), use_container_width=True)

# League-wide position analysis
st.subheader(":material/query_stats: League Position Analysis")

position_stats = all_players_df.groupby('Position').agg({
    'Points': ['mean', 'max', 'min', 'count'],
    'Avg Points': 'mean'
}).round(2)

position_stats.columns = ['Avg Total Points', 'Max Points', 'Min Points', 'Player Count', 'Avg Per Game']
position_stats = position_stats.reset_index()

st.dataframe(position_stats, width='stretch')

render_sidebar_info()
render_footer()
