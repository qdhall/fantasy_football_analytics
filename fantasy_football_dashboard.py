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

# League configuration variables
league_id = 23224200
espn_s2 = 'AEAeJkkoTaooG%2BUU5zr3ccb3p7rMEYzp2QPA%2F2Vh2dIO9EMvlN8xNqbuVSXa37QQiUn%2BrY9M5vIBwz94BNbJBNOERwRGpXaqo1013tLZCyBoYzvX1X1C%2BpDRtfXzgEyWSPe1ck1bRcEgF0XEKse%2BNKO7bAAgyz7Q7Z2dggtY16%2F3S5MbftgGoQ08brZh0G4z4FvEPc%2BGzUzDLEYS8lEX8CLIrUYDQkP%2FL0m%2F0k%2F7WxfThtbJ42blZENQsVMhJcUvewcMaOofh49SP3bNhnIXAqzDdt8l4RSbOGycrqu95c9YzibQRwKX%2FsyWpd5WR1%2BkHRQ%3D'
swid = '{1CE75B65-F3E4-4903-A75B-65F3E4E903A7}'

def get_playoff_start_week(year):
    """Get the correct playoff start week based on year"""
    if year in [2019, 2020]:
        return 14  # 13 regular season weeks, playoffs start week 14
    else:
        return 15  # 14 regular season weeks, playoffs start week 15

# Head to head 
def get_all_time_h2h_by_scores_fixed(league_id, start_year, end_year, espn_s2=None, swid=None, record_type='all'):
    
    
    all_time_h2h = {}
    team_names = {}
    
    for year in range(start_year, end_year + 1):
        print(f"Processing {year} season...")
        
        try:
            league = League(league_id, year, espn_s2=espn_s2, swid=swid)
            
            # Get correct playoff start week for this year
            playoff_start_week = get_playoff_start_week(year)
            
            for team in league.teams:
                team_names[team.team_id] = team.team_name
            
            max_week = league.current_week
            processed_games = set()
            
            for week in range(max_week):
                
                actual_week = week + 1
                
                # Filter based on record type
                if record_type == 'regular' and actual_week >= playoff_start_week:
                    continue
                elif record_type == 'playoffs' and actual_week < playoff_start_week:
                    continue
                
                    
                for team in league.teams:
                    if (week < len(team.schedule) and 
                        week < len(team.scores) and 
                        hasattr(team.schedule[week], 'team_id')):
                        
                        opponent = team.schedule[week]
                        team_score = team.scores[week]
                        opponent_score = opponent.scores[week]
                        
                        
                        if team_score is None or opponent_score is None:
                            continue
                        
                        # Avoid double counting
                        game_id = tuple(sorted([team.team_id, opponent.team_id]))
                        full_game_id = (year, week, *game_id)
                        
                        if full_game_id in processed_games:
                            continue
                        processed_games.add(full_game_id)
                        
                        # determine winner
                        if team_score > opponent_score:
                            # Team won
                            winner_id = team.team_id
                            winner_name = team.team_name
                            loser_id = opponent.team_id
                            loser_name = opponent.team_name
                        elif opponent_score > team_score:
                            # Opponent won
                            winner_id = opponent.team_id
                            winner_name = opponent.team_name
                            loser_id = team.team_id
                            loser_name = team.team_name
                        else:
                            continue  
                        
                        # Create consistent key (always smaller ID first for consistency)
                        key = tuple(sorted([team.team_id, opponent.team_id]))
                        
                        if key not in all_time_h2h:
                            all_time_h2h[key] = {team.team_id: 0, opponent.team_id: 0}
                        
                        # Record the win for the team with HIGHER score
                        all_time_h2h[key][winner_id] += 1
        
        except Exception as e:
            print(f"Error processing {year}: {e}")
            st.error(f"Error processing {year}: {e}")
    
    # h2h dict
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

def create_h2h_matrix(league_id, start_year, end_year, espn_s2=None, swid=None, record_type='all'):
    """
    Create the H2H matrix using the scores function
    record_type: 'all', 'regular', 'playoffs'
    """
    
    # Get records using the scores function
    all_records = get_all_time_h2h_by_scores_fixed(league_id, start_year, end_year, espn_s2, swid, record_type)
    
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
                    
                    
                    flipped_wins = record['team2_wins']  
                    flipped_losses = record['team1_wins']  
                    
                    matrix_data[row_team][col_team] = f"{flipped_wins}-{flipped_losses}"
                else:
                    matrix_data[row_team][col_team] = "0-0"
    
    df = pd.DataFrame(matrix_data)
    return df

