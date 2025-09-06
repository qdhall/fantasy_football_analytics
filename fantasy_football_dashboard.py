import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
from datetime import datetime
from espn_api.football import League

# Page config
st.set_page_config(
    page_title="Fantasy Football Analytics",
    page_icon="🏈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Title and header
st.title("Athletic Enough to Play Fantasy Football: League Portal")
st.markdown("---")

# League configuration variables (hardcoded)
league_id = 23224200
espn_s2 = 'AEAeJkkoTaooG%2BUU5zr3ccb3p7rMEYzp2QPA%2F2Vh2dIO9EMvlN8xNqbuVSXa37QQiUn%2BrY9M5vIBwz94BNbJBNOERwRGpXaqo1013tLZCyBoYzvX1X1C%2BpDRtfXzgEyWSPe1ck1bRcEgF0XEKse%2BNKO7bAAgyz7Q7Z2dggtY16%2F3S5MbftgGoQ08brZh0G4z4FvEPc%2BGzUzDLEYS8lEX8CLIrUYDQkP%2FL0m%2F0k%2F7WxfThtbJ42blZENQsVMhJcUvewcMaOofh49SP3bNhnIXAqzDdt8l4RSbOGycrqu95c9YzibQRwKX%2FsyWpd5WR1%2BkHRQ%3D'
swid = '{1CE75B65-F3E4-4903-A75B-65F3E4E903A7}'

# Your actual H2H functions
def get_all_time_h2h_by_scores_fixed(league_id, start_year, end_year, espn_s2=None, swid=None):
    """Fixed version - correctly award wins to the team with the HIGHER score"""
    
    all_time_h2h = {}
    team_names = {}
    
    for year in range(start_year, end_year + 1):
        print(f"Processing {year} season...")
        
        try:
            league = League(league_id, year, espn_s2=espn_s2, swid=swid)
            
            for team in league.teams:
                team_names[team.team_id] = team.team_name
            
            max_week = league.current_week
            processed_games = set()
            
            for week in range(max_week):
                for team in league.teams:
                    if (week < len(team.schedule) and 
                        week < len(team.scores) and 
                        hasattr(team.schedule[week], 'team_id')):
                        
                        opponent = team.schedule[week]
                        team_score = team.scores[week]
                        opponent_score = opponent.scores[week]
                        
                        # Skip if no scores available
                        if team_score is None or opponent_score is None:
                            continue
                        
                        # Avoid double counting
                        game_id = tuple(sorted([team.team_id, opponent.team_id]))
                        full_game_id = (year, week, *game_id)
                        
                        if full_game_id in processed_games:
                            continue
                        processed_games.add(full_game_id)
                        
                        # FIX: Correctly determine winner by HIGHER score
                        if team_score > opponent_score:
                            # Team won (higher score)
                            winner_id = team.team_id
                            winner_name = team.team_name
                            loser_id = opponent.team_id
                            loser_name = opponent.team_name
                        elif opponent_score > team_score:
                            # Opponent won (higher score)
                            winner_id = opponent.team_id
                            winner_name = opponent.team_name
                            loser_id = team.team_id
                            loser_name = team.team_name
                        else:
                            continue  # Skip ties
                        
                        # Create consistent key (always smaller ID first for consistency)
                        key = tuple(sorted([team.team_id, opponent.team_id]))
                        
                        if key not in all_time_h2h:
                            all_time_h2h[key] = {team.team_id: 0, opponent.team_id: 0}
                        
                        # CRITICAL FIX: Record the win for the team with HIGHER score
                        all_time_h2h[key][winner_id] += 1
        
        except Exception as e:
            print(f"Error processing {year}: {e}")
            st.error(f"Error processing {year}: {e}")
    
    # Convert to readable format
    readable_records = {}
    for (team1_id, team2_id), wins_dict in all_time_h2h.items():
        team1_name = team_names.get(team1_id, f"Team {team1_id}")
        team2_name = team_names.get(team2_id, f"Team {team2_id}")
        
        team1_wins = wins_dict.get(team1_id, 0)
        team2_wins = wins_dict.get(team2_id, 0)
        
        # Create both directions for easy lookup
        key1 = f"{team1_name} vs {team2_name}"
        key2 = f"{team2_name} vs {team1_name}"
        
        readable_records[key1] = {
            'team1': team1_name,
            'team1_wins': team1_wins,
            'team2': team2_name,
            'team2_wins': team2_wins,
            'total_games': team1_wins + team2_wins
        }
        
        readable_records[key2] = {
            'team1': team2_name,
            'team1_wins': team2_wins,
            'team2': team1_name,
            'team2_wins': team1_wins,
            'total_games': team1_wins + team2_wins
        }
    
    return readable_records

def create_h2h_matrix(league_id, start_year, end_year, espn_s2=None, swid=None):
    """Create the H2H matrix using the scores function"""
    
    # Get records using the scores function
    all_records = get_all_time_h2h_by_scores_fixed(league_id, start_year, end_year, espn_s2, swid)
    
    # Extract team names
    all_teams = set()
    for key in all_records.keys():
        if " vs " in key:
            teams = key.split(" vs ")
            if len(teams) == 2:
                all_teams.add(teams[0])
                all_teams.add(teams[1])
    
    all_teams = sorted(list(all_teams))
    
    # Create matrix
    matrix_data = {}
    for row_team in all_teams:
        matrix_data[row_team] = {}
        for col_team in all_teams:
            if row_team == col_team:
                matrix_data[row_team][col_team] = "-"
            else:
                lookup_key = f"{row_team} vs {col_team}"
                
                if lookup_key in all_records:
                    record = all_records[lookup_key]
                    
                    # CHEAT: Just flip the wins and losses
                    flipped_wins = record['team2_wins']  # Use team2's wins as row team's wins
                    flipped_losses = record['team1_wins']  # Use team1's wins as row team's losses
                    
                    matrix_data[row_team][col_team] = f"{flipped_wins}-{flipped_losses}"
                else:
                    matrix_data[row_team][col_team] = "0-0"
    
    df = pd.DataFrame(matrix_data)
    return df

# Sidebar for navigation
st.sidebar.title("Navigation")
page = st.sidebar.selectbox(
    "Choose a page:",
    ["Team Overview", "Player Analysis", "Matchup Predictor", "Season Stats", "H2H Matrix"]
)

# League configuration in sidebar (for H2H Matrix)
if page == "H2H Matrix":
    st.sidebar.markdown("---")
    st.sidebar.subheader("League Configuration")
    
    start_year = st.sidebar.number_input("Start Year", value=2019, min_value=2000, max_value=2099)
    end_year = st.sidebar.number_input("End Year", value=2025, min_value=2000, max_value=2099)

# Sample data functions for other pages
@st.cache_data
def load_team_data():
    return pd.DataFrame({
        'Player': ['Josh Allen', 'Christian McCaffrey', 'Tyreek Hill', 'Travis Kelce'],
        'Position': ['QB', 'RB', 'WR', 'TE'],
        'Points': [342.5, 289.2, 267.8, 198.3],
        'Games': [17, 14, 16, 15],
        'PPG': [20.1, 20.7, 16.7, 13.2]
    })

@st.cache_data
def load_weekly_scores():
    weeks = list(range(1, 15))
    return pd.DataFrame({
        'Week': weeks,
        'Your_Team': [145, 162, 98, 178, 134, 156, 189, 123, 167, 145, 134, 178, 156, 189],
        'League_Average': [135, 142, 128, 155, 148, 162, 171, 139, 158, 149, 144, 165, 151, 163]
    })

# Main content based on page selection
if page == "Team Overview":
    st.header("Team Overview")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Points", "2,145", "+45 vs avg")
    with col2:
        st.metric("Current Rank", "3rd", "+2 positions")
    with col3:
        st.metric("Wins", "9", "+2 vs expected")
    with col4:
        st.metric("Points Per Game", "154.3", "+12.1 vs avg")
    
    # Weekly performance chart
    weekly_data = load_weekly_scores()
    
    fig = px.line(weekly_data, x='Week', y=['Your_Team', 'League_Average'], 
                  title='Weekly Performance vs League Average',
                  labels={'value': 'Points', 'variable': 'Team'})
    st.plotly_chart(fig, use_container_width=True)
    
    # Team roster performance
    st.subheader("Top Performers")
    team_data = load_team_data()
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Points bar chart
        fig_bar = px.bar(team_data, x='Player', y='Points', 
                        title='Total Points by Player',
                        color='Position')
        st.plotly_chart(fig_bar, use_container_width=True)
    
    with col2:
        # PPG comparison
        fig_ppg = px.scatter(team_data, x='Games', y='PPG', 
                           size='Points', hover_name='Player',
                           title='Points Per Game vs Games Played',
                           color='Position')
        st.plotly_chart(fig_ppg, use_container_width=True)

elif page == "Player Analysis":
    st.header("👤 Player Analysis")
    
    team_data = load_team_data()
    selected_player = st.selectbox("Select a player:", team_data['Player'].tolist())
    
    player_info = team_data[team_data['Player'] == selected_player].iloc[0]
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Position", player_info['Position'])
    with col2:
        st.metric("Total Points", f"{player_info['Points']:.1f}")
    with col3:
        st.metric("PPG", f"{player_info['PPG']:.1f}")
    
    # Player performance trends (sample data)
    weeks = list(range(1, 15))
    performance = [20, 15, 25, 8, 22, 18, 26, 12, 24, 19, 16, 23, 21, 27]
    
    player_df = pd.DataFrame({
        'Week': weeks,
        'Points': performance
    })
    
    fig = px.line(player_df, x='Week', y='Points', 
                  title=f'{selected_player} - Weekly Performance')
    st.plotly_chart(fig, use_container_width=True)

elif page == "Matchup Predictor":
    st.header("🔮 Matchup Predictor")
    
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
                 barmode='group')
    st.plotly_chart(fig, use_container_width=True)

