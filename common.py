"""Shared page chrome: page config, theme/palette, CSS, league-history loading, and
Plotly styling used by every page."""

import textwrap
from datetime import datetime

import streamlit as st

from db import ensure_synced
from db import get_front_office_history as _db_get_front_office_history
from db import get_league_history as _db_get_league_history
from espn_data import get_credentials

# Validated light-mode palette (see the dataviz skill's reference palette) - the same
# eight categorical hues and surfaces used across every chart and card in the app,
# matching the light theme set in .streamlit/config.toml.
PALETTE = {
    "surface": "#fcfcfb",
    "page": "#f9f9f7",
    "ink_primary": "#0b0b0b",
    "ink_secondary": "#52514e",
    "ink_muted": "#898781",
    "gridline": "#e1e0d9",
    "axis": "#c3c2b7",
    "categorical": [
        "#2a78d6",  # blue
        "#eb6834",  # orange
        "#1baf7a",  # aqua
        "#eda100",  # yellow/gold
        "#e87ba4",  # magenta
        "#008300",  # green
        "#4a3aa7",  # violet
        "#e34948",  # red
    ],
    "sequential": ["#0d366b", "#104281", "#184f95", "#1c5cab", "#256abf", "#2a78d6", "#3987e5"],
    "status": {
        "good": "#0ca30c",
        "warning": "#fab219",
        "serious": "#ec835a",
        "critical": "#d03b3b",
    },
}

RANK_ACCENT = {
    1: "#c98500",  # gold
    2: "#8a8f98",  # silver
    3: "#a1662f",  # bronze
}


def get_league_history(start_year=2019, end_year=2026):
    """Load (and cache in session_state) the full per-owner league history used by
    the All-Time Rankings, League Records, Wall of Shame, and League Trivia pages
    (and most others) - a fast Postgres read instead of a live ESPN walk, per
    db.get_league_history."""
    if 'league_history' not in st.session_state:
        league_id, espn_s2, swid = get_credentials()
        ensure_synced(league_id, end_year, espn_s2, swid)
        st.session_state['league_history'] = _db_get_league_history(league_id, start_year, end_year)
    return st.session_state['league_history']


def get_front_office_history(start_year=2019, end_year=2026):
    """Load (and cache in session_state) the (gm_history, coach_history,
    draft_log, luck_history) tuple used by Front Office, Luck Index, League
    Trivia, and Team Killers - a fast Postgres read instead of the ~50
    live weekly box-score calls per season db.get_front_office_history
    replaces (the heaviest fetch in the app - what used to take "a few
    minutes" on a fresh session)."""
    if 'front_office_history' not in st.session_state:
        league_id, espn_s2, swid = get_credentials()
        ensure_synced(league_id, end_year, espn_s2, swid)
        st.session_state['front_office_history'] = _db_get_front_office_history(league_id, start_year, end_year)
    return st.session_state['front_office_history']


def configure_page(page_title, page_icon="🏈"):
    st.set_page_config(
        page_title=page_title,
        page_icon=page_icon,
        layout="wide",
        initial_sidebar_state="auto",
    )
    inject_custom_css()


def inject_custom_css():
    st.markdown(
        f"""
        <style>
        /* Record cards (League Records / Wall of Shame / Trivia) */
        div[class*="st-key-card-"] {{
            transition: transform 0.15s ease, box-shadow 0.15s ease;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.10);
        }}
        div[class*="st-key-card-"]:hover {{
            transform: translateY(-2px);
            box-shadow: 0 6px 16px rgba(0, 0, 0, 0.14);
        }}
        div[class*="st-key-card-records-"] {{ border-top: 3px solid {PALETTE['status']['good']} !important; }}
        div[class*="st-key-card-shame-"] {{ border-top: 3px solid {PALETTE['status']['critical']} !important; }}
        div[class*="st-key-card-trivia-"] {{ border-top: 3px solid {PALETTE['categorical'][6]} !important; }}

        /* render_mini_board's column widths were tuned for the Home page's
           3-up award-race layout - with just one stat column and the full
           page width to stretch across (no wrapping st.columns), the name
           column balloons and the single right-aligned value ends up stranded
           far to the right. Capping the board's own width keeps it compact
           regardless of how much of the page it's placed in. */
        div[class*="st-key-mini-"] {{
            max-width: 560px;
        }}

        /* Rankings leaderboard - deliberately grid-free: no cell borders anywhere,
           just whitespace, alternating row tint, and a hairline under the header. */
        .rankings-wrap {{
            overflow-x: auto;
        }}
        .rankings-header, .rankings-row {{
            display: grid;
            grid-template-columns: 46px 34px 1.4fr 0.7fr 0.55fr 0.55fr 0.75fr 0.55fr 0.9fr 0.9fr 0.8fr 0.9fr 0.9fr 0.9fr 0.7fr;
            align-items: center;
            column-gap: 14px;
            padding: 10px 16px;
            min-width: 1280px;
        }}
        .rankings-header {{
            text-transform: uppercase;
            letter-spacing: 0.05em;
            font-size: 0.68rem;
            color: {PALETTE['ink_muted']};
            border-bottom: 1px solid {PALETTE['axis']};
            padding-bottom: 10px;
        }}
        .rankings-body .rankings-row:nth-child(odd) {{
            background-color: {PALETTE['surface']};
            border-radius: 10px;
        }}
        .rankings-row {{
            transition: background-color 0.1s ease;
        }}
        .rankings-row:hover {{
            background-color: {PALETTE['categorical'][0]}14 !important;
            border-radius: 10px;
        }}
        .rankings-col-num {{
            text-align: right;
            font-variant-numeric: tabular-nums;
            color: {PALETTE['ink_secondary']};
            font-size: 0.88rem;
        }}
        .rank-badge {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 26px;
            height: 26px;
            border-radius: 50%;
            font-weight: 700;
            font-size: 0.75rem;
        }}
        .owner-avatar {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 30px;
            height: 30px;
            border-radius: 50%;
            font-weight: 700;
            font-size: 0.72rem;
            color: white;
        }}
        .owner-name {{
            font-weight: 700;
            font-size: 0.95rem;
            color: {PALETTE['ink_primary']};
        }}
        .score-pill {{
            font-weight: 700;
            font-variant-numeric: tabular-nums;
            text-align: right;
        }}

        /* Home page season-storylines section - a comic-book splash page, not
           another row/column table: a skewed logo banner, halftone-textured
           panels with a hard offset shadow and a slight alternating tilt, and
           burst-badge tags. One fixed comic color scheme throughout (not a
           different hue per tag) - the whole point is that it reads as a comic
           cover, not a legend. */
        .comic-masthead {{
            text-align: center;
            margin-bottom: 22px;
        }}
        .comic-logo {{
            display: inline-block;
            font-family: Impact, Haettenschweiler, 'Arial Narrow Bold', sans-serif;
            font-size: 2.1rem;
            letter-spacing: 0.02em;
            color: #fff9e8;
            background: linear-gradient(100deg, #e34948, #eb6834);
            padding: 6px 30px;
            transform: skew(-8deg);
            border: 4px solid #111;
            border-radius: 4px;
            box-shadow: 6px 6px 0 #111;
            text-shadow: 2px 2px 0 #111;
        }}
        .comic-tagline {{
            margin-top: 12px;
            font-family: Impact, Haettenschweiler, 'Arial Narrow Bold', sans-serif;
            font-size: 0.8rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: {PALETTE['ink_secondary']};
        }}
        .news-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 22px;
            padding: 4px 6px 14px;
        }}
        .news-card {{
            background-color: #fffdf5;
            background-image: radial-gradient(circle, rgba(17,17,17,0.08) 1px, transparent 1.4px);
            background-size: 8px 8px;
            border: 3px solid #111;
            border-radius: 4px;
            padding: 18px 20px;
            box-shadow: 5px 5px 0 #111;
            transform: rotate(-0.6deg);
            transition: transform 0.15s ease, box-shadow 0.15s ease;
        }}
        .news-card:nth-child(even) {{
            transform: rotate(0.6deg);
        }}
        .news-card:hover {{
            transform: rotate(0deg) scale(1.02);
            box-shadow: 7px 7px 0 #111;
        }}
        .news-card.news-lead {{
            grid-column: span 2;
            padding: 22px 24px;
        }}
        .comic-tag-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 7px;
            margin-bottom: 12px;
        }}
        .comic-tag {{
            display: inline-block;
            font-family: Impact, Haettenschweiler, 'Arial Narrow Bold', sans-serif;
            font-size: 0.72rem;
            letter-spacing: 0.02em;
            color: #111;
            background-color: #ffcf3f;
            border: 2px solid #111;
            border-radius: 3px;
            padding: 2px 10px;
            transform: rotate(-2deg);
        }}
        .comic-tag:nth-child(even) {{
            transform: rotate(2deg);
        }}
        .news-headline {{
            font-family: Impact, Haettenschweiler, 'Arial Narrow Bold', sans-serif;
            font-size: 1.1rem;
            letter-spacing: 0.01em;
            line-height: 1.32;
            color: #111;
        }}
        .news-lead .news-headline {{
            font-size: 1.4rem;
        }}

        /* League News page's Rumor Mill - a plain Twitter/X-style feed (an
           avatar, a bold handle, a line of "tweet" text), deliberately
           understated next to the comic-book League Insider section above
           it on the same page, since this content is gossip-toned but still
           grounded in real facts, not a second splash page. */
        .rumor-feed {{
            display: flex;
            flex-direction: column;
        }}
        .rumor-card {{
            display: flex;
            gap: 12px;
            padding: 14px 4px;
            border-bottom: 1px solid {PALETTE['gridline']};
        }}
        .rumor-card:last-child {{
            border-bottom: none;
        }}

        </style>
        """,
        unsafe_allow_html=True,
    )