def calculate_all_time_stats(league_id, start_year, end_year, espn_s2, swid):
    """Calculate all-time statistics for all teams, separating regular season and playoffs"""
    all_time_stats = {}
    
    for year in range(start_year, end_year + 1):
        try:
            league = League(league_id, year, espn_s2=espn_s2, swid=swid)
            
            # Get correct playoff start week for this year
            playoff_start_week = get_playoff_start_week(year)
            
            for team in league.teams:
                # Get owner name
                owner_name = "Unknown Owner"
                if hasattr(team, 'owners') and team.owners:
                    if isinstance(team.owners, list) and len(team.owners) > 0:
                        owner_name = team.owners[0].get('firstName', '') + ' ' + team.owners[0].get('lastName', '')
                    elif isinstance(team.owners, dict):
                        owner_name = team.owners.get('firstName', '') + ' ' + team.owners.get('lastName', '')
                    else:
                        owner_name = str(team.owners[0]) if isinstance(team.owners, list) else str(team.owners)
                
                owner_name = owner_name.strip()
                if owner_name == "" or owner_name == " ":
                    owner_name = f"Team {team.team_id}"
                
                # Initialize owner entry if not exists
                if owner_name not in all_time_stats:
                    all_time_stats[owner_name] = {
                        'regular_season': {
                            'total_points': 0,
                            'wins': 0,
                            'losses': 0,
                            'ties': 0
                        },
                        'playoffs': {
                            'total_points': 0,
                            'wins': 0,
                            'losses': 0,
                            'ties': 0,
                            'appearances': 0
                        },
                        'years_played': 0
                    }
                
                # Calculate regular season and playoff stats
                reg_wins = 0
                reg_losses = 0
                reg_ties = 0
                reg_points = 0
                playoff_wins = 0
                playoff_losses = 0
                playoff_ties = 0
                playoff_points = 0
                
                # Process each week's games
                for week_num in range(len(team.scores)):
                    if week_num < len(team.schedule) and team.scores[week_num] is not None:
                        opponent = team.schedule[week_num]
                        if hasattr(opponent, 'scores') and week_num < len(opponent.scores):
                            team_score = team.scores[week_num]
                            opp_score = opponent.scores[week_num]
                            
                            if opp_score is not None:
                                actual_week = week_num + 1
                                if actual_week < playoff_start_week:
                                    # Regular season
                                    reg_points += team_score
                                    if team_score > opp_score:
                                        reg_wins += 1
                                    elif team_score < opp_score:
                                        reg_losses += 1
                                    else:
                                        reg_ties += 1
                                else:
                                    # Playoffs
                                    playoff_points += team_score
                                    if team_score > opp_score:
                                        playoff_wins += 1
                                    elif team_score < opp_score:
                                        playoff_losses += 1
                                    else:
                                        playoff_ties += 1
                
                # Add to all-time stats
                all_time_stats[owner_name]['regular_season']['wins'] += reg_wins
                all_time_stats[owner_name]['regular_season']['losses'] += reg_losses
                all_time_stats[owner_name]['regular_season']['ties'] += reg_ties
                all_time_stats[owner_name]['regular_season']['total_points'] += reg_points
                
                all_time_stats[owner_name]['playoffs']['wins'] += playoff_wins
                all_time_stats[owner_name]['playoffs']['losses'] += playoff_losses
                all_time_stats[owner_name]['playoffs']['ties'] += playoff_ties
                all_time_stats[owner_name]['playoffs']['total_points'] += playoff_points
                
                # Count playoff appearance if they played any playoff games
                if playoff_wins + playoff_losses + playoff_ties > 0:
                    all_time_stats[owner_name]['playoffs']['appearances'] += 1
                
                all_time_stats[owner_name]['years_played'] += 1
                
        except Exception as e:
            print(f"Error loading year {year}: {e}")
            continue
    
    return all_time_stats

