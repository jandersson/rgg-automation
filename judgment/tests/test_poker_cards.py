"""Whole-card hole-card reader: colour signal, colour-gated SVM, learning, writer.

Construction loads the labeled crop library (gitignored data), so these tests
build readers from injected synthetic whole-card crops instead."""
import json
import threading

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")
pytest.importorskip("sklearn")

from judgment_assist.vision import poker_cards as PC
from judgment_assist.cards import RANK_TO_INT, SUIT_TO_INT


def _whole(rank_char, red):
    """A synthetic whole hole-card crop: rank glyph top-left, coloured suit pip in
    the colour-test region, a centre blob for body."""
    w, h = 278, 400
    c = np.full((h, w, 3), 235, np.uint8)
    cv2.putText(c, rank_char, (8, 78), cv2.FONT_HERSHEY_SIMPLEX, 2.2, (30, 30, 30), 5)
    y0, y1, x0, x1 = PC._HOLE_SUIT
    c[y0:y1, x0 + 4:x1 - 4] = (40, 40, 180) if red else (45, 45, 45)   # BGR
    cv2.circle(c, (w // 2, h // 2), 45, (70, 70, 70), -1)
    return c


def test_is_red_distinguishes_colour():
    assert PC._is_red(_whole("A", red=True)[PC._HOLE_SUIT[0]:PC._HOLE_SUIT[1],
                                            PC._HOLE_SUIT[2]:PC._HOLE_SUIT[3]]) is True
    assert PC._is_red(_whole("A", red=False)[PC._HOLE_SUIT[0]:PC._HOLE_SUIT[1],
                                             PC._HOLE_SUIT[2]:PC._HOLE_SUIT[3]]) is False


def _reader(samples):
    """A reader built from (whole_bgr, rank_int, suit_int) without touching disk."""
    r = PC.HoleCardReader.__new__(PC.HoleCardReader)
    r._hog, r._lock = PC._hog(), threading.Lock()
    r._X = [PC._features(w, r._hog) for w, _, _ in samples]
    r._rank = [ri for _, ri, _ in samples]
    r._suit = [si for _, _, si in samples]
    r._rank_clf = r._suit_clf = None
    r._fit()
    return r


def _base_samples():
    # two ranks, all four suits present so the suit gate has red + black choices
    s = []
    for _ in range(2):
        s += [(_whole("A", True), RANK_TO_INT["A"], SUIT_TO_INT["h"]),
              (_whole("A", True), RANK_TO_INT["A"], SUIT_TO_INT["d"]),
              (_whole("9", False), RANK_TO_INT["9"], SUIT_TO_INT["c"]),
              (_whole("9", False), RANK_TO_INT["9"], SUIT_TO_INT["s"])]
    return s


def test_recognize_colour_gated_suit_matches_colour():
    r = _reader(_base_samples())
    (rank, suit), info = r.recognize(_whole("A", red=True))
    assert info["color"] == "red" and suit in PC._RED          # suit can't contradict colour
    (_, suit2), info2 = r.recognize(_whole("9", red=False))
    assert info2["color"] == "black" and suit2 not in PC._RED


def test_add_exemplar_grows_and_refits():
    r = _reader(_base_samples())
    n = len(r._X)
    r.add_exemplar(_whole("5", red=True), RANK_TO_INT["5"], SUIT_TO_INT["h"])
    assert len(r._X) == n + 1
    (_, suit), info = r.recognize(_whole("5", red=True))     # still runs, colour right
    assert info["color"] == "red" and suit in PC._RED


def test_training_writer_saves_dedups_persists(tmp_path):
    w = PC.TrainingWriter(str(tmp_path))
    card = _whole("A", red=True)
    assert w.save(card, RANK_TO_INT["A"], SUIT_TO_INT["h"], "H0") is True
    (key, val), = json.load(open(tmp_path / "labels.json")).items()
    assert val == {"rank": "A", "suit": "hearts"} and key.endswith("#H0")
    saved_png = next(tmp_path.glob("*_H0.png"))
    assert cv2.imread(str(saved_png)).shape[:2] == (PC._STORE[1], PC._STORE[0])   # stored whole-card
    assert w.save(card, RANK_TO_INT["A"], SUIT_TO_INT["h"], "H0") is False        # dedup
    assert len(PC.TrainingWriter(str(tmp_path)).labels) == 1                       # persisted


def test_recrop_library_to_whole(tmp_path):
    import os
    cfg = json.load(open("config/regions.json", encoding="utf-8"))["poker"]
    hx, hy = cfg["hole"][0]
    frame = np.full((1080, 1920, 3), (70, 120, 40), np.uint8)
    frame[hy - 12:hy + 388, hx:hx + 278] = 235                 # a white card at hole 0
    frames = tmp_path / "frames"; frames.mkdir()
    cv2.imwrite(str(frames / "f1.png"), frame)
    cards = tmp_path / "cards"; cards.mkdir()
    (cards / "labels.json").write_text(json.dumps({"f1#H0": {"rank": "A", "suit": "hearts"}}))
    done, missing = PC.recrop_library_to_whole(str(cards), str(frames))
    assert done == 1 and missing == 0
    crop = cv2.imread(str(cards / "f1_H0.png"))
    assert crop.shape[:2] == (PC._STORE[1], PC._STORE[0])      # whole-card sized
