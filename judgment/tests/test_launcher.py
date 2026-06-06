"""The launcher's flag -> argv mapping (pure; no tkinter / display needed)."""
from judgment_assist.app.launcher import build_argv, DEFAULTS, terminate_all, summarize


class _FakeProc:
    def __init__(self, running=True):
        self._running, self.killed = running, False

    def poll(self):
        return None if self._running else 0

    def terminate(self):
        self.killed = True
        self._running = False


def test_single_instance_lock():
    import os
    import pytest
    if os.name != "nt":
        pytest.skip("named-mutex lock is Windows-only")
    from judgment_assist.app.launcher import acquire_single_instance
    name = "rgg-test-launcher-lock"               # unique name -> isolated from a real launcher
    first = acquire_single_instance(name)
    assert first                                  # got the lock
    assert acquire_single_instance(name) is None   # a second launcher is refused


def test_terminate_all_kills_running_only():
    running, done = _FakeProc(True), _FakeProc(False)
    assert terminate_all([running, done]) == 1     # only the live one
    assert running.killed and not done.killed


def test_summarize_is_plain_english():
    poker = summarize(_opts(game="poker", detect=True, learn=False, opp=3))
    assert "Poker advisor" in poker and "auto-detect hole cards ON" in poker
    assert "learn from corrections OFF" in poker and "3 opponents" in poker
    bj = summarize(_opts(game="blackjack", count=True, overlay=False))
    assert "Blackjack advisor" in bj and "counting ON" in bj
    assert "console only" in bj.lower()


def _opts(**over):
    o = dict(DEFAULTS)
    o.update(over)
    return o


def test_poker_defaults_emit_detection_on():
    argv = build_argv(_opts(game="poker"))
    assert argv[0] == "poker"
    assert argv[argv.index("--opp") + 1] == "3" and "--iters" in argv   # 4-handed default
    assert "--no-detect" not in argv          # detect on by default
    assert "--no-overlay" not in argv         # overlay on by default
    # no blackjack-only flags leak in
    assert "--decks" not in argv and "--count" not in argv


def test_poker_no_detect_and_console_only():
    argv = build_argv(_opts(game="poker", detect=False, overlay=False, opp=3))
    assert "--no-detect" in argv and "--no-overlay" in argv
    assert argv[argv.index("--opp") + 1] == "3"


def test_poker_passes_confirm_key():
    argv = build_argv(_opts(game="poker"))
    assert argv[argv.index("--confirm-key") + 1] == "insert"  # default
    argv2 = build_argv(_opts(game="poker", confirm_key="home"))
    assert argv2[argv2.index("--confirm-key") + 1] == "home"
    assert "--confirm-key" not in build_argv(_opts(game="blackjack"))  # poker-only


def test_poker_learning_default_on_flag_when_off():
    assert "--no-learn" not in build_argv(_opts(game="poker"))          # on by default
    assert "--no-learn" in build_argv(_opts(game="poker", learn=False))
    # blackjack never emits the poker-only learn flag
    assert "--no-learn" not in build_argv(_opts(game="blackjack", learn=False))


def test_blackjack_flags():
    argv = build_argv(_opts(game="blackjack", count=True, db=False, log="hands.csv"))
    assert argv[0] == "blackjack"
    assert "--decks" in argv and "--count" in argv and "--no-db" in argv
    assert argv[argv.index("--log") + 1] == "hands.csv"
    # poker-only flags absent
    assert "--opp" not in argv and "--iters" not in argv


def test_blackjack_db_on_omits_no_db_and_empty_log():
    argv = build_argv(_opts(game="blackjack", db=True, log="   "))
    assert "--no-db" not in argv
    assert "--log" not in argv                 # blank log is not passed


def test_common_flags_always_present():
    argv = build_argv(_opts(game="poker", interval=0.5, min_confidence=0.7, x=100, y=200))
    for flag, val in (("--config", "config/regions.json"), ("--interval", "0.5"),
                      ("--min-confidence", "0.7"), ("--x", "100"), ("--y", "200")):
        assert argv[argv.index(flag) + 1] == val


def _gui():
    """Build a LauncherApp on a hidden root, or skip if there's no display."""
    import pytest
    tk = pytest.importorskip("tkinter")
    from judgment_assist.app.launcher import LauncherApp
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display for tkinter")
    root.withdraw()
    return root, LauncherApp(root)


def test_launcher_has_play_and_review_tabs():
    root, app = _gui()
    try:
        assert [app.nb.tab(t, "text") for t in app.nb.tabs()] == ["Play", "Review"]
    finally:
        root.destroy()


def test_review_tab_lists_live_banked_cards_newest_first():
    root, app = _gui()
    try:
        app._clear_review()                        # drop any on-disk history -> isolate
        class _Adv:                                # stands in for a running advisor
            banked = [{"time": "02:55:24", "slot": "H0", "card": "Ac", "path": None},
                      {"time": "02:55:25", "slot": "H1", "card": "Ts", "path": None}]
        app._sess = {"advisor": _Adv()}
        app._review_seen = 0
        app._refresh_review()
        rows = [app.review_tree.item(i, "values") for i in app.review_tree.get_children()]
        assert rows == [("Today 02:55", "02:55:25", "Hole 2", "Ts"),
                        ("Today 02:55", "02:55:24", "Hole 1", "Ac")]   # newest on top
        assert app._review_count.cget("text") == "2 banked"
        app._refresh_review()                      # idempotent: no duplicate rows
        assert len(app.review_tree.get_children()) == 2
        app._clear_review()                        # clears the list only
        assert app.review_tree.get_children() == ()
    finally:
        app._sess = None
        root.destroy()


def test_review_tab_loads_past_sessions_from_disk():
    """The tab pre-loads every past session's banked crops from data/poker_cards,
    not just the running session — that's the whole point of disk-backing it."""
    import json
    from judgment_assist.app.launcher import ROOT
    lp = ROOT / "data" / "poker_cards" / "labels.json"
    if not lp.exists() or not any(
            k.startswith("live") for k in json.load(open(lp, encoding="utf-8"))):
        import pytest
        pytest.skip("no banked 'live*' history on disk to load")
    root, app = _gui()
    try:
        assert len(app.review_tree.get_children()) > 0     # loaded at build time
        app._clear_review()
        assert app.review_tree.get_children() == ()
        app._load_review_history()                          # Refresh reloads them
        assert len(app.review_tree.get_children()) > 0
    finally:
        root.destroy()
