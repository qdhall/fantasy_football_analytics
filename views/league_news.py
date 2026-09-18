from datetime import datetime

import streamlit as st

from common import PALETTE, configure_page, get_league_history, render_footer, render_sidebar_info, render_storyline_feed
from espn_data import get_credentials, get_recent_activity
from home_stats import compute_storylines

configure_page("League News")

st.header(":material/newspaper: League News")
st.caption("Storylines and roster moves from around the league - all grounded in real data, nothing invented.")

owners = get_league_history()
if not owners:
    st.error("Could not load league history. Check your league credentials.")
    st.stop()

league_id, espn_s2, swid = get_credentials()
current_year = 2026
last_season_year = current_year - 1

# --- League Insider -----------------------------------------------------------
storylines = compute_storylines(owners, last_season_year)
render_storyline_feed(storylines, edition_label=f"{current_year} Season Edition")

st.markdown("---")

# --- Trades & Acquisitions ------------------------------------------------------
st.subheader(":material/swap_horiz: Trades & Acquisitions")

with st.spinner("Loading recent league activity..."):
    recent_activity = get_recent_activity(league_id, current_year, espn_s2, swid, size=25)

ACTION_LABELS = {
    'FA ADDED': 'signed as a free agent',
    'WAIVER ADDED': 'added off waivers',
    'DROPPED': 'dropped',
}

if not recent_activity:
    st.info("No roster moves yet this season.", icon=":material/inbox:")
else:
    for entry in recent_activity:
        when = entry['date'].strftime('%b %-d, %-I:%M %p')
        if entry['kind'] == 'trade':
            players_a = ", ".join(entry['players_a'])
            players_b = ", ".join(entry['players_b'])
            st.markdown(
                f'<div style="padding:10px 0;border-bottom:1px solid {PALETTE["gridline"]};">'
                f'<div style="font-size:0.7rem;color:{PALETTE["ink_muted"]};text-transform:uppercase;'
                f'letter-spacing:0.04em;">Trade &middot; {when}</div>'
                f'<div style="margin-top:3px;color:{PALETTE["ink_primary"]};">'
                f'<b>{entry["team_a"]}</b> traded <b>{players_a}</b> to <b>{entry["team_b"]}</b> '
                f'for <b>{players_b}</b></div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            label = ACTION_LABELS.get(entry['action'], entry['action'].lower())
            bid = f" (${entry['bid_amount']})" if entry['bid_amount'] else ""
            st.markdown(
                f'<div style="padding:8px 0;border-bottom:1px solid {PALETTE["gridline"]};'
                f'font-size:0.92rem;color:{PALETTE["ink_secondary"]};">'
                f'<span style="font-size:0.68rem;color:{PALETTE["ink_muted"]};">{when}</span>&nbsp;&middot;&nbsp;'
                f'<b>{entry["team"]}</b> {label} <b>{entry["player"]}</b>{bid}'
                f'</div>',
                unsafe_allow_html=True,
            )

render_sidebar_info()
render_footer()
