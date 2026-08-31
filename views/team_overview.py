import plotly.express as px
import streamlit as st

from common import PALETTE, configure_page, render_footer, render_owner_banner, render_sidebar_info, theme_plotly
from espn_data import build_owner_season_trend, calculate_all_time_stats, get_credentials, load_real_teams_data_full

configure_page("Team Overview")
league_id, espn_s2, swid = get_credentials()

st.header(":material/bar_chart: Team Overview")
st.caption("All-time and per-season stats for each owner, plus their roster in any given year.")

# Load initial data for the owner selector
if 'initial_teams_data' not in st.session_state:
    with st.spinner("Loading team data..."):
        # Try to load most recent year for the owner list, now including 2026
        for year_to_try in [2026, 2025, 2024]:
            try:
                initial_data = load_real_teams_data_full(league_id, year_to_try, espn_s2, swid)
                if initial_data:
                    st.session_state['initial_teams_data'] = initial_data
                    st.session_state['initial_year'] = year_to_try
                    break
            except Exception:
                continue

        if 'initial_teams_data' not in st.session_state:
            st.error("Could not load team data. Please check your league credentials.")
            st.stop()

initial_teams_data = st.session_state['initial_teams_data']

owner_options = sorted(initial_teams_data.keys())
selected_owner = st.selectbox("Select an owner:", owner_options)
render_owner_banner(selected_owner)

# Calculate all-time stats if not cached - now includes 2026
if 'all_time_stats' not in st.session_state:
    with st.spinner("Calculating all-time statistics..."):
        st.session_state['all_time_stats'] = calculate_all_time_stats(league_id, 2019, 2026, espn_s2, swid)

all_time_stats = st.session_state['all_time_stats']

if 'owner_season_trend' not in st.session_state:
    with st.spinner("Loading year-by-year history..."):
        st.session_state['owner_season_trend'] = build_owner_season_trend(league_id, 2019, 2026, espn_s2, swid)

owner_trend = st.session_state['owner_season_trend'].get(selected_owner, {})
owner_years = sorted(owner_trend.keys())

# ALL-TIME STATS SECTION - the year range and season count are specific to
# whichever owner is selected, not a hardcoded league-wide span
if owner_years:
    st.subheader(f":material/query_stats: All-Time Stats ({owner_years[0]}-{owner_years[-1]})")
    st.caption(f"{len(owner_years)} season{'s' if len(owner_years) != 1 else ''}")
else:
    st.subheader(":material/query_stats: All-Time Stats")

