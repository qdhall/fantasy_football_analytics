from datetime import datetime

import streamlit as st

from common import (
    configure_page,
    get_league_history,
    render_footer,
    render_mini_board,
    render_sidebar_info,
    render_storyline_feed,
    render_trivia_carousel,
)
from espn_data import get_credentials, get_current_season_snapshot
from home_stats import compute_award_races, compute_storylines
from league_stats import compute_league_trivia

configure_page("Fantasy Football Analytics")

# A slightly greyer tint than the rest of the app's warm-white pages, so the
# portal reads as its own "landing" space rather than just another stats page.
st.markdown(
    '<style>[data-testid="stAppViewContainer"] { background-color: #ececea; }</style>',
    unsafe_allow_html=True,
)

st.title(":material/sports_football: League Portal")
st.caption("Athletic Enough to Play Fantasy Football")

current_year = datetime.now().year
last_season_year = current_year - 1

owners = get_league_history()

if not owners:
    st.error("Could not load league history. Check your league credentials.")
    st.stop()

# --- League Trivia carousel ---------------------------------------------------
header_col, link_col = st.columns([5, 1.4])
with header_col:
    st.markdown("### :material/casino: League Trivia")
    st.caption("A few of the league's all-time numbers - cycling automatically.")
with link_col:
    st.write("")
    st.page_link("views/league_trivia.py", label="View All Trivia", icon=":material/casino:")

trivia = {k: v for k, v in compute_league_trivia(owners).items() if v}
render_trivia_carousel(trivia)

st.markdown("---")

# --- Season storylines ("word on the street") ---------------------------------
storylines = compute_storylines(owners, last_season_year)
render_storyline_feed(storylines, edition_label=f"{current_year} Season Edition")

st.markdown("---")

# --- Award races & playoff picture ---------------------------------------------
st.markdown("### :material/emoji_events: Award Races & Playoff Picture")

league_id, espn_s2, swid = get_credentials()
if 'current_season_snapshot' not in st.session_state:
    with st.spinner(f"Pulling live {current_year} standings and rosters..."):
        st.session_state['current_season_snapshot'] = get_current_season_snapshot(
            league_id, current_year, espn_s2, swid)
snapshot = st.session_state['current_season_snapshot']

if not snapshot['season_started']:
    st.info(
        f"The {current_year} season hasn't kicked off yet - once Week 1 is in the books, "
        f"this section will show the live Playoff Race, Top Scoring Teams, and MVP Race.",
        icon=":material/campaign:",
    )
else:
    races = compute_award_races(snapshot)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("##### :material/swords: Playoff Race")
        playoff_rows = races['playoff_race'][:races['playoff_team_count'] + 2]
        render_mini_board(
            playoff_rows,
            [("W-L", lambda r: f"{r['wins']}-{r['losses']}" + (f"-{r['ties']}" if r['ties'] else "")),
             ("PF", lambda r: f"{r['points_for']:,.1f}")],
            subtitle_key='team_name', key_prefix='playoff',
        )

    with col2:
        st.markdown("##### :material/bar_chart: Top Scoring Teams")
        render_mini_board(
            races['top_scoring'],
            [("PF", lambda r: f"{r['points_for']:,.1f}")],
            subtitle_key='team_name', key_prefix='scoring',
        )

    with col3:
        st.markdown("##### :material/military_tech: MVP Race")
        render_mini_board(
            races['mvp_race'],
            [("Pts", lambda r: f"{r['points']:,.1f}")],
            name_key='player', subtitle_key='owner', key_prefix='mvp',
        )

render_sidebar_info()
render_footer()