def inject_nav_css():
    """Custom sidebar nav CSS (see render_custom_nav) - a gold gradient + bevel
    + shimmer icon per page, in place of the flat Material icons Streamlit's
    built-in nav is limited to.

    Deliberately kept OUT of inject_custom_css/configure_page and instead
    called directly from fantasy_football_dashboard.py, before
    render_custom_nav() runs. inject_custom_css() only re-executes once the
    destination page's own script runs (inside nav.run(), which happens
    AFTER render_custom_nav() re-renders the sidebar for the new active
    page) - Streamlit tears down and rebuilds the sidebar's DOM nodes on
    every navigation (see render_nav_auto_collapse), so for that one render
    the freshly-rebuilt nav briefly had no custom CSS at all, and browsers
    fall back to Streamlit's native single-line/ellipsis nav-link styling -
    visible as a flash of an unwrapped, clipped label ("Scoreboard & Matchup
    Predict...") sitting next to the newly-highlighted destination link.
    Injecting this before render_custom_nav() instead guarantees the CSS is
    already present in the DOM by the time the nav re-renders, every time."""
    st.markdown(
        """
        <style>
        /* The icon markdown and the page_link are two separate child elements,
           each wrapped in its own stElementContainer, both sitting inside one
           shared stVerticalBlock - three box layers between the st-key-navlink-
           div and the actual visible content. Flexing just one of those levels
           wasn't enough (each stElementContainer still carries its own
           full-width block sizing), so instead every wrapper layer is flattened
           with display:contents - it keeps the element in the DOM but removes
           its own box entirely, so its children splice directly into the
           st-key-navlink- div's flex row regardless of whatever width/display
           Streamlit set on the wrapper itself. */
        div[class*="st-key-navlink-"] {
            display: flex !important;
            flex-direction: row !important;
            align-items: flex-start;
            gap: 10px;
            margin-bottom: 2px;
        }
        div[class*="st-key-navlink-"] div[data-testid="stVerticalBlock"],
        div[class*="st-key-navlink-"] div[data-testid="stElementContainer"] {
            display: contents;
        }
        div[class*="st-key-navlink-"] [data-testid="stPageLink"] {
            flex: 1;
            min-width: 0;
        }
        /* The old active page and the newly-hovered destination can both show
           a highlighted background for a brief window while a click is still
           being routed (the old page hasn't unmounted yet, the new one hasn't
           finished its script run) - a transition here turns that overlap
           into a soft crossfade instead of a jarring double-flash. */
        div[class*="st-key-navlink-"] [data-testid="stPageLink"],
        div[class*="st-key-navlink-"] [data-testid="stPageLink"] > div,
        div[class*="st-key-navlink-"] a {
            transition: background-color 0.15s ease, box-shadow 0.15s ease;
        }
        /* A long title (e.g. "Scoreboard & Matchup Predictor") was getting
           hard-clipped mid-word by Streamlit's own single-line nav-link
           styling instead of wrapping - this lets it wrap to a second line
           like a normal label instead of losing the tail end. */
        div[class*="st-key-navlink-"] [data-testid="stPageLink"] p {
            white-space: normal !important;
            overflow-wrap: break-word;
            line-height: 1.25;
        }
        div[class*="st-key-navlink-"] .nav-icon-slot {
            margin-top: 3px;
        }
        /* Coming-soon pages (waiting on the season to start): grey icon, dimmed
           label, disabled cursor - disabled=True on st.page_link already blocks
           the actual navigation, this is just making that state visible. */
        div[class*="st-key-navlink-player-analysis"] [data-testid="stPageLink"],
        div[class*="st-key-navlink-matchup-predictor"] [data-testid="stPageLink"],
        div[class*="st-key-navlink-season-stats"] [data-testid="stPageLink"] {
            opacity: 0.5;
        }
        .nav-icon-dim svg {
            filter: grayscale(1) opacity(0.55) !important;
        }
        .nav-icon-dim .nav-shimmer-band {
            animation: none !important;
        }
        .nav-icon-slot {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 22px;
            height: 22px;
            flex-shrink: 0;
        }
        .nav-icon-slot svg {
            width: 20px;
            height: 20px;
            filter:
                drop-shadow(-0.5px -0.5px 0.3px rgba(255, 255, 255, 0.7))
                drop-shadow(1px 1.2px 0.8px rgba(30, 18, 8, 0.5));
        }
        .nav-shimmer-band {
            transform-box: fill-box;
            transform-origin: 0 0;
        }
        @media (prefers-reduced-motion: no-preference) {
            .nav-shimmer-band {
                animation: navShimmer 3.2s ease-in-out infinite;
            }
        }
        @keyframes navShimmer {
            0%   { transform: translateX(0); }
            45%  { transform: translateX(96px); }
            100% { transform: translateX(96px); }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# Page title -> nav icon shape id, one hand-drawn glyph per real page (see
# render_nav_icon_defs). Home has no entry - it keeps its blank icon slot.
NAV_ICON_SHAPES = {
    "League News": "Newspaper",
    "Rumor Mill": "Megaphone",
    "All-Time Rankings": "Crown",
    "League Records": "Trophy",
    "Wall of Shame": "Skull",
    "League Trivia": "Dice",
    "Front Office": "Briefcase",
    "Team Overview": "Bars",
    "Luck Index": "Clover",
    "Team Killers": "Ban",
    "Player Analysis": "Person",
    "Scoreboard & Matchup Predictor": "Target",
    "Season Stats": "Trend",
    "H2H Matrix": "Swords",
    "Matchup History": "Clock",
}

# Pages that need real in-season data (or just haven't been built yet) to be
# worth visiting - disabled in the nav (with a "Coming Soon" suffix) until
# they're ready.
COMING_SOON_PAGES = {"Player Analysis", "Season Stats"}


def render_nav_icon_defs():
    """Hidden SVG defs (gold gradients + one shape/mask pair per nav icon) that
    render_custom_nav's <use>/mask references resolve against - id references
    work regardless of where in the DOM the defs physically sit, so this can be
    called once from the router before the nav itself is rendered. A <mask> is
    used instead of a <clipPath> to silhouette each icon: a mask uses the actual
    rendered luminance of its content, so stroke-only details (like the trophy's
    handles) show up correctly, where a clipPath's raw fill-geometry approach can
    resolve a stroke-only child to zero area and make it (or the whole icon)
    vanish. Wrapped in textwrap.dedent + strip() before reaching st.markdown -
    Markdown treats 4+ leading spaces on a line as a literal indented code
    block, which is exactly what happened here before the dedent: the whole
    defs block rendered as visible text instead of being parsed as real SVG,
    so every mask/gradient reference below resolved to nothing and every icon
    fell back to a plain unmasked square."""
    st.markdown(
        textwrap.dedent(
            """
            <svg width="0" height="0" style="position: absolute" aria-hidden="true">
              <defs>
            <linearGradient id="navGoldBase" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stop-color="#8a5a17" />
              <stop offset="42%" stop-color="#f6e7b8" />
              <stop offset="58%" stop-color="#d4a13d" />
              <stop offset="100%" stop-color="#8a5a17" />
            </linearGradient>
            <linearGradient id="navShimmerBand" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stop-color="#fff" stop-opacity="0" />
              <stop offset="50%" stop-color="#fff" stop-opacity="0.85" />
              <stop offset="100%" stop-color="#fff" stop-opacity="0" />
            </linearGradient>

            <g id="navShapeCrown">
              <path d="M8,34 12,10 18,22 24,8 30,22 36,10 40,34 Z" />
              <circle cx="12" cy="10" r="2.4" />
              <circle cx="24" cy="8" r="2.4" />
              <circle cx="36" cy="10" r="2.4" />
              <rect x="8" y="34" width="32" height="6" rx="1" />
            </g>
            <g id="navShapeTrophy">
              <path d="M14,6 h20 v11 a10,10 0 0 1 -20,0 V6 z" />
              <path d="M14,9 c-5,0 -8,3.2 -8,7.4 s3,7.6 7.6,7.8" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" />
              <path d="M34,9 c5,0 8,3.2 8,7.4 s-3,7.6 -7.6,7.8" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" />
              <rect x="21" y="27" width="6" height="8" />
              <rect x="15" y="35" width="18" height="4" rx="1" />
              <rect x="11" y="39" width="26" height="4" rx="1" />
            </g>
            <g id="navShapeDice">
              <rect x="8" y="8" width="32" height="32" rx="7" />
              <circle cx="17" cy="17" r="2.6" fill="#180f08" />
              <circle cx="31" cy="17" r="2.6" fill="#180f08" />
              <circle cx="24" cy="24" r="2.6" fill="#180f08" />
              <circle cx="17" cy="31" r="2.6" fill="#180f08" />
              <circle cx="31" cy="31" r="2.6" fill="#180f08" />
            </g>
            <g id="navShapeBriefcase">
              <path d="M18,10 h12 a3,3 0 0 1 3,3 v5 h-18 v-5 a3,3 0 0 1 3,-3 z" fill="none" stroke="currentColor" stroke-width="3" />
              <rect x="6" y="18" width="36" height="22" rx="3" />
              <rect x="6" y="27" width="36" height="4" fill="#180f08" />
            </g>
            <g id="navShapeBars">
              <rect x="8" y="26" width="8" height="16" rx="1.5" />
              <rect x="20" y="16" width="8" height="26" rx="1.5" />
              <rect x="32" y="8" width="8" height="34" rx="1.5" />
            </g>
            <g id="navShapePerson">
              <circle cx="24" cy="14" r="8" />
              <path d="M8,42 c0,-10 7,-16 16,-16 s16,6 16,16 z" />
            </g>
            <g id="navShapeTarget">
              <circle cx="24" cy="24" r="18" fill="none" stroke="currentColor" stroke-width="4" />
              <circle cx="24" cy="24" r="10" fill="none" stroke="currentColor" stroke-width="4" />
              <circle cx="24" cy="24" r="3" />
            </g>
            <g id="navShapeTrend">
              <path d="M6,34 16,22 24,28 40,10" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" />
              <path d="M40,10 h-9" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round" />
              <path d="M40,10 v9" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round" />
            </g>
            <g id="navShapeSwords">
              <path d="M10,10 L34,34" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round" />
              <path d="M38,10 L14,34" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round" />
              <path d="M8,8 l6,0 0,6" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />
              <path d="M40,8 l-6,0 0,6" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />
              <circle cx="34" cy="34" r="3" />
              <circle cx="14" cy="34" r="3" />
            </g>
            <g id="navShapeClover">
              <circle cx="18" cy="18" r="10" />
              <circle cx="30" cy="18" r="10" />
              <circle cx="18" cy="30" r="10" />
              <circle cx="30" cy="30" r="10" />
              <rect x="22" y="30" width="4" height="14" rx="2" />
            </g>
            <g id="navShapeBan">
              <circle cx="24" cy="24" r="18" fill="none" stroke="currentColor" stroke-width="4" />
              <line x1="12" y1="36" x2="36" y2="12" stroke="currentColor" stroke-width="4" stroke-linecap="round" />
            </g>
            <g id="navShapeSkull">
              <path d="M24,6 C15,6 9,13 9,21 c0,5 2,9 4,11 v5 a2,2 0 0 0 2,2 h18 a2,2 0 0 0 2,-2 v-5 c2,-2 4,-6 4,-11 C39,13 33,6 24,6 Z" />
              <circle cx="17.5" cy="21" r="3.8" fill="#180f08" />
              <circle cx="30.5" cy="21" r="3.8" fill="#180f08" />
              <path d="M22,29 h4 l-2,4 z" fill="#180f08" />
            </g>
            <g id="navShapeClock">
              <circle cx="24" cy="24" r="18" fill="none" stroke="currentColor" stroke-width="4" />
              <path d="M24,13 v11 l8,6" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" />
            </g>
            <g id="navShapeNewspaper">
              <path d="M8,10 h26 l6,6 v22 a2,2 0 0 1 -2,2 h-30 a2,2 0 0 1 -2,-2 v-26 a2,2 0 0 1 2,-2 z" />
              <path d="M34,10 v6 h6" fill="none" stroke="#180f08" stroke-width="2" stroke-linejoin="round" />
              <rect x="13" y="19" width="16" height="3" fill="#180f08" />
              <rect x="13" y="25" width="22" height="3" fill="#180f08" />
              <rect x="13" y="31" width="22" height="3" fill="#180f08" />
            </g>
            <g id="navShapeMegaphone">
              <path d="M8,18 h6 l18,-11 v34 l-18,-11 h-6 a3,3 0 0 1 -3,-3 v-6 a3,3 0 0 1 3,-3 z" />
              <rect x="10" y="29" width="6" height="11" rx="2" transform="rotate(14 10 29)" />
              <path d="M36,15 a11,11 0 0 1 0,18" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" />
              <path d="M41,10 a17,17 0 0 1 0,28" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" opacity="0.65" />
            </g>

            <mask id="navMaskCrown" maskUnits="userSpaceOnUse" x="0" y="0" width="48" height="48">
              <g fill="#fff" stroke="#fff" style="color: #fff"><use href="#navShapeCrown" /></g>
            </mask>
            <mask id="navMaskTrophy" maskUnits="userSpaceOnUse" x="0" y="0" width="48" height="48">
              <g fill="#fff" stroke="#fff" style="color: #fff"><use href="#navShapeTrophy" /></g>
            </mask>
            <mask id="navMaskDice" maskUnits="userSpaceOnUse" x="0" y="0" width="48" height="48">
              <g fill="#fff" stroke="#fff" style="color: #fff"><use href="#navShapeDice" /></g>
            </mask>
            <mask id="navMaskBriefcase" maskUnits="userSpaceOnUse" x="0" y="0" width="48" height="48">
              <g fill="#fff" stroke="#fff" style="color: #fff"><use href="#navShapeBriefcase" /></g>
            </mask>
            <mask id="navMaskBars" maskUnits="userSpaceOnUse" x="0" y="0" width="48" height="48">
              <g fill="#fff" stroke="#fff" style="color: #fff"><use href="#navShapeBars" /></g>
            </mask>
            <mask id="navMaskPerson" maskUnits="userSpaceOnUse" x="0" y="0" width="48" height="48">
              <g fill="#fff" stroke="#fff" style="color: #fff"><use href="#navShapePerson" /></g>
            </mask>
            <mask id="navMaskTarget" maskUnits="userSpaceOnUse" x="0" y="0" width="48" height="48">
              <g fill="#fff" stroke="#fff" style="color: #fff"><use href="#navShapeTarget" /></g>
            </mask>
            <mask id="navMaskTrend" maskUnits="userSpaceOnUse" x="0" y="0" width="48" height="48">
              <g fill="#fff" stroke="#fff" style="color: #fff"><use href="#navShapeTrend" /></g>
            </mask>
            <mask id="navMaskSwords" maskUnits="userSpaceOnUse" x="0" y="0" width="48" height="48">
              <g fill="#fff" stroke="#fff" style="color: #fff"><use href="#navShapeSwords" /></g>
            </mask>
            <mask id="navMaskClover" maskUnits="userSpaceOnUse" x="0" y="0" width="48" height="48">
              <g fill="#fff" stroke="#fff" style="color: #fff"><use href="#navShapeClover" /></g>
            </mask>
            <mask id="navMaskBan" maskUnits="userSpaceOnUse" x="0" y="0" width="48" height="48">
              <g fill="#fff" stroke="#fff" style="color: #fff"><use href="#navShapeBan" /></g>
            </mask>
            <mask id="navMaskSkull" maskUnits="userSpaceOnUse" x="0" y="0" width="48" height="48">
              <g fill="#fff" stroke="#fff" style="color: #fff"><use href="#navShapeSkull" /></g>
            </mask>
            <mask id="navMaskClock" maskUnits="userSpaceOnUse" x="0" y="0" width="48" height="48">
              <g fill="#fff" stroke="#fff" style="color: #fff"><use href="#navShapeClock" /></g>
            </mask>
            <mask id="navMaskNewspaper" maskUnits="userSpaceOnUse" x="0" y="0" width="48" height="48">
              <g fill="#fff" stroke="#fff" style="color: #fff"><use href="#navShapeNewspaper" /></g>
            </mask>
            <mask id="navMaskMegaphone" maskUnits="userSpaceOnUse" x="0" y="0" width="48" height="48">
              <g fill="#fff" stroke="#fff" style="color: #fff"><use href="#navShapeMegaphone" /></g>
            </mask>
              </defs>
            </svg>
            """
        ).strip(),
        unsafe_allow_html=True,
    )


def _nav_icon_html(shape_name, delay_s, dim=False):
    # render_custom_nav() paints this markup on every page navigation BEFORE
    # the destination page's own configure_page() call re-injects the
    # <style> block that sizes .nav-icon-slot/.nav-icon-slot svg - relying on
    # that external stylesheet alone left a brief window where the browser
    # renders the raw, unstyled SVG at its default (much larger) intrinsic
    # size, which is the "icons glitch huge" flash on click. Setting the size
    # inline here means it's correct on the very first paint regardless of
    # when/whether the stylesheet has loaded yet; the CSS classes stay for
    # the drop-shadow/dim/shimmer effects only.
    slot_class = "nav-icon-slot nav-icon-dim" if dim else "nav-icon-slot"
    return (
        f'<span class="{slot_class}" style="display:inline-flex;align-items:center;'
        f'justify-content:center;width:22px;height:22px;flex-shrink:0;">'
        f'<svg viewBox="0 0 48 48" width="20" height="20" aria-hidden="true" '
        f'style="width:20px;height:20px;display:block;">'
        f'<g mask="url(#navMask{shape_name})">'
        '<rect width="48" height="48" fill="url(#navGoldBase)" />'
        f'<rect class="nav-shimmer-band" x="-48" width="48" height="48" fill="url(#navShimmerBand)" '
        f'style="mix-blend-mode: screen; animation-delay: {delay_s}s" />'
        '</g></svg></span>'
    )


def render_custom_nav(pages):
    """Custom sidebar nav standing in for Streamlit's built-in one (see
    fantasy_football_dashboard.py, which hides the native nav via
    position='hidden') - st.page_link keeps all the real navigation/routing/
    active-page behavior, this just draws a gold gradient + bevel + shimmer icon
    next to each label instead of a flat Material icon, since st.Page's icon
    param only accepts an emoji or a :material/name: string, never custom SVG."""
    with st.sidebar:
        for i, page in enumerate(pages):
            slug = page.title.lower().replace(" ", "-")
            shape_name = NAV_ICON_SHAPES.get(page.title)
            coming_soon = page.title in COMING_SOON_PAGES
            with st.container(key=f"navlink-{slug}"):
                # Always reserve the icon column, even for Home (which has no
                # shape) - an empty same-width spacer keeps every label
                # starting in the same column instead of Home needing its own
                # special centered treatment to not look like a stray, floating
                # nav item.
                icon_html = _nav_icon_html(shape_name, i * 0.15, dim=coming_soon) if shape_name else (
                    '<span class="nav-icon-slot" style="display:inline-flex;width:22px;height:22px;flex-shrink:0;"></span>'
                )
                st.markdown(icon_html, unsafe_allow_html=True)
                if coming_soon:
                    st.page_link(
                        page, label=f"{page.title} (Coming Soon)", disabled=True,
                        help="Available once the season starts",
                    )
                else:
                    st.page_link(page, label=page.title)


def render_nav_auto_collapse():
    """Auto-collapses the sidebar right after a nav link is tapped, but only
    on narrow/mobile viewports where the sidebar is a full-width overlay
    covering the page - on desktop it's a persistent side panel, where
    closing it on every click would just be an extra step to reopen it for
    the next one. st.markdown never executes <script> tags (its raw-HTML
    path uses dangerouslySetInnerHTML, which browsers don't run scripts
    from), so this goes through components.v1.html's real iframe instead and
    reaches back out to window.parent.document to click the app's own
    collapse button."""
    import streamlit.components.v1 as components

    components.html(
        """
        <script>
        (function() {
            var doc = window.parent.document;
            var MOBILE_BREAKPOINT = 640;

            function collapseSidebar() {
                var btn = doc.querySelector('[data-testid="stSidebarCollapseButton"] button');
                if (btn) btn.click();
            }

            function onClick(e) {
                var link = e.target.closest(
                    '[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"]'
                );
                if (!link) return;
                if (window.parent.innerWidth < MOBILE_BREAKPOINT) {
                    setTimeout(collapseSidebar, 150);
                }
            }

            // Delegate on document instead of binding to the links directly -
            // Streamlit tears down and rebuilds the sidebar's DOM nodes on
            // every navigation, but window.parent.document itself persists
            // across those reruns, so a listener attached to it survives.
            // The flag stops it from being attached again on every rerun
            // (this script itself re-executes each time, in a fresh iframe).
            if (!doc.__navAutoCollapseAttached) {
                doc.__navAutoCollapseAttached = true;
                doc.addEventListener('click', onClick, true);
            }
        })();
        </script>
        """,
        height=0,
    )


def _owner_avatar_color(owner):
    digest = sum(ord(c) for c in owner)
    return PALETTE["categorical"][digest % len(PALETTE["categorical"])]


def render_owner_banner(owner, subtitle=None):
    """Colored avatar + bold name banner for a single-owner detail page (Team
    Overview) - the same avatar-circle language used for every owner mention
    in the rankings tables, so a detail page reads as part of the same app
    instead of a plain form with a dropdown."""
    avatar_color = _owner_avatar_color(owner)
    initials = "".join(part[0].upper() for part in owner.split()[:2])
    subtitle_html = f'<div style="color:{PALETTE["ink_muted"]};font-size:0.85rem">{subtitle}</div>' if subtitle else ""
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:14px;margin:4px 0 18px;">'
        f'<span class="owner-avatar" style="background-color:{avatar_color};width:44px;height:44px;font-size:1rem">{initials}</span>'
        f'<div><div class="owner-name" style="font-size:1.3rem">{owner}</div>{subtitle_html}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def format_record(wins, losses, ties=0):
    """W-L, or W-L-T when there are ties - dropping ties silently is how a lower
    win% can look higher than a rival's (the tie games vanish from the ratio)."""
    record = f"{wins}-{losses}"
    if ties:
        record += f"-{ties}"
    return record


