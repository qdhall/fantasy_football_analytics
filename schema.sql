-- Multi-tenant Postgres schema for the Fantasy Football Analytics app.
-- See /Users/qhall/.claude/plans/mellow-mapping-brook.md for the full design
-- rationale. Run this once against a fresh Supabase project to create
-- everything; db.py's sync_season()/ensure_synced() populate and maintain it.
--
-- league_id is a first-class tenant key on every table from day one, even
-- though only one league populates it today - adding a second league later
-- is a data-population exercise, not a schema change.

CREATE TABLE leagues (
    id              bigserial PRIMARY KEY,
    platform        text NOT NULL DEFAULT 'espn',
    espn_league_id  bigint NOT NULL,
    name            text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (platform, espn_league_id)
);

-- One row per league-year. Also where get_league_scoring_settings() and
-- get_slot_structure()'s outputs live - both are live-refetched-every-time
-- today even for long-final seasons; this closes that gap.
CREATE TABLE seasons (
    league_id             bigint NOT NULL REFERENCES leagues(id),
    year                  int NOT NULL,
    playoff_start_week    smallint NOT NULL,
    playoff_team_count    smallint,
    scoring_settings      jsonb NOT NULL DEFAULT '{}',   -- {statID: points}
    dedicated_slots       jsonb NOT NULL DEFAULT '[]',   -- [["QB",1],["RB",2],...]
    flex_slots            jsonb NOT NULL DEFAULT '[]',
    is_final              boolean NOT NULL DEFAULT false, -- mirrors _is_year_final()
    synced_through_week   smallint NOT NULL DEFAULT 0,
    last_synced_at        timestamptz,
    PRIMARY KEY (league_id, year)
);
CREATE INDEX idx_seasons_final ON seasons (league_id, is_final);

-- Stable owner identity - the same display-name string get_owner_name()
-- already uses as a dict key everywhere. No separate person/auth entity yet
-- (deliberately deferred to the later multi-user rebuild).
CREATE TABLE owners (
    id            bigserial PRIMARY KEY,
    league_id     bigint NOT NULL REFERENCES leagues(id),
    display_name  text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (league_id, display_name)
);

-- One row per owner per season - the "team" for that year, plus the resolved
-- championship/DFL/best-record/most-points flags, computed once at sync time
-- with the same tiebreak logic _compute_league_history_year uses today
-- (min/max by (wins, points)) and persisted forever once a season is final.
CREATE TABLE season_teams (
    league_id        bigint NOT NULL,
    year             int NOT NULL,
    owner_id         bigint NOT NULL REFERENCES owners(id),
    espn_team_id     int NOT NULL,
    team_name        text,
    wins             smallint NOT NULL DEFAULT 0,
    losses           smallint NOT NULL DEFAULT 0,
    ties             smallint NOT NULL DEFAULT 0,
    points_for       numeric(8,2) NOT NULL DEFAULT 0,
    standing         smallint,
    final_standing   smallint,
    made_playoffs    boolean NOT NULL DEFAULT false,
    is_champion      boolean NOT NULL DEFAULT false,
    is_runner_up     boolean NOT NULL DEFAULT false,
    is_dfl           boolean NOT NULL DEFAULT false,
    is_best_record   boolean NOT NULL DEFAULT false,
    is_most_points   boolean NOT NULL DEFAULT false,
    bye_weeks        smallint NOT NULL DEFAULT 0,
    PRIMARY KEY (league_id, year, owner_id),
    FOREIGN KEY (league_id, year) REFERENCES seasons(league_id, year)
);

-- ONE row per real matchup, not duplicated per side (today's in-memory
-- game_log is stored twice, once per owner, with a dedup step downstream
-- because of it - see league_stats._unique_games).
--
-- is_playoff uses the STRICTER, symmetric definition from
-- get_all_time_h2h_by_scores_fixed (both teams made the playoffs), not
-- _compute_league_history_year's per-team-independent version - the two
-- currently disagree in the live app. Normalizing to one column forces
-- picking one; the stricter version is more correct. Expect League
-- Records/Wall of Shame/Trivia numbers to shift slightly once games/queries
-- read from this table - that's an intentional bugfix, not a regression, and
-- should be called out to the user when that migration step ships.
CREATE TABLE games (
    id               bigserial PRIMARY KEY,
    league_id        bigint NOT NULL,
    year             int NOT NULL,
    week             smallint NOT NULL,
    is_playoff       boolean NOT NULL DEFAULT false,
    home_owner_id    bigint NOT NULL REFERENCES owners(id),
    home_score       numeric(6,2) NOT NULL,
    away_owner_id    bigint NOT NULL REFERENCES owners(id),
    away_score       numeric(6,2) NOT NULL,
    winner_owner_id  bigint REFERENCES owners(id),  -- NULL on a tie
    UNIQUE (league_id, year, week, home_owner_id, away_owner_id),
    FOREIGN KEY (league_id, year) REFERENCES seasons(league_id, year)
);
CREATE INDEX idx_games_home_owner ON games (league_id, home_owner_id, year, week);
CREATE INDEX idx_games_away_owner ON games (league_id, away_owner_id, year, week);
CREATE INDEX idx_games_week       ON games (league_id, year, week);