def load_real_teams_data_full(league_id, year, espn_s2, swid):
    """Load complete team data including players"""
    try:
        league = League(league_id, year, espn_s2=espn_s2, swid=swid)
        
        teams_data = {}
        
        for team in league.teams:
            # Get owner name - handle different formats
            owner_name = "Unknown Owner"
            if hasattr(team, 'owners') and team.owners:
                if isinstance(team.owners, list) and len(team.owners) > 0:
                    owner_name = team.owners[0].get('firstName', '') + ' ' + team.owners[0].get('lastName', '')
                elif isinstance(team.owners, dict):
                    owner_name = team.owners.get('firstName', '') + ' ' + team.owners.get('lastName', '')
                else:
                    owner_name = str(team.owners[0]) if isinstance(team.owners, list) else str(team.owners)
            
            owner_name = owner_name.strip()
            if owner_name == "" or owner_name == " ":
                owner_name = f"Team {team.team_id}"
            
            # Collect player data
            players_list = []
            if hasattr(team, 'roster'):
                for player in team.roster:
                    player_data = {
                        'Player': player.name,
                        'Position': player.position,
                        'Points': player.total_points,
                        'Avg Points': player.avg_points,
                        'Pro Team': player.proTeam if hasattr(player, 'proTeam') else 'FA',
                        'Injury Status': player.injuryStatus if hasattr(player, 'injuryStatus') else 'ACTIVE'
                    }
                    players_list.append(player_data)
            
            teams_data[owner_name] = {
                'total_points': team.points_for,
                'rank': team.standing,
                'wins': team.wins,
                'losses': team.losses,
                'ties': team.ties if hasattr(team, 'ties') else 0,
                'team_name': team.team_name,
                'players': pd.DataFrame(players_list)
            }
        
        return teams_data
        
    except Exception as e:
        st.error(f"Error loading team data: {str(e)}")
        return {}

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
    end_year = st.sidebar.number_input("End Year", value=2024, min_value=2000, max_value=2099)