def render_rankings_table(rows):
    """Render the All-Time Rankings leaderboard as a grid-free layout: no cell
    borders, a colored avatar + bold owner name, and a gold/silver/bronze rank
    badge for the top 3, since st.dataframe doesn't expose this level of control."""
    column_labels = [
        "Titles", "Finals", "Playoff Apps", "Byes", "Best Record Seasons", "Most Points Seasons",
        "DFL Finishes", "All-Time Record", "Playoff Record", "Points Scored", "Seasons",
    ]

    header_cells = "".join(f'<div class="rankings-col-num">{label}</div>' for label in column_labels)
    header_html = (
        '<div class="rankings-header">'
        '<div></div><div></div><div>Owner</div><div class="rankings-col-num">Score</div>'
        f'{header_cells}</div>'
    )

    body_rows = []
    for row in rows:
        accent = RANK_ACCENT.get(row["rank"])
        rank_html = (
            f'<span class="rank-badge" style="background-color:{accent}22;color:{accent}">{row["rank"]}</span>'
            if accent else f'<span class="rankings-col-num">{row["rank"]}</span>'
        )
        avatar_color = _owner_avatar_color(row["owner"])
        initials = "".join(part[0].upper() for part in row["owner"].split()[:2])

        cells = [
            f'<div>{rank_html}</div>',
            f'<div><span class="owner-avatar" style="background-color:{avatar_color}">{initials}</span></div>',
            f'<div class="owner-name">{row["owner"]}</div>',
            f'<div class="score-pill" style="color:{PALETTE["categorical"][0]}">{row["score"]:.1f}</div>',
            f'<div class="rankings-col-num">{row["championships"]}</div>',
            f'<div class="rankings-col-num">{row["championship_appearances"]}</div>',
            f'<div class="rankings-col-num">{row["playoff_appearances"]}</div>',
            f'<div class="rankings-col-num">{row["bye_weeks"]}</div>',
            f'<div class="rankings-col-num">{row["best_record_seasons"]}</div>',
            f'<div class="rankings-col-num">{row["most_points_seasons"]}</div>',
            f'<div class="rankings-col-num">{row["dfl_finishes"]}</div>',
            f'<div class="rankings-col-num">{format_record(row["total_wins"], row["total_losses"], row["total_ties"])}</div>',
            f'<div class="rankings-col-num">{format_record(row["playoff_wins"], row["playoff_losses"], row["playoff_ties"])}</div>',
            f'<div class="rankings-col-num">{row["total_points"]:,.1f}</div>',
            f'<div class="rankings-col-num">{row["years_played"]}</div>',
        ]
        body_rows.append(f'<div class="rankings-row">{"".join(cells)}</div>')

    html = f"""
    <div class="rankings-wrap">
      {header_html}
      <div class="rankings-body">{''.join(body_rows)}</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def _rank_and_avatar_html(row):
    accent = RANK_ACCENT.get(row["rank"])
    rank_html = (
        f'<span class="rank-badge" style="background-color:{accent}22;color:{accent}">{row["rank"]}</span>'
        if accent else f'<span class="rankings-col-num">{row["rank"]}</span>'
    )
    avatar_color = _owner_avatar_color(row["owner"])
    initials = "".join(part[0].upper() for part in row["owner"].split()[:2])
    avatar_html = f'<span class="owner-avatar" style="background-color:{avatar_color}">{initials}</span>'
    return rank_html, avatar_html


def render_leaderboard(rows, extra_columns, score_fmt="{:.1f}"):
    """Generic version of render_rankings_table for a different column set (GM/Coach
    rankings): same grid-free chrome (avatar, rank badge, score pill), with a
    caller-supplied list of extra columns. extra_columns is [(label, key), ...] -
    row[key] must already be a display-ready string."""
    n_extra = len(extra_columns)
    grid_style = f'grid-template-columns: 46px 34px 1.4fr 0.7fr {" ".join(["1fr"] * n_extra)};'

    header_cells = "".join(f'<div class="rankings-col-num">{label}</div>' for label, _ in extra_columns)
    header_html = (
        f'<div class="rankings-header" style="{grid_style}">'
        '<div></div><div></div><div>Owner</div><div class="rankings-col-num">Score</div>'
        f'{header_cells}</div>'
    )

    body_rows = []
    for row in rows:
        rank_html, avatar_html = _rank_and_avatar_html(row)
        cells = [
            f'<div>{rank_html}</div>',
            f'<div>{avatar_html}</div>',
            f'<div class="owner-name">{row["owner"]}</div>',
            f'<div class="score-pill" style="color:{PALETTE["categorical"][0]}">{score_fmt.format(row["score"])}</div>',
        ]
        cells += [f'<div class="rankings-col-num">{row[key]}</div>' for _, key in extra_columns]
        body_rows.append(f'<div class="rankings-row" style="{grid_style}">{"".join(cells)}</div>')

    html = f"""
    <div class="rankings-wrap">
      {header_html}
      <div class="rankings-body">{''.join(body_rows)}</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def render_record_card(col, section, i, record):
    with col:
        with st.container(border=True, key=f"card-{section}-{i}"):
            st.caption(record['label'])
            st.markdown(f"### {record['display_value']}")
            holders = record['holders']
            if len(holders) > 3:
                holder_str = f"{len(holders)}-way tie"
            else:
                holder_str = " & ".join(holders)
            st.write(f"**{holder_str}**")
            if record['detail']:
                st.caption(record['detail'])


