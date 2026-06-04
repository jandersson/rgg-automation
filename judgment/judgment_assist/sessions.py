"""SQLite telemetry for live game sessions.

One row in ``sessions`` per live run; one row in ``blackjack_hands`` per finished
hand. The point is to accumulate data across many sessions so anomalies are
visible — "is something off" with the game (outcome rates, dealer up-card
distribution) or with our own pipeline (reader-miss rate).

We log the **reliable** signals only: the hand ``outcome`` (the result banner,
validated 85/85) and the HUD ``player_total`` + ``dealer_up`` (the digit reader,
validated 12/12). Those are trustworthy even though full-table card reading is
not. The Hi-Lo ``running``/``true_count``/``cards_seen`` columns are filled only
when ``--count`` is on and are best-effort (see issue #3) — kept so the data is
there if a persistent shoe is ever confirmed.

``now`` is injectable on every write so tests are deterministic and so the module
has no hidden clock dependency.
"""
from __future__ import annotations

import datetime
import os
import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at   TEXT,
    game       TEXT NOT NULL,
    config     TEXT,
    note       TEXT
);
CREATE TABLE IF NOT EXISTS blackjack_hands (
    id           INTEGER PRIMARY KEY,
    session_id   INTEGER NOT NULL REFERENCES sessions(id),
    hand_no      INTEGER NOT NULL,
    ended_at     TEXT NOT NULL,
    outcome      TEXT,
    player_total INTEGER,
    dealer_up    INTEGER,
    running      INTEGER,
    true_count   REAL,
    cards_seen   INTEGER
);
CREATE INDEX IF NOT EXISTS ix_hands_session ON blackjack_hands(session_id);
"""


def _stamp(now):
    return (now or datetime.datetime.now()).isoformat(timespec="seconds")


class SessionStore:
    """A thin wrapper over a SQLite file. Safe to open repeatedly (idempotent
    schema). Each live run calls ``start_session`` once, then ``record_hand`` per
    finished hand, then ``close_session`` on exit."""

    def __init__(self, path):
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def start_session(self, game, config=None, note=None, now=None):
        cur = self.conn.execute(
            "INSERT INTO sessions(started_at, game, config, note) VALUES (?,?,?,?)",
            (_stamp(now), game, config, note))
        self.conn.commit()
        return cur.lastrowid

    def record_hand(self, session_id, hand_no, outcome=None, player_total=None,
                    dealer_up=None, running=None, true_count=None,
                    cards_seen=None, now=None):
        self.conn.execute(
            "INSERT INTO blackjack_hands(session_id, hand_no, ended_at, outcome, "
            "player_total, dealer_up, running, true_count, cards_seen) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (session_id, hand_no, _stamp(now), outcome, player_total, dealer_up,
             running, true_count, cards_seen))
        self.conn.commit()

    def close_session(self, session_id, now=None):
        self.conn.execute("UPDATE sessions SET ended_at = ? WHERE id = ?",
                          (_stamp(now), session_id))
        self.conn.commit()

    def close(self):
        self.conn.close()


# --- analysis -------------------------------------------------------------

# Rough basic-strategy baselines (S17, ~ single hand, no count): a sanity anchor,
# not a precise model — large deviations are the signal worth investigating.
_OUTCOME_BASELINE = {"WIN": 0.43, "LOSE": 0.48, "PUSH": 0.09, "BLACKJACK": 0.045,
                     "BUST": 0.0}  # BUST is folded into LOSE here; reported separately


def summarize(path):
    """Return a dict of distributions/anomaly signals over a session DB. Pure
    read; the report CLI formats this."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        n_sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        hands = conn.execute(
            "SELECT outcome, player_total, dealer_up FROM blackjack_hands").fetchall()
    finally:
        conn.close()

    n = len(hands)
    outcomes, dealer, player = {}, {}, {}
    for h in hands:
        if h["outcome"]:
            outcomes[h["outcome"]] = outcomes.get(h["outcome"], 0) + 1
        if h["dealer_up"] is not None:
            dealer[h["dealer_up"]] = dealer.get(h["dealer_up"], 0) + 1
        if h["player_total"] is not None:
            player[h["player_total"]] = player.get(h["player_total"], 0) + 1

    # dealer up-card uniformity: a fair deal makes each rank ~1/13 (ten-values
    # 10/11..; we bucket by the HUD value 2..11 where 11 = Ace, 10 = any ten).
    # A simple chi-square against "10-value four times as likely as each other".
    dealer_chi = _dealer_chi_square(dealer)
    return {
        "sessions": n_sessions,
        "hands": n,
        "outcomes": outcomes,
        "outcome_baseline": _OUTCOME_BASELINE,
        "dealer_up": dict(sorted(dealer.items())),
        "dealer_chi_square": dealer_chi,
        "player_total": dict(sorted(player.items())),
    }


def _dealer_chi_square(dealer):
    """Chi-square of the dealer up-card distribution against a fair single deck:
    a ten-value (HUD 10) is 4x as likely as any other rank (2..9, A=11). Returns
    (chi2, dof, total) or None if too little data. High chi2 relative to dof =>
    the up-card distribution looks non-uniform (game or reader anomaly)."""
    total = sum(dealer.values())
    if total < 20:
        return None
    weights = {v: 1 for v in list(range(2, 10)) + [11]}
    weights[10] = 4
    wsum = sum(weights.values())  # 8*1 + 1(ace) + 4 = 13
    chi2 = 0.0
    for v, w in weights.items():
        exp = total * w / wsum
        obs = dealer.get(v, 0)
        chi2 += (obs - exp) ** 2 / exp
    return {"chi2": round(chi2, 2), "dof": len(weights) - 1, "total": total}