# Main content based on page selection
if page == "Team Overview":
    st.header("Team Overview")
    
    # Load initial data for team selector
    if 'initial_teams_data' not in st.session_state:
        with st.spinner("Loading team data..."):
            # Try to load most recent year for team list
            for year_to_try in [2024, 2023]:
                try:
                    initial_data = load_real_teams_data_full(league_id, year_to_try, espn_s2, swid)
                    if initial_data:
                        st.session_state['initial_teams_data'] = initial_data
                        st.session_state['initial_year'] = year_to_try
                        break
                except:
                    continue
            
            if 'initial_teams_data' not in st.session_state:
                st.error("Could not load team data. Please check your league credentials.")
                st.stop()
    
    initial_teams_data = st.session_state['initial_teams_data']
    
    # Team selector at the top
    owner_options = []
    for owner, data in initial_teams_data.items():
        owner_options.append(f"{owner} - {data['team_name']}")
    
    selected_option = st.selectbox("Select a team:", owner_options)
    selected_owner = selected_option.split(' - ')[0]
    
    # Calculate all-time stats if not cached
    if 'all_time_stats' not in st.session_state:
        with st.spinner("Calculating all-time statistics..."):
            all_time_stats = calculate_all_time_stats(league_id, 2019, 2024, espn_s2, swid)
            st.session_state['all_time_stats'] = all_time_stats
    
    all_time_stats = st.session_state['all_time_stats']
    
    # ALL-TIME STATS SECTION
    st.subheader("📊 All-Time Stats (2019-2024)")
    
    # Add note about regular season weeks
    st.caption("*Regular Season: 13 weeks (2019-2020), 14 weeks (2021-2024)*")
    
    if selected_owner in all_time_stats:
        owner_all_time = all_time_stats[selected_owner]
        
        # Calculate league averages for regular season
        total_owners = len(all_time_stats)
        league_avg_reg_points = sum(s['regular_season']['total_points'] for s in all_time_stats.values()) / total_owners if total_owners > 0 else 0
        league_avg_reg_wins = sum(s['regular_season']['wins'] for s in all_time_stats.values()) / total_owners if total_owners > 0 else 0
        league_avg_reg_losses = sum(s['regular_season']['losses'] for s in all_time_stats.values()) / total_owners if total_owners > 0 else 0
        league_avg_reg_win_pct = (league_avg_reg_wins / (league_avg_reg_wins + league_avg_reg_losses) * 100) if (league_avg_reg_wins + league_avg_reg_losses) > 0 else 0
        
        # REGULAR SEASON STATS
        st.write("**Regular Season**")
        
        # Calculate owner regular season stats
        owner_reg_games = owner_all_time['regular_season']['wins'] + owner_all_time['regular_season']['losses']
        owner_reg_win_pct = (owner_all_time['regular_season']['wins'] / owner_reg_games * 100) if owner_reg_games > 0 else 0
        
        # Differences from league average
        reg_points_diff = owner_all_time['regular_season']['total_points'] - league_avg_reg_points
        reg_points_diff_pct = (reg_points_diff / league_avg_reg_points * 100) if league_avg_reg_points > 0 else 0
        reg_wins_diff = owner_all_time['regular_season']['wins'] - league_avg_reg_wins
        reg_win_pct_diff = owner_reg_win_pct - league_avg_reg_win_pct
        
        # Display regular season metrics
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric(
                "Regular Season Points", 
                f"{owner_all_time['regular_season']['total_points']:.1f}",
                f"{reg_points_diff:+.1f} ({reg_points_diff_pct:+.1f}% vs avg)"
            )
        
        with col2:
            reg_record_str = f"{owner_all_time['regular_season']['wins']}-{owner_all_time['regular_season']['losses']}"
            if owner_all_time['regular_season']['ties'] > 0:
                reg_record_str += f"-{owner_all_time['regular_season']['ties']}"
            st.metric(
                "Regular Season Record", 
                reg_record_str,
                f"{reg_wins_diff:+.0f} wins vs avg"
            )
        
        with col3:
            st.metric(
                "Regular Season Win %", 
                f"{owner_reg_win_pct:.1f}%",
                f"{reg_win_pct_diff:+.1f}% vs avg"
            )
        
        # PLAYOFF STATS
        st.write("**Playoffs**")
        
        # Calculate playoff win percentage
        playoff_games = owner_all_time['playoffs']['wins'] + owner_all_time['playoffs']['losses']
        owner_playoff_win_pct = (owner_all_time['playoffs']['wins'] / playoff_games * 100) if playoff_games > 0 else 0
        
        # Display playoff metrics
        col4, col5, col6 = st.columns(3)
        
        with col4:
            st.metric(
                "Playoff Appearances", 
                f"{owner_all_time['playoffs']['appearances']}"
            )
        
        with col5:
            playoff_record_str = f"{owner_all_time['playoffs']['wins']}-{owner_all_time['playoffs']['losses']}"
            if owner_all_time['playoffs']['ties'] > 0:
                playoff_record_str += f"-{owner_all_time['playoffs']['ties']}"
            st.metric(
                "Playoff Record", 
                playoff_record_str
            )
        
        with col6:
            st.metric(
                "Playoff Win %", 
                f"{owner_playoff_win_pct:.1f}%" if playoff_games > 0 else "N/A"
            )
        
        # Combined total points
        total_all_time_points = owner_all_time['regular_season']['total_points'] + owner_all_time['playoffs']['total_points']
        
        # Years played and total points
        col7, col8 = st.columns(2)
        with col7:
            st.info(f"Years in league: {owner_all_time['years_played']}")
        with col8:
            st.info(f"Total All-Time Points (Reg + Playoffs): {total_all_time_points:.1f}")
    else:
        st.warning(f"No all-time data available for {selected_owner}")
    
    st.markdown("---")
    
    # YEAR SELECTOR 
    available_years = list(range(2019, 2025))  
    selected_year = st.selectbox("Select Year for Individual Stats:", available_years, index=len(available_years)-1)
    
    # Load data for selected year
    cache_key = f'teams_data_{selected_year}'
    if cache_key not in st.session_state:
        with st.spinner(f"Loading {selected_year} data..."):
            try:
                year_data = load_real_teams_data_full(league_id, selected_year, espn_s2, swid)
                if year_data:
                    st.session_state[cache_key] = year_data
                else:
                    st.error(f"No data available for {selected_year}")
                    year_data = {}
            except Exception as e:
                st.error(f"Error loading data for {selected_year}: {e}")
                year_data = {}
    else:
        year_data = st.session_state[cache_key]
    
    # INDIVIDUAL YEAR STATS SECTION
    st.subheader(f"📅 {selected_year} Season Stats")
    
    # Show regular season weeks for selected year
    reg_season_weeks = 13 if selected_year in [2019, 2020] else 14
    st.caption(f"*{selected_year} Regular Season: {reg_season_weeks} weeks*")
    
    if year_data and selected_owner in year_data:
        team_data_dict = year_data[selected_owner]
        
        # Display team info
        st.write(f"**Team Name:** {team_data_dict['team_name']}")
        st.write(f"**Owner:** {selected_owner}")
        
        # Team metrics for selected year
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Points", f"{team_data_dict['total_points']:.1f}")
        with col2:
            st.metric("Current Rank", f"#{team_data_dict['rank']}")
        with col3:
            record = f"{team_data_dict['wins']}-{team_data_dict['losses']}"
            if team_data_dict['ties'] > 0:
                record += f"-{team_data_dict['ties']}"
            st.metric("Record", record)
        with col4:
            win_pct = team_data_dict['wins'] / (team_data_dict['wins'] + team_data_dict['losses']) * 100 if (team_data_dict['wins'] + team_data_dict['losses']) > 0 else 0
            st.metric("Win %", f"{win_pct:.1f}%")
        
        # Display roster if available
        if not team_data_dict['players'].empty:
            st.subheader(f"{selected_year} Roster")
            
            # Sort players by total points
            roster_df = team_data_dict['players'].sort_values('Points', ascending=False)
            
            # Format the dataframe for display
            display_df = roster_df[['Player', 'Position', 'Pro Team', 'Points', 'Avg Points', 'Injury Status']].copy()
            display_df['Points'] = display_df['Points'].round(1)
            display_df['Avg Points'] = display_df['Avg Points'].round(1)
            
            st.dataframe(display_df, use_container_width=True, hide_index=True)
            
            # Position breakdown
            st.subheader(f"Points by Position - {selected_year}")
            position_points = roster_df.groupby('Position')['Points'].sum().sort_values(ascending=False)
            
            fig = px.bar(x=position_points.index, y=position_points.values,
                        labels={'x': 'Position', 'y': 'Total Points'},
                        title=f"Total Points by Position - {team_data_dict['team_name']} ({selected_year})")
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning(f"No data available for {selected_owner} in {selected_year}")