def render_record_grid(section, records, n_cols=3):
    items = list(records.values())
    for i in range(0, len(items), n_cols):
        row_items = items[i:i + n_cols]
        cols = st.columns(n_cols)
        for j, (col, record) in enumerate(zip(cols, row_items)):
            render_record_card(col, section, i + j, record)


def theme_plotly(fig):
    """Apply the app's light surface + validated categorical palette to a Plotly figure."""
    fig.update_layout(
        template="plotly_white",
        paper_bgcolor=PALETTE["surface"],
        plot_bgcolor=PALETTE["surface"],
        font_color=PALETTE["ink_secondary"],
        title_font_color=PALETTE["ink_primary"],
        colorway=PALETTE["categorical"],
        legend=dict(bgcolor="rgba(0,0,0,0)"),
        margin=dict(t=60, l=10, r=10, b=10),
    )
    fig.update_xaxes(gridcolor=PALETTE["gridline"], linecolor=PALETTE["axis"], zerolinecolor=PALETTE["axis"])
    fig.update_yaxes(gridcolor=PALETTE["gridline"], linecolor=PALETTE["axis"], zerolinecolor=PALETTE["axis"])
    return fig


def render_trivia_carousel(records, seconds_per_card=7, height=190):
    """Continuously scrolling left-to-right ticker of trivia cards for the Home
    page - a real marquee, not a one-at-a-time slideshow. Pure CSS animation (a
    duplicated track translated by -50% and looped) so it never stutters waiting
    on JS timers; hovering pauses it so a card can be read in full. Built with
    components.v1.html for style isolation from Streamlit's own CSS."""
    import streamlit.components.v1 as components

    items = list(records.values())
    if not items:
        return

    colors = PALETTE["categorical"]

    def _card(r, i):
        color = colors[i % len(colors)]
        holders = r['holders']
        holder_str = f"{len(holders)}-way tie" if len(holders) > 3 else " & ".join(holders)
        detail_html = f'<div class="detail">{r["detail"]}</div>' if r.get('detail') else ""
        return (
            f'<div class="card" style="border-top-color:{color}">'
            f'<div class="label" style="color:{color}">{r["label"]}</div>'
            f'<div class="value">{r["display_value"]}</div>'
            f'<div class="holder">{holder_str}</div>'
            f'{detail_html}</div>'
        )

    # The track is the card list twice back-to-back, animated exactly -50% of its
    # own width - the moment the first copy scrolls fully offscreen, the second
    # copy is in the exact position the first started in, so the loop is seamless.
    cards_html = "".join(_card(r, i) for i, r in enumerate(items))
    track_html = cards_html + cards_html
    duration = max(20, len(items) * seconds_per_card)

    html = f"""
    <html><head><style>
      html, body {{ margin:0; padding:0; font-family:-apple-system,"Segoe UI",sans-serif;
                    background:transparent; overflow:hidden; }}
      .wrap {{ height:{height - 16}px; overflow:hidden; -webkit-mask-image: linear-gradient(90deg,
               transparent, #000 5%, #000 95%, transparent);
               mask-image: linear-gradient(90deg, transparent, #000 5%, #000 95%, transparent); }}
      .track {{ display:flex; height:100%; width:max-content; gap:16px; padding:8px 0;
                box-sizing:border-box; animation: scroll {duration}s linear infinite; }}
      .track:hover {{ animation-play-state: paused; }}
      @keyframes scroll {{
        from {{ transform: translateX(0); }}
        to {{ transform: translateX(-50%); }}
      }}
      .card {{ flex: 0 0 300px; box-sizing:border-box; padding:18px 22px;
               border-radius:12px; border-top:4px solid transparent;
               background:{PALETTE['surface']}; box-shadow:0 1px 3px rgba(0,0,0,0.10);
               display:flex; flex-direction:column; justify-content:center; }}
      .label {{ text-transform:uppercase; letter-spacing:0.06em; font-size:0.72rem;
                font-weight:700; margin-bottom:6px; }}
      .value {{ font-size:1.6rem; font-weight:800; color:{PALETTE['ink_primary']}; }}
      .holder {{ font-size:0.92rem; font-weight:700; color:{PALETTE['ink_secondary']}; margin-top:2px; }}
      .detail {{ font-size:0.78rem; color:{PALETTE['ink_muted']}; margin-top:4px; }}
    </style></head>
    <body>
      <div class="wrap"><div class="track">{track_html}</div></div>
    </body></html>
    """
    components.html(html, height=height)


