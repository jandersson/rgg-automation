import glob
import json

import pytest


def test_read_hand_finds_a_pasted_piece():
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    from judgment_assist.vision.shogi_hand import read_hand

    tmpl = np.zeros((90, 80, 3), np.uint8); tmpl[20:70, 30:50] = 255   # distinct glyph
    natives = {"P": cv2.cvtColor(tmpl, cv2.COLOR_BGR2GRAY)}
    tray = np.full((400, 300, 3), 180, np.uint8)
    tray[40:130, 30:110] = tmpl                                       # paste one piece
    assert read_hand(tray, [0, 0, 300, 400], natives, threshold=0.6) == {"P": 1}


def test_read_hand_empty_tray_is_empty():
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    from judgment_assist.vision.shogi_hand import read_hand
    tmpl = np.zeros((90, 80, 3), np.uint8); tmpl[20:70, 30:50] = 255
    natives = {"P": cv2.cvtColor(tmpl, cv2.COLOR_BGR2GRAY)}
    blank = np.full((400, 300, 3), 180, np.uint8)
    assert read_hand(blank, [0, 0, 300, 400], natives, threshold=0.6) == {}


def test_read_hands_runs_on_a_real_frame():
    """Smoke test on real pixels: read_hands returns a sane {code: count>=1} dict
    (the synthetic tests cover the actual finding). Game state varies frame to
    frame, so we don't assert a specific captured piece."""
    pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    from judgment_assist.app.launcher import ROOT
    from judgment_assist.vision.shogi_hand import read_hands
    frames = sorted(glob.glob(str(ROOT / "data" / "shogi" / "frames" / "*.png")))
    reg = ROOT / "config" / "regions.json"
    tdir = ROOT / "data" / "shogi" / "templates"
    if not frames or not reg.exists() or not (tdir / "manifest.json").exists():
        pytest.skip("need captured frames + templates")
    sh = json.load(open(reg, encoding="utf-8")).get("shogi", {})
    if "hand_you" not in sh or "hand_opp" not in sh:
        pytest.skip("komadai ROIs not calibrated")
    hands = read_hands(cv2.imread(frames[-1]), sh["hand_you"], sh["hand_opp"], str(tdir))
    assert isinstance(hands, dict)
    for code, n in hands.items():
        assert n >= 1 and code.lstrip("+").upper() in "PLNSGBRK"
