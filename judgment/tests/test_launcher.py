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


_BASE_ROOT = None


def _gui():
    """Build a LauncherApp on a hidden Toplevel, or skip if there's no display.
    Reuses ONE base Tk() across tests — repeatedly creating/destroying Tk roots in a
    process is flaky (intermittent 'no display'); a single root + per-test Toplevel
    is the supported pattern."""
    global _BASE_ROOT
    import pytest
    tk = pytest.importorskip("tkinter")
    from judgment_assist.app.launcher import LauncherApp
    if _BASE_ROOT is None:
        try:
            _BASE_ROOT = tk.Tk()
        except tk.TclError:
            pytest.skip("no display for tkinter")
        _BASE_ROOT.withdraw()
    top = tk.Toplevel(_BASE_ROOT)
    top.withdraw()
    return top, LauncherApp(top)


def _crop():
    np = __import__("numpy")
    return np.full((400, 278, 3), 200, "uint8")


def _temp_lib(app, tmp):
    """Point the Labels tab at an isolated library so edit tests don't touch real data."""
    from judgment_assist.vision.poker_cards import LabelLibrary
    app._lib = LabelLibrary(str(tmp))
    app._reload_labels_list()


def test_launcher_has_play_and_labels_tabs():
    root, app = _gui()
    try:
        assert [app.nb.tab(t, "text") for t in app.nb.tabs()] == ["Play", "Labels"]
    finally:
        root.destroy()


def test_labels_tab_loads_whole_library_from_disk():
    """The tab lists every crop the reader learns from (seeds + sessions), not just
    the running session — that's the point of backing it with LabelLibrary."""
    import json
    from judgment_assist.app.launcher import ROOT
    lp = ROOT / "data" / "poker_cards" / "labels.json"
    if not lp.exists() or not json.load(open(lp, encoding="utf-8")):
        import pytest
        pytest.skip("no label library on disk to load")
    root, app = _gui()
    try:
        assert len(app.labels_tree.get_children()) > 0     # loaded at build time
    finally:
        root.destroy()


def test_labels_tab_live_bank_appends_labeled_row(tmp_path):
    import pytest
    pytest.importorskip("cv2")
    root, app = _gui()
    try:
        _temp_lib(app, tmp_path)                   # empty isolated library
        assert app.labels_tree.get_children() == ()
        class _Adv:
            banked = [{"time": "02:55:24", "slot": "H0", "card": "Ac",
                       "path": str(tmp_path / "live9_1_H0.png")}]
        app._sess = {"advisor": _Adv()}
        app._live_seen = 0
        app._append_live_banks()
        rows = [app.labels_tree.item(i, "values") for i in app.labels_tree.get_children()]
        assert rows == [("02:55:24", "Session", "Hole 1", "Ac")]
        app._append_live_banks()                   # idempotent
        assert len(app.labels_tree.get_children()) == 1
    finally:
        app._sess = None
        root.destroy()


def _one_card_frame():
    """A 1080p felt frame with a single face-up card at hole slot 0 (real ROIs)."""
    import json
    np = __import__("numpy")
    from judgment_assist.app.launcher import ROOT
    poker = json.load(open(ROOT / "config" / "regions.json", encoding="utf-8"))["poker"]
    hx, hy = poker["hole"][0]
    frame = np.full((1080, 1920, 3), (70, 120, 40), np.uint8)
    frame[hy - 12:hy + 388, hx:hx + 278] = 235
    return frame, poker


def test_capture_from_game_adds_unlabeled_crops(tmp_path):
    import pytest
    pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    frame, poker = _one_card_frame()
    root, app = _gui()
    try:
        _temp_lib(app, tmp_path)
        app._sess = {"grab": None, "cfg": {"poker": poker},
                     "grab_frame": lambda g, c: frame,
                     "advisor": type("A", (), {"banked": []})()}
        app._capture_from_game()
        caps = [k for k in app._lib.labels if k.startswith("cap")]
        assert len(caps) == 1 and app._lib.labels[caps[0]] == {}   # captured, unlabeled
        assert app._labels_needs == 1
        app._capture_from_game()                       # same frame -> dedup, no new crop
        assert sum(k.startswith("cap") for k in app._lib.labels) == 1
    finally:
        app._sess = None
        root.destroy()


def test_import_frames_adds_unlabeled_crops(tmp_path):
    import pytest
    pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    frame, _ = _one_card_frame()
    fp = tmp_path / "shotA.png"
    cv2.imwrite(str(fp), frame)
    root, app = _gui()
    try:
        _temp_lib(app, tmp_path)
        app._import_frames([str(fp)])
        imps = [k for k in app._lib.labels if k.startswith("imp_")]
        assert imps and all(app._lib.labels[k] == {} for k in imps)   # unlabeled
        assert app._labels_needs == len(imps)
    finally:
        root.destroy()


def test_labels_tab_fix_skip_delete(tmp_path):
    import os
    import pytest
    pytest.importorskip("cv2")
    root, app = _gui()
    try:
        _temp_lib(app, tmp_path)
        key, path = app._lib.add(_crop(), "cap1_1", "H0")    # captured, unlabeled
        app._reload_labels_list()
        assert app._labels_needs == 1                        # flagged as needing a label
        app.labels_tree.selection_set(path)
        app._edit_rank.set("A")
        app._edit_suit.set("h")
        app._save_label()
        assert app._lib.labels[key] == {"rank": "A", "suit": "hearts"}
        assert app._labels_needs == 0
        app.labels_tree.selection_set(path)
        app._skip_label()
        assert app._lib.labels[key] == {"_skip": True}
        app.labels_tree.selection_set(path)
        app._delete_label()
        assert key not in app._lib.labels and not os.path.exists(path)
        assert app.labels_tree.get_children() == ()
    finally:
        root.destroy()