def render_storyline_feed(storylines, edition_label=None):
    """Comic-book splash page for the Home page's season storylines: a skewed
    logo banner, halftone-textured panels with a hard offset shadow and a slight
    alternating tilt, and burst-badge tags - deliberately NOT another row/column
    table since the rest of the site already uses that structure for rankings
    and stats. Every tag badge shares one fixed comic color scheme (rather than a
    different hue per category) since a wall of rainbow labels reads as a chart
    legend, not a comic cover. storylines is [{owner, tags, text}, ...] -
    everything an owner qualifies for is already merged into one card upstream
    (see home_stats._combine_by_owner), so nobody's name shows up twice."""
    if not storylines:
        st.info("No storylines yet - check back once there's a season of league history.")
        return

    cards_html = ""
    for i, s in enumerate(storylines):
        lead_class = " news-lead" if i == 0 else ""
        tags_html = "".join(f'<span class="comic-tag">{tag}</span>' for tag in s["tags"])
        cards_html += (
            f'<div class="news-card{lead_class}">'
            f'<div class="comic-tag-row">{tags_html}</div>'
            f'<div class="news-headline">{s["text"]}</div>'
            '</div>'
        )

    subtitle_html = f'<div class="comic-tagline">{edition_label}</div>' if edition_label else ''
    masthead = (
        '<div class="comic-masthead">'
        '<div class="comic-logo">League Insider</div>'
        f'{subtitle_html}'
        '</div>'
    )

    st.markdown(f'{masthead}<div class="news-grid">{cards_html}</div>', unsafe_allow_html=True)