if selected_owner in all_time_stats:
    owner_all_time = all_time_stats[selected_owner]

    # League averages are computed per-GAME, not per-owner-total - owners have
    # played wildly different numbers of seasons, so comparing raw career
    # totals (points, wins) against a flat "average owner" total would make
    # anyone with a short tenure look artificially "below average" and anyone
    # long-tenured look artificially "above average" regardless of how good
    # they actually are. A per-game rate is tenure-neutral - it's the same
    # principle already used for win %, just extended to points too.
    league_total_reg_points = sum(s['regular_season']['total_points'] for s in all_time_stats.values())
    league_total_reg_wins = sum(s['regular_season']['wins'] for s in all_time_stats.values())
    league_total_reg_losses = sum(s['regular_season']['losses'] for s in all_time_stats.values())
    league_total_reg_ties = sum(s['regular_season']['ties'] for s in all_time_stats.values())
    league_total_reg_games = league_total_reg_wins + league_total_reg_losses + league_total_reg_ties
    league_avg_reg_win_pct = (
        league_total_reg_wins / (league_total_reg_wins + league_total_reg_losses) * 100
    ) if (league_total_reg_wins + league_total_reg_losses) > 0 else 0
    league_avg_reg_points_per_game = (league_total_reg_points / league_total_reg_games) if league_total_reg_games > 0 else 0

    league_total_playoff_points = sum(s['playoffs']['total_points'] for s in all_time_stats.values())
    league_total_playoff_wins = sum(s['playoffs']['wins'] for s in all_time_stats.values())
    league_total_playoff_losses = sum(s['playoffs']['losses'] for s in all_time_stats.values())
    league_total_playoff_ties = sum(s['playoffs']['ties'] for s in all_time_stats.values())
    league_total_playoff_games = league_total_playoff_wins + league_total_playoff_losses + league_total_playoff_ties
    league_avg_playoff_points_per_game = (
        league_total_playoff_points / league_total_playoff_games
    ) if league_total_playoff_games > 0 else 0

    # REGULAR SEASON STATS
    st.write("**Regular Season**")

    owner_reg_games = (
        owner_all_time['regular_season']['wins'] + owner_all_time['regular_season']['losses']
        + owner_all_time['regular_season']['ties']
    )
    owner_reg_win_pct = (owner_all_time['regular_season']['wins'] / owner_reg_games * 100) if owner_reg_games > 0 else 0
    owner_reg_wins_per_season = (owner_all_time['regular_season']['wins'] / owner_all_time['years_played']) \
        if owner_all_time['years_played'] > 0 else 0
    owner_reg_points_per_game = (owner_all_time['regular_season']['total_points'] / owner_reg_games) if owner_reg_games > 0 else 0

    reg_win_pct_diff = owner_reg_win_pct - league_avg_reg_win_pct
    reg_points_per_game_diff = owner_reg_points_per_game - league_avg_reg_points_per_game
    reg_points_per_game_diff_pct = (
        reg_points_per_game_diff / league_avg_reg_points_per_game * 100
    ) if league_avg_reg_points_per_game > 0 else 0

    col1, col2, col3 = st.columns(3)

    with col1:
        reg_record_str = f"{owner_all_time['regular_season']['wins']}-{owner_all_time['regular_season']['losses']}"
        if owner_all_time['regular_season']['ties'] > 0:
            reg_record_str += f"-{owner_all_time['regular_season']['ties']}"
        st.metric(
            "Regular Season Record",
            reg_record_str,
            f"{owner_reg_wins_per_season:.1f} wins/season",
            delta_color="off",
            border=True,
        )

    with col2:
        st.metric(
            "Regular Season Win %",
            f"{owner_reg_win_pct:.1f}%",
            f"{reg_win_pct_diff:+.1f}% vs avg",
            border=True,
        )

    with col3:
        st.metric(
            "Regular Season Points",
            f"{owner_all_time['regular_season']['total_points']:,.1f}",
            f"{reg_points_per_game_diff:+,.1f} pts/game vs avg ({reg_points_per_game_diff_pct:+.1f}%)",
            border=True,
        )

    # PLAYOFF STATS
    playoff_games = (
        owner_all_time['playoffs']['wins'] + owner_all_time['playoffs']['losses'] + owner_all_time['playoffs']['ties']
    )
    owner_playoff_win_pct = (owner_all_time['playoffs']['wins'] / playoff_games * 100) if playoff_games > 0 else 0
    owner_playoff_points_per_game = (owner_all_time['playoffs']['total_points'] / playoff_games) if playoff_games > 0 else 0
    playoff_points_per_game_diff = owner_playoff_points_per_game - league_avg_playoff_points_per_game

    st.write(f"**Playoffs** — {owner_all_time['playoffs']['appearances']} appearance"
             f"{'s' if owner_all_time['playoffs']['appearances'] != 1 else ''}")

    col4, col5, col6 = st.columns(3)

    with col4:
        playoff_record_str = f"{owner_all_time['playoffs']['wins']}-{owner_all_time['playoffs']['losses']}"
        if owner_all_time['playoffs']['ties'] > 0:
            playoff_record_str += f"-{owner_all_time['playoffs']['ties']}"
        st.metric("Playoff Record", playoff_record_str, border=True)

    with col5:
        st.metric(
            "Playoff Win %",
            f"{owner_playoff_win_pct:.1f}%" if playoff_games > 0 else "N/A",
            border=True,
        )

    with col6:
        st.metric(
            "Playoff Points",
            f"{owner_all_time['playoffs']['total_points']:,.1f}",
            f"{playoff_points_per_game_diff:+,.1f} pts/game vs avg" if playoff_games > 0 else None,
            border=True,
        )
