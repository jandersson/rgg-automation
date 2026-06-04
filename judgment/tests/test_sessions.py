"""Tests for the SQLite session/hand telemetry + its summary."""
import datetime

from judgment_assist.sessions import SessionStore, summarize

T = datetime.datetime(2026, 6, 4, 12, 0, 0)


def test_start_session_and_parent_dir_creation(tmp_path):
    db = tmp_path / "nested" / "sessions.db"   # parent dir does not exist yet
    store = SessionStore(str(db))
    sid = store.start_session("blackjack", config="config/regions.json", now=T)
    assert sid == 1 and db.exists()
    store.close()


def test_record_hand_round_trips(tmp_path):
    store = SessionStore(str(tmp_path / "s.db"))
    sid = store.start_session("blackjack", now=T)
    store.record_hand(sid, 1, outcome="WIN", player_total=20, dealer_up=6,
                      running=2, true_count=0.3, cards_seen=4, now=T)
    s = summarize(str(tmp_path / "s.db"))
    assert s["sessions"] == 1 and s["hands"] == 1
    assert s["outcomes"] == {"WIN": 1}
    assert s["dealer_up"] == {6: 1} and s["player_total"] == {20: 1}


def test_summarize_empty_db(tmp_path):
    SessionStore(str(tmp_path / "e.db")).close()
    s = summarize(str(tmp_path / "e.db"))
    assert s["sessions"] == 0 and s["hands"] == 0 and s["outcomes"] == {}
    assert s["dealer_chi_square"] is None


def test_outcome_and_dealer_distributions(tmp_path):
    store = SessionStore(str(tmp_path / "d.db"))
    sid = store.start_session("blackjack", now=T)
    # 3 WIN, 2 LOSE, 1 PUSH; dealer up-cards skew to tens
    plan = (["WIN"] * 3 + ["LOSE"] * 2 + ["PUSH"])
    for i, oc in enumerate(plan):
        store.record_hand(sid, i + 1, outcome=oc, player_total=18,
                          dealer_up=10 if i % 2 == 0 else 6, now=T)
    s = summarize(str(tmp_path / "d.db"))
    assert s["hands"] == 6
    assert s["outcomes"] == {"WIN": 3, "LOSE": 2, "PUSH": 1}
    assert s["dealer_up"] == {6: 3, 10: 3}
    # <20 dealer cards -> no chi-square yet
    assert s["dealer_chi_square"] is None


def test_dealer_chi_square_flags_skew(tmp_path):
    store = SessionStore(str(tmp_path / "c.db"))
    sid = store.start_session("blackjack", now=T)
    # 40 hands, ALL dealer up-card = 5 (grossly non-uniform)
    for i in range(40):
        store.record_hand(sid, i + 1, outcome="LOSE", dealer_up=5, now=T)
    chi = summarize(str(tmp_path / "c.db"))["dealer_chi_square"]
    assert chi is not None and chi["total"] == 40
    # a degenerate single-value distribution must produce a large chi-square
    assert chi["chi2"] > chi["dof"]