elif page == "Season Stats":
    st.header("📈 Season Statistics")
    
    # League standings table
    standings = pd.DataFrame({
        'Rank': [1, 2, 3, 4, 5],
        'Team': ['Team Alpha', 'Team Beta', 'Your Team', 'Team Gamma', 'Team Delta'],
        'Wins': [11, 10, 9, 8, 7],
        'Losses': [3, 4, 5, 6, 7],
        'Points For': [2190, 2156, 2145, 2089, 2034],
        'Points Against': [1987, 2023, 2067, 2156, 2178]
    })
    
    st.subheader("League Standings")
    st.dataframe(standings, use_container_width=True)
    
    # Points distribution
    st.subheader("Points Distribution")
    fig = px.histogram(standings, x='Points For', nbins=10,
                      title='League Points Distribution')
    st.plotly_chart(fig, use_container_width=True)

elif page == "H2H Matrix":
    st.header("🏆 Head-to-Head Matrix")
    
    # Instructions
    st.info("📖 **How to read**: Row team's record vs Column team. Format: Wins-Losses")
    
    # Automatically generate matrix when page loads
    if 'h2h_matrix' not in st.session_state:
        with st.spinner("Processing league data... This may take a few minutes..."):
            try:
                # Generate the matrix using your functions
                h2h_matrix = create_h2h_matrix(league_id, start_year, end_year, espn_s2, swid)
                
                # Store in session state so we don't have to regenerate
                st.session_state['h2h_matrix'] = h2h_matrix
                st.success("Matrix generated successfully!")
                
            except Exception as e:
                st.error(f"Error generating matrix: {e}")
                st.info("Make sure you have the correct league ID and credentials (if private league)")
    
    # Display matrix if it exists in session state
    if 'h2h_matrix' in st.session_state:
        h2h_matrix = st.session_state['h2h_matrix']
        
        # Full matrix display
        st.subheader("Complete Head-to-Head Matrix")
        
        # Style the matrix for better visibility
        def style_matrix(val):
            if val == "-":
                return 'background-color: #f0f0f0; text-align: center; font-weight: bold'
            else:
                return 'text-align: center; font-weight: bold'
        
        styled_matrix = h2h_matrix.style.applymap(style_matrix)
        st.dataframe(styled_matrix, use_container_width=True)
        
        st.markdown("---")
        
        # Individual team filter
        st.subheader("Individual Team Records")
        
        # Team selector
        teams = list(h2h_matrix.index)
        selected_team = st.selectbox("Select a team to view their record:", teams)
        
        if selected_team:
            # Get the selected team's row
            team_record = h2h_matrix.loc[selected_team]
            
            # Create a dataframe for better display
            record_df = pd.DataFrame({
                'Opponent': team_record.index,
                'Record (W-L)': team_record.values
            })
            
            # Remove the self-matchup row
            record_df = record_df[record_df['Record (W-L)'] != '-']
            
            # Calculate totals
            total_wins = 0
            total_losses = 0
            total_games = 0
            
            for record in record_df['Record (W-L)']:
                if '-' in record and record != '-':
                    try:
                        wins, losses = record.split('-')
                        total_wins += int(wins)
                        total_losses += int(losses)
                        total_games += int(wins) + int(losses)
                    except:
                        continue
            
            # Display metrics
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Wins", total_wins)
            with col2:
                st.metric("Total Losses", total_losses)
            with col3:
                st.metric("Total Games", total_games)
            with col4:
                win_pct = (total_wins / total_games * 100) if total_games > 0 else 0
                st.metric("Win %", f"{win_pct:.1f}%")
            
            # Display the individual records
            st.dataframe(record_df, use_container_width=True, hide_index=True)
            
            # Create a bar chart of wins vs losses for each opponent
            wins_data = []
            losses_data = []
            opponents = []
            
            for _, row in record_df.iterrows():
                opponent = row['Opponent']
                record = row['Record (W-L)']
                if '-' in record:
                    try:
                        wins, losses = record.split('-')
                        wins_data.append(int(wins))
                        losses_data.append(int(losses))
                        opponents.append(opponent)
                    except:
                        continue
            
            if opponents:
                chart_df = pd.DataFrame({
                    'Opponent': opponents + opponents,
                    'Count': wins_data + losses_data,
                    'Type': ['Wins'] * len(opponents) + ['Losses'] * len(opponents)
                })
                
                fig = px.bar(chart_df, x='Opponent', y='Count', color='Type',
                            title=f'{selected_team} - Wins vs Losses by Opponent',
                            barmode='group')
                fig.update_layout(xaxis_tickangle=45)
                st.plotly_chart(fig, use_container_width=True)
    
    else:
        st.info("Matrix generation failed - check your league configuration")

# Sidebar info
st.sidebar.markdown("---")
st.sidebar.info(
    "This app is still in development and many of its modules represent feature concepts and contain dummy data. "
    "Navigate to the H2H Matrix Tab to see initial functionality. Excited to add to this project as the season progresses🫡"
)

# Footer
st.markdown("---")
st.markdown("*Last updated: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "*")