else:
    st.warning(f"No all-time data available for {selected_owner}")

st.markdown("---")

# YEAR-OVER-YEAR TREND
st.subheader(":material/timeline: Year-Over-Year Trend")

if owner_years:
    metric_choice = st.segmented_control(
        "Metric:", ["Final Standing", "Wins", "Points"], default="Final Standing",
    )
    metric_choice = metric_choice or "Final Standing"
    metric_key = {"Final Standing": "standing", "Wins": "wins", "Points": "points"}[metric_choice]

    trend_x = owner_years
    trend_y = [owner_trend[y][metric_key] for y in owner_years]

    fig = px.line(
        x=trend_x, y=trend_y, markers=True,
        labels={'x': 'Season', 'y': metric_choice},
        title=f"{selected_owner} — {metric_choice} by Season",
        color_discrete_sequence=[PALETTE['categorical'][0]],
    )
    fig.update_xaxes(tickmode='array', tickvals=trend_x)
    if metric_key == 'standing':
        # Lower standing is better - flip the axis so 1st place sits on top
        fig.update_yaxes(autorange='reversed', dtick=1)
    st.plotly_chart(theme_plotly(fig), use_container_width=True)
else:
    st.info(f"No season history available for {selected_owner}.", icon=":material/timeline:")

st.markdown("---")

# YEAR SELECTOR - Now includes 2026
available_years = list(range(2019, 2027))
selected_year = st.selectbox("Select Year for Individual Stats:", available_years, index=len(available_years) - 1)

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
st.subheader(f":material/calendar_month: {selected_year} Season Stats")

if year_data and selected_owner in year_data:
    team_data_dict = year_data[selected_owner]

    # Display team info
    st.write(f"**Team Name:** {team_data_dict['team_name']}")
    st.write(f"**Owner:** {selected_owner}")

    # Team metrics for selected year
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Points", f"{team_data_dict['total_points']:,.2f}", border=True)
    with col2:
        st.metric("Current Rank", f"#{team_data_dict['rank']}", border=True)
    with col3:
        record = f"{team_data_dict['wins']}-{team_data_dict['losses']}"
        if team_data_dict['ties'] > 0:
            record += f"-{team_data_dict['ties']}"
        st.metric("Record", record, border=True)
    with col4:
        win_pct = team_data_dict['wins'] / (team_data_dict['wins'] + team_data_dict['losses']) * 100 if (team_data_dict['wins'] + team_data_dict['losses']) > 0 else 0
        st.metric("Win %", f"{win_pct:.1f}%", border=True)

    # Display roster if available
    if not team_data_dict['players'].empty:
        st.subheader(f"{selected_year} Roster")

        # Sort players by total points
        roster_df = team_data_dict['players'].sort_values('Points', ascending=False)

        # Format the dataframe for display
        display_df = roster_df[['Player', 'Position', 'Pro Team', 'Points', 'Avg Points']].copy()
        display_df['Points'] = display_df['Points'].round(1)
        display_df['Avg Points'] = display_df['Avg Points'].round(1)
        display_df = display_df.reset_index(drop=True)

        def _zebra_stripe(row):
            color = PALETTE['surface'] if row.name % 2 == 0 else 'transparent'
            return [f'background-color: {color}'] * len(row)

        styled_roster = display_df.style.apply(_zebra_stripe, axis=1).format({'Points': '{:,.1f}', 'Avg Points': '{:,.1f}'})
        st.dataframe(styled_roster, width='stretch', hide_index=True)
else:
    st.warning(f"No data available for {selected_owner} in {selected_year}")

render_sidebar_info()
render_footer()