-- Reconstructs the old per-owner, per-side-duplicated game_log shape as a
-- read view, purely so common.get_league_history() can hand *_stats.py the
-- exact same dict shape it already expects - no changes needed downstream.
CREATE VIEW v_owner_game_log AS
    SELECT league_id, year, week, is_playoff,
           home_owner_id AS owner_id, home_score AS points,
           away_score AS opp_points, away_owner_id AS opponent_id,
           CASE WHEN home_score > away_score THEN 'W'
                WHEN home_score < away_score THEN 'L' ELSE 'T' END AS result
    FROM games
    UNION ALL
    SELECT league_id, year, week, is_playoff,
           away_owner_id, away_score, home_score, home_owner_id,
           CASE WHEN away_score > home_score THEN 'W'
                WHEN away_score < home_score THEN 'L' ELSE 'T' END
    FROM games;

-- Global player dimension keyed on ESPN's own numeric playerId - already
-- sitting on every BoxPlayer today (p.playerId) and currently thrown away in
-- favor of just the name (_lineup_players, espn_data.py). Free to add now;
-- does NOT solve the separate ESPN<->Vegas-odds-provider name-matching gap
-- (odds_data.py) - that's a different provider's IDs with no shared key,
-- explicitly out of scope for this migration.
CREATE TABLE players (
    id               bigint PRIMARY KEY,   -- ESPN's playerId
    name             text NOT NULL,
    position         text,
    normalized_name  text GENERATED ALWAYS AS
                      (lower(regexp_replace(name, '[^a-zA-Z ]', '', 'g'))) STORED,
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_players_normalized_name ON players (normalized_name);

CREATE TABLE draft_picks (
    league_id   bigint NOT NULL,
    year        int NOT NULL,
    player_id   bigint NOT NULL REFERENCES players(id),
    owner_id    bigint NOT NULL REFERENCES owners(id),
    round_num   smallint NOT NULL,
    round_pick  smallint NOT NULL,
    PRIMARY KEY (league_id, year, player_id),
    FOREIGN KEY (league_id, year) REFERENCES seasons(league_id, year)
);
CREATE INDEX idx_draft_picks_owner ON draft_picks (league_id, owner_id, year);

-- The player x owner x week fact - replaces BOTH the season_box_scores cache
-- kind and the raw weekly walk inside _compute_front_office_year. One row per
-- player per week per roster they were actually on that week (a mid-season
-- trade produces separate rows under each owner, never a fractional split -
-- exactly matching _compute_front_office_year's existing possession-window
-- logic, which groups a player's weekly stat lines by whichever owner had
-- them that specific week).
CREATE TABLE player_weeks (
    league_id         bigint NOT NULL,
    year              int NOT NULL,
    week              smallint NOT NULL,
    player_id         bigint NOT NULL REFERENCES players(id),
    owner_id          bigint NOT NULL REFERENCES owners(id),
    position          text,
    slot              text NOT NULL,   -- ESPN slot_position: 'QB','BE','IR','RB/WR/TE',...
    pro_team          text,
    actual_points     numeric(6,2) NOT NULL DEFAULT 0,
    projected_points  numeric(6,2) NOT NULL DEFAULT 0,
    PRIMARY KEY (league_id, year, week, player_id),
    FOREIGN KEY (league_id, year) REFERENCES seasons(league_id, year)
);
-- Covers "this owner's whole roster for one week" (coach/luck rollups),
-- avoiding a heap fetch per row:
CREATE INDEX idx_pw_owner_week ON player_weeks (league_id, owner_id, year, week)
    INCLUDE (slot, actual_points, projected_points);
-- Covers the (player_id, owner_id, year) GROUP BY that reproduces
-- gm_year['picks']/['acquisitions'] decision rows exactly:
CREATE INDEX idx_pw_player_owner_year ON player_weeks (league_id, player_id, owner_id, year);

-- NEW - not present in any form today. Persists get_recent_activity's
-- reliably-typed trade/waiver/drop data going forward (it's already being
-- fetched for the live "recent activity" widget - this is a zero-extra-I/O
-- side effect of the same call), so FUTURE seasons can resolve
-- front_office's currently-undifferentiated "acquisition" bucket into real
-- trade-vs-waiver history. Cannot backfill 2019-2025 - ESPN's
-- recent_activity endpoint is a rolling recent-only window, not a full
-- historical log. That's a hard, permanent limitation, not a to-do.
CREATE TABLE roster_moves (
    id                     bigserial PRIMARY KEY,
    league_id              bigint NOT NULL,
    year                   int NOT NULL,
    occurred_at            timestamptz NOT NULL,
    kind                   text NOT NULL
                           CHECK (kind IN ('trade','waiver_add','fa_add','drop')),
    owner_id               bigint REFERENCES owners(id),
    counterparty_owner_id  bigint REFERENCES owners(id),  -- only set for kind='trade'
    player_id              bigint NOT NULL REFERENCES players(id),
    bid_amount             numeric(6,2),
    trade_group_id         uuid,  -- links every leg of one multi-player trade
    UNIQUE (league_id, occurred_at, owner_id, player_id, kind)
);
CREATE INDEX idx_roster_moves_player ON roster_moves (league_id, player_id, occurred_at);

-- Deliberately NO dedicated tables for the old 'all_time_stats'/'owner_trend'
-- pickle-cache kinds - both are cheap aggregations over season_teams +
-- v_owner_game_log at read time (Team Overview page only, low traffic),
-- consistent with the fact that the whole *_stats.py layer is already
-- millisecond-cheap once input data is in memory - the expense being fixed
-- by this migration is ESPN refetching, not Python-side computation.