# A dark, gold-accented "sportsbook slip" look for the Vegas-blended card -
# distinct on purpose from the rest of this app's light theme, the same way
# a real odds board reads differently than the surrounding page. The ESPN
# comparison card stays in this app's normal light card language, so the two
# are visually unmistakable at a glance, not just by their labels. Shared
# between views/matchup_predictor.py and the Home page carousel so both
# always render the identical card.
VEGAS_THEME = {
    'bg': 'linear-gradient(160deg, #14181f, #1d2430)',
    'border': '#8a5a17',
    'ink_primary': '#f7f3ea',
    'ink_muted': '#a9a394',
    'accent': PALETTE['categorical'][3],  # gold
    'pill_bg': PALETTE['categorical'][3],
    'pill_text': '#1a1206',
    'bar_home': PALETTE['categorical'][3],
    'bar_away': PALETTE['categorical'][2],
}
ESPN_THEME = {
    'bg': PALETTE['surface'],
    'border': PALETTE['gridline'],
    'ink_primary': PALETTE['ink_primary'],
    'ink_muted': PALETTE['ink_muted'],
    'accent': PALETTE['ink_secondary'],
    'pill_bg': PALETTE['page'],
    'pill_text': PALETTE['ink_muted'],
    'bar_home': PALETTE['categorical'][0],
    'bar_away': PALETTE['categorical'][1],
}


def _ats_str(ats_records, owner):
    if not ats_records:
        return None
    rec = ats_records.get(owner)
    if not rec:
        return None
    s = f"{rec['beats']}-{rec['misses']}"
    if rec['pushes']:
        s += f"-{rec['pushes']}"
    return s


def _moneyline_str(odds):
    return f"+{odds:.0f}" if odds > 0 else f"{odds:.0f}"


def render_sportsbook_card(theme, label, m, pred, show_details, ats_records=None, espn_pred=None):
    """One Vegas-style matchup card. Used both for the full Scoreboard &
    Matchup Predictor page and for one slide of the Home page's Matchups
    and Predictions carousel (render_matchup_carousel). `m` is one entry
    from espn_data.get_current_week_matchups (carries live home_score/
    away_score alongside the lineups); `pred` is
    matchup_predictor_stats.compute_matchup_prediction's output - the
    Vegas-blended projection, which is what this card is built around.
    `espn_pred` (compute_espn_only_prediction's output) is optional and,
    when given, adds ESPN's own projected points as a small subnote under
    each team's Vegas number - this used to be its own separate ESPN-themed
    card; folding it in here as one line removes a whole card's worth of
    visual noise (its own spread, win-probability bar, etc.) for a number
    that's really just a point of comparison, not a second prediction
    worth equal billing."""
    from matchup_predictor_stats import win_prob_to_moneyline

    home_favorite = pred['spread'] > 0
    favorite_team = m['home_team_name'] if home_favorite else m['away_team_name']
    ml_home = win_prob_to_moneyline(pred['win_prob_home'])
    ml_away = win_prob_to_moneyline(pred['win_prob_away'])

    def _team_block(name, owner, score, live_score, moneyline, espn_score, is_favorite, align):
        ats = _ats_str(ats_records, owner) if show_details else None
        detail_html = ""
        if show_details:
            detail_html = f'<div style="font-size:0.74rem;color:{theme["ink_muted"]}">{owner}</div>'
            if ats:
                detail_html += f'<div style="font-size:0.7rem;color:{theme["ink_muted"]}">ATS: {ats}</div>'
        espn_html = ""
        if espn_score is not None:
            espn_html = (
                f'<div style="font-size:0.68rem;color:{theme["ink_muted"]};margin-top:3px;">'
                f'ESPN Projection: {espn_score:.1f}</div>'
            )
        live_html = ""
        if live_score and live_score > 0:
            live_html = (
                f'<div style="font-size:0.68rem;font-weight:700;color:{PALETTE["status"]["good"]};'
                f'margin-top:2px;">&#9679; LIVE {live_score:,.1f}</div>'
            )
        score_color = theme['accent'] if is_favorite else theme['ink_primary']
        # Built as ONE unbroken line, not a multi-line triple-quoted string -
        # this whole card gets spliced into an outer f-string, and any line
        # left indented 4+ spaces at that point reads as a Markdown code
        # block (rendered as literal text) instead of HTML once it reaches
        # st.markdown, regardless of how it looked indented in this source.
        return (
            f'<div style="flex:1;text-align:{align};">'
            f'<div style="font-weight:700;color:{theme["ink_primary"]};font-size:0.95rem;">{name}</div>'
            f'{detail_html}'
            f'<div style="font-size:1.6rem;font-weight:800;color:{score_color};margin-top:3px;">{score:.1f}</div>'
            f'<div style="font-size:0.72rem;color:{theme["ink_muted"]};margin-top:1px;">{_moneyline_str(moneyline)}</div>'
            f'{espn_html}'
            f'{live_html}'
            f'</div>'
        )

    home_block = _team_block(
        m['home_team_name'], m['home_owner'], pred['home_projected'], m.get('home_score'),
        ml_home, espn_pred['home_projected'] if espn_pred else None, home_favorite, 'left')
    away_block = _team_block(
        m['away_team_name'], m['away_owner'], pred['away_projected'], m.get('away_score'),
        ml_away, espn_pred['away_projected'] if espn_pred else None, not home_favorite, 'right')

    # Same one-line-per-fragment discipline as _team_block, for the same
    # reason - this return value goes straight into st.markdown.
    return (
        f'<div style="background:{theme["bg"]};border:1.5px solid {theme["border"]};border-radius:12px;'
        f'padding:16px 18px;height:100%;box-sizing:border-box;">'
        f'<div style="display:inline-block;background:{theme["pill_bg"]};color:{theme["pill_text"]};'
        f'font-size:0.65rem;font-weight:800;text-transform:uppercase;letter-spacing:0.07em;'
        f'padding:3px 10px;border-radius:20px;margin-bottom:12px;">{label}</div>'
        f'<div style="display:flex;align-items:flex-start;gap:10px;">'
        f'{home_block}'
        f'<div style="color:{theme["ink_muted"]};font-weight:700;padding-top:4px;font-size:0.85rem;">@</div>'
        f'{away_block}'
        f'</div>'
        f'<div style="margin-top:14px;padding-top:12px;border-top:1px solid {theme["border"]};">'
        f'<div style="font-size:0.65rem;color:{theme["ink_muted"]};text-transform:uppercase;'
        f'letter-spacing:0.06em;">Spread</div>'
        f'<div style="font-weight:700;color:{theme["accent"]};font-size:0.95rem;">'
        f'{favorite_team} {-abs(pred["spread"]):.1f}</div>'
        f'</div>'
        f'<div style="margin-top:10px;">'
        f'<div style="display:flex;height:8px;border-radius:4px;overflow:hidden;background:{theme["border"]}44;">'
        f'<div style="width:{pred["win_prob_home"] * 100:.2f}%;background:{theme["bar_home"]}"></div>'
        f'<div style="width:{pred["win_prob_away"] * 100:.2f}%;background:{theme["bar_away"]}"></div>'
        f'</div>'
        f'<div style="display:flex;justify-content:space-between;font-size:0.7rem;color:{theme["ink_muted"]};'
        f'margin-top:4px;"><span>{pred["win_prob_home"] * 100:.1f}%</span>'
        f'<span>{pred["win_prob_away"] * 100:.1f}%</span></div>'
        f'</div>'
        f'</div>'
    )


def render_matchup_carousel(predictions, ats_records=None, seconds_per_card=10, height=300):
    """Same continuously-scrolling marquee mechanic as render_trivia_carousel
    (a duplicated track animated -50% and looped, built with
    components.v1.html for CSS isolation) - one slide per matchup instead of
    one trivia fact, each slide a single Vegas sportsbook card (ESPN's
    projection folded in as a subnote, see render_sportsbook_card) via
    render_sportsbook_card, so this always looks identical to the full
    Scoreboard & Matchup Predictor page. predictions is
    [(matchup, vegas_pred, espn_pred), ...]."""
    import streamlit.components.v1 as components

    if not predictions:
        return

    def _slide(m, vegas_pred, espn_pred):
        card_html = render_sportsbook_card(VEGAS_THEME, "Vegas Projection", m, vegas_pred, True, ats_records, espn_pred)
        return (
            f'<div class="slide">'
            f'<div class="slide-title">{m["home_team_name"]} vs {m["away_team_name"]}</div>'
            f'<div class="slide-card">{card_html}</div>'
            f'</div>'
        )

    slides_html = "".join(_slide(m, vp, ep) for m, vp, ep in predictions)
    track_html = slides_html + slides_html
    duration = max(30, len(predictions) * seconds_per_card)

    html = f"""
    <html><head><style>
      html, body {{ margin:0; padding:0; font-family:-apple-system,"Segoe UI",sans-serif;
                    background:transparent; overflow:hidden; }}
      .wrap {{ height:{height - 16}px; overflow:hidden; -webkit-mask-image: linear-gradient(90deg,
               transparent, #000 3%, #000 97%, transparent);
               mask-image: linear-gradient(90deg, transparent, #000 3%, #000 97%, transparent); }}
      .track {{ display:flex; height:100%; width:max-content; gap:20px; padding:8px 4px;
                box-sizing:border-box; animation: scroll {duration}s linear infinite; }}
      .track:hover {{ animation-play-state: paused; }}
      @keyframes scroll {{
        from {{ transform: translateX(0); }}
        to {{ transform: translateX(-50%); }}
      }}
      .slide {{ flex: 0 0 340px; box-sizing:border-box; display:flex; flex-direction:column; }}
      .slide-title {{ font-weight:700; color:{PALETTE['ink_muted']}; font-size:0.78rem;
                      text-transform:uppercase; letter-spacing:0.04em; margin-bottom:8px; }}
      .slide-card {{ flex:1; min-width:0; }}
    </style></head>
    <body>
      <div class="wrap"><div class="track">{track_html}</div></div>
    </body></html>
    """
    components.html(html, height=height)


def render_rumor_feed(rumors):
    """Twitter/X-style feed for the League News page's Rumor Mill - every
    entry traces back to a real fact (see home_stats.compute_rumors), just
    delivered in a gossipy voice instead of League Insider's newspaper one.
    rumors is [{'handle', 'text', 'category'}, ...]."""
    if not rumors:
        st.info(
            "No rumors yet this season - check back once there's been some real league "
            "activity (trades, streaks, a tight playoff race) to gossip about.",
            icon=":material/chat_bubble:",
        )
        return

    cards_html = ""
    for r in rumors:
        handle = r['handle']
        avatar_color = _owner_avatar_color(handle)
        initials = handle.lstrip('@')[:2].upper()
        cards_html += (
            '<div class="rumor-card">'
            f'<span class="owner-avatar" style="background-color:{avatar_color};width:38px;height:38px;">'
            f'{initials}</span>'
            '<div>'
            f'<div style="font-weight:700;color:{PALETTE["ink_primary"]};font-size:0.88rem;">{handle}'
            f'<span style="font-weight:400;color:{PALETTE["ink_muted"]};font-size:0.8rem;"> &middot; insider tip</span>'
            '</div>'
            f'<div style="margin-top:3px;color:{PALETTE["ink_secondary"]};font-size:0.92rem;line-height:1.4;">'
            f'{r["text"]}</div>'
            '</div>'
            '</div>'
        )

    st.markdown(f'<div class="rumor-feed">{cards_html}</div>', unsafe_allow_html=True)


def render_mini_board(rows, columns, name_key='owner', subtitle_key=None, key_prefix='mini'):
    """Compact grid-free ranked list for the Home page's award/race widgets.
    columns is [(label, value_fn)] where value_fn(row) returns an already
    display-ready string. Built as a real CSS grid (not st.columns per row) -
    Streamlit auto-stacks st.columns vertically below ~640px, which would
    turn every row into a tall stack of separate fields on a phone instead of
    a compact table row, so this uses the same raw-HTML-grid approach as
    render_rankings_table/render_leaderboard. min-width is overridden to 0
    (those two need 1280px+ for their column count; this one doesn't) so it
    shrinks to fit a phone instead of forcing horizontal scroll needlessly."""
    n_extra = len(columns)
    grid_style = f'grid-template-columns: 32px 2.2fr {" ".join(["1fr"] * n_extra)}; min-width: 0;'

    header_cells = "".join(
        f'<div class="rankings-col-num" style="text-transform:uppercase;letter-spacing:0.05em;'
        f'font-size:0.68rem;color:{PALETTE["ink_muted"]}">{label}</div>'
        for label, _ in columns
    )
    header_html = f'<div class="rankings-header" style="{grid_style}"><div></div><div></div>{header_cells}</div>'

    body_rows = []
    for i, row in enumerate(rows):
        accent = RANK_ACCENT.get(i + 1)
        rank_html = (
            f'<span class="rank-badge" style="background-color:{accent}22;color:{accent}">{i + 1}</span>'
            if accent else f'<span class="rankings-col-num">{i + 1}</span>'
        )
        subtitle_html = ""
        if subtitle_key and row.get(subtitle_key):
            subtitle_html = f'<div style="color:{PALETTE["ink_muted"]};font-size:0.78rem">{row[subtitle_key]}</div>'
        cells = [
            f'<div>{rank_html}</div>',
            f'<div class="owner-name" style="font-size:0.9rem">{row[name_key]}</div>{subtitle_html}',
        ]
        cells += [f'<div class="rankings-col-num">{value_fn(row)}</div>' for _, value_fn in columns]
        body_rows.append(f'<div class="rankings-row" style="{grid_style}">{"".join(cells)}</div>')

    html = f"""
    <div class="rankings-wrap">
      {header_html}
      <div class="rankings-body">{''.join(body_rows)}</div>
    </div>
    """
    with st.container(border=True, key=f"mini-{key_prefix}"):
        st.markdown(html, unsafe_allow_html=True)


def render_loading_screen(message="Loading..."):
    """A single centered spinning-wheel + message, meant to sit inside an
    st.empty() placeholder that later gets swapped for the real page content
    once everything is ready - one clean reveal instead of sections popping
    in individually over time. Built as one unbroken f-string line (not a
    multi-line triple-quoted string) since Markdown treats 4+ leading spaces
    as a literal indented code block, which would otherwise render this as
    visible text instead of parsing it as real HTML/CSS."""
    st.markdown(
        f'<style>@keyframes ffLoadingSpin {{ to {{ transform: rotate(360deg); }} }}</style>'
        f'<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;'
        f'padding:110px 20px;gap:18px;">'
        f'<div style="width:46px;height:46px;border-radius:50%;'
        f'border:4px solid {PALETTE["gridline"]};border-top-color:{PALETTE["categorical"][3]};'
        f'animation:ffLoadingSpin 0.8s linear infinite;"></div>'
        f'<div style="color:{PALETTE["ink_muted"]};font-weight:600;font-size:0.95rem;'
        f'letter-spacing:0.01em;">{message}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def render_sidebar_info():
    st.sidebar.markdown("---")
    st.sidebar.info(
        "**2026 Season Update!** The app now includes 2026 season data support. "
        "Navigate to different tabs to explore your league's history and current season stats. "
        "H2H Matrix shows comprehensive head-to-head records across all seasons.",
        icon=":material/campaign:",
    )


def render_footer():
    st.markdown("---")
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.caption(f"Last updated: {current_time} · Now supporting 2019-2026 seasons")
