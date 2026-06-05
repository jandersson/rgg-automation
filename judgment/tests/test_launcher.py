"""The launcher's flag -> argv mapping (pure; no tkinter / display needed)."""
from judgment_assist.app.launcher import build_argv, DEFAULTS


def _opts(**over):
    o = dict(DEFAULTS)
    o.update(over)
    return o


def test_poker_defaults_emit_detection_on():
    argv = build_argv(_opts(game="poker"))
    assert argv[0] == "poker"
    assert "--opp" in argv and "2" in argv and "--iters" in argv
    assert "--no-detect" not in argv          # detect on by default
    assert "--no-overlay" not in argv         # overlay on by default
    # no blackjack-only flags leak in
    assert "--decks" not in argv and "--count" not in argv


def test_poker_no_detect_and_console_only():
    argv = build_argv(_opts(game="poker", detect=False, overlay=False, opp=3))
    assert "--no-detect" in argv and "--no-overlay" in argv
    assert argv[argv.index("--opp") + 1] == "3"


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