elif page == "Player Analysis":
    st.header("👤 Player Analysis")
    
    
    if 'all_teams_data' not in st.session_state:
        with st.spinner("Loading player data..."):
            for year_to_try in [2024, 2023]:
                try:
                    all_teams_data = load_real_teams_data_full(league_id, year_to_try, espn_s2, swid)
                    
                    if all_teams_data:
                        st.session_state['all_teams_data'] = all_teams_data
                        break
                except:
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
        st.metric("Position", selected_player_data['Position'])
    with col2:
        st.metric("Total Points", f"{selected_player_data['Points']:.1f}")
    with col3:
        st.metric("Avg Points", f"{selected_player_data['Avg Points']:.1f}")
    with col4:
        st.metric("Pro Team", selected_player_data['Pro Team'])
    
    # Additional player info
    col5, col6 = st.columns(2)
    with col5:
        st.metric("Owner", selected_player_data['Owner'])
    with col6:
        st.metric("Injury Status", selected_player_data['Injury Status'])
    
    # Position comparison chart
    st.subheader("Position Comparison")
    
    # Filter players by same position
    same_position_players = all_players_df[all_players_df['Position'] == selected_player_data['Position']]
    
    if len(same_position_players) > 1:
        fig_comparison = px.bar(same_position_players.sort_values('Points', ascending=False), 
                               x='Player', y='Points',
                               title=f'{selected_player_data["Position"]} Rankings by Total Points',
                               color='Points',
                               hover_data=['Owner', 'Avg Points'])
        fig_comparison.update_layout(xaxis_tickangle=45)
        st.plotly_chart(fig_comparison, use_container_width=True)
    
    # League-wide position analysis
    st.subheader("League Position Analysis")
    
    position_stats = all_players_df.groupby('Position').agg({
        'Points': ['mean', 'max', 'min', 'count'],
        'Avg Points': 'mean'
    }).round(2)
    
    position_stats.columns = ['Avg Total Points', 'Max Points', 'Min Points', 'Player Count', 'Avg Per Game']
    position_stats = position_stats.reset_index()
    
    st.dataframe(position_stats, use_container_width=True)

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
    
    # Show regular season weeks info
    st.caption(f"*Regular Season: 13 weeks (2019-2020), 14 weeks (2021-{end_year})*")
    
    # Add toggle for regular season vs playoffs
    col1, col2 = st.columns(2)
    with col1:
        matrix_type = st.radio(
            "Select Records Type:",
            ["Regular Season Only", "Playoffs Only", "All Games", "All Three Views"]
        )
    
    # Generate matrices based on selection
    if matrix_type == "All Three Views":
        # Generate all three matrices
        cache_key_reg = f'h2h_matrix_regular_{start_year}_{end_year}'
        cache_key_playoff = f'h2h_matrix_playoffs_{start_year}_{end_year}'
        cache_key_all = f'h2h_matrix_all_{start_year}_{end_year}'
        
        # Regular season matrix
        if cache_key_reg not in st.session_state:
            with st.spinner("Processing regular season data..."):
                try:
                    h2h_matrix_reg = create_h2h_matrix(league_id, start_year, end_year, espn_s2, swid, record_type='regular')
                    st.session_state[cache_key_reg] = h2h_matrix_reg
                except Exception as e:
                    st.error(f"Error generating regular season matrix: {e}")
        
        # Playoffs matrix
        if cache_key_playoff not in st.session_state:
            with st.spinner("Processing playoffs data..."):
                try:
                    h2h_matrix_playoff = create_h2h_matrix(league_id, start_year, end_year, espn_s2, swid, record_type='playoffs')
                    st.session_state[cache_key_playoff] = h2h_matrix_playoff
                except Exception as e:
                    st.error(f"Error generating playoffs matrix: {e}")
        
        # All games matrix
        if cache_key_all not in st.session_state:
            with st.spinner("Processing all games data..."):
                try:
                    h2h_matrix_all = create_h2h_matrix(league_id, start_year, end_year, espn_s2, swid, record_type='all')
                    st.session_state[cache_key_all] = h2h_matrix_all
                except Exception as e:
                    st.error(f"Error generating full matrix: {e}")
        
        # Display all three matrices
        if cache_key_reg in st.session_state and cache_key_playoff in st.session_state and cache_key_all in st.session_state:
            # First row - Regular Season and Playoffs side by side
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("Regular Season Only")
                h2h_matrix_reg = st.session_state[cache_key_reg]
                
                def style_matrix(val):
                    if val == "-":
                        return 'background-color: #f0f0f0; text-align: center; font-weight: bold'
                    else:
                        return 'text-align: center; font-weight: bold; font-size: 10px'
                
                styled_matrix_reg = h2h_matrix_reg.style.applymap(style_matrix)
                st.dataframe(styled_matrix_reg, use_container_width=True, height=350)
            
            with col2:
                st.subheader("Playoffs Only")
                h2h_matrix_playoff = st.session_state[cache_key_playoff]
                styled_matrix_playoff = h2h_matrix_playoff.style.applymap(style_matrix)
                st.dataframe(styled_matrix_playoff, use_container_width=True, height=350)
            
            # Second row - All Games centered
            st.subheader("All Games Combined")
            h2h_matrix_all = st.session_state[cache_key_all]
            styled_matrix_all = h2h_matrix_all.style.applymap(style_matrix)
            st.dataframe(styled_matrix_all, use_container_width=True, height=350)
    
    else:
        # Single matrix view
        if matrix_type == "Regular Season Only":
            record_type = 'regular'
        elif matrix_type == "Playoffs Only":
            record_type = 'playoffs'
        else:  # All Games
            record_type = 'all'
            
        cache_key = f'h2h_matrix_{record_type}_{start_year}_{end_year}'
        
        if cache_key not in st.session_state:
            with st.spinner(f"Processing {matrix_type.lower()} data... This may take a few minutes..."):
                try:
                    h2h_matrix = create_h2h_matrix(league_id, start_year, end_year, espn_s2, swid, record_type=record_type)
                    st.session_state[cache_key] = h2h_matrix
                    st.success("Matrix generated successfully!")
                except Exception as e:
                    st.error(f"Error generating matrix: {e}")
                    st.info("Make sure you have the correct league ID and credentials (if private league)")
        
        # Display matrix if it exists in session state
        if cache_key in st.session_state:
            h2h_matrix = st.session_state[cache_key]
            
            # Full matrix display
            st.subheader(f"Complete Head-to-Head Matrix - {matrix_type}")
            
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
            st.subheader(f"Individual Team Records - {matrix_type}")
            
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
                                title=f'{selected_team} - Wins vs Losses by Opponent ({matrix_type})',
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