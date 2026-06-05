"""Hole-card reader: the reliable colour signal + exemplar matching.

Construction loads the labeled corner library (gitignored data), so these tests
exercise the pure pieces and recognize() with injected exemplars instead."""
import json

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from judgment_assist.vision import poker_cards as PC
from judgment_assist.cards import RANK_TO_INT, SUIT_TO_INT


def _suit_region(red):
    """A 44x52 suit crop: white card with a coloured pip block."""
    reg = np.full((44, 52, 3), 235, np.uint8)
    reg[10:34, 14:38] = (40, 40, 180) if red else (50, 50, 50)   # BGR red vs black
    return reg


def test_is_red_distinguishes_colour():
    assert PC._is_red(_suit_region(red=True)) is True
    assert PC._is_red(_suit_region(red=False)) is False


def test_ink_bbox_tightens_to_glyph():
    g = np.full((60, 60), 240, np.uint8)
    g[20:40, 25:35] = 30                       # a dark blob in the middle
    box = PC._ink_bbox(g)
    assert box.shape[0] <= 22 and box.shape[1] <= 12   # cropped to the ink


def _corner_with(rank_char, red):
    """A canonical-size corner: rank glyph on top, coloured suit pip below."""
    w, h = PC._CORNER
    c = np.full((h, w, 3), 235, np.uint8)
    cv2.putText(c, rank_char, (6, 48), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (30, 30, 30), 3)
    y0, y1, x0, x1 = PC._SUIT_BOX
    c[y0 + 4:y0 + 28, x0 + 8:x0 + 32] = (40, 40, 180) if red else (50, 50, 50)
    return c


def _reader_with(rank_chars):
    """Build a reader without touching disk: inject exemplars for the given
    ranks (red->hearts, black->clubs) from synthetic corners."""
    r = PC.HoleCardReader.__new__(PC.HoleCardReader)
    r._rank_ex, r._suit_ex = [], {True: [], False: []}
    for ch in rank_chars:
        rg, sg = PC.HoleCardReader._regions(_corner_with(ch, red=False))
        r._rank_ex.append((RANK_TO_INT[ch], PC._ink_bbox(rg)))
    # one red (hearts) and one black (clubs) suit exemplar
    for red, suit in ((True, "h"), (False, "c")):
        _, sg = PC.HoleCardReader._regions(_corner_with("A", red=red))
        r._suit_ex[red].append((SUIT_TO_INT[suit], PC._ink_bbox(cv2.cvtColor(sg, cv2.COLOR_BGR2GRAY))))
    return r


def test_recognize_picks_matching_rank_and_colour():
    r = _reader_with(["A", "2", "9"])
    (rank, suit), info = r.recognize(_corner_with("9", red=True))
    assert rank == RANK_TO_INT["9"]            # matched the right rank exemplar
    assert info["color"] == "red" and suit == SUIT_TO_INT["h"]   # colour-gated suit
    (rank2, suit2), info2 = r.recognize(_corner_with("A", red=False))
    assert rank2 == RANK_TO_INT["A"] and info2["color"] == "black"
    assert suit2 == SUIT_TO_INT["c"]


def test_add_exemplar_grows_library_and_recognizes():
    r = PC.HoleCardReader.__new__(PC.HoleCardReader)
    r._rank_ex, r._suit_ex = [], {True: [], False: []}
    r.add_exemplar(_corner_with("2", red=False), RANK_TO_INT["2"], SUIT_TO_INT["c"])
    r.add_exemplar(_corner_with("9", red=True), RANK_TO_INT["9"], SUIT_TO_INT["h"])
    assert len(r._rank_ex) == 2 and len(r._suit_ex[True]) == 1
    (rank, _), info = r.recognize(_corner_with("9", red=True))
    assert rank == RANK_TO_INT["9"] and info["color"] == "red"


def test_training_writer_saves_dedups_persists(tmp_path):
    w = PC.TrainingWriter(str(tmp_path))
    corner = _corner_with("A", red=True)
    assert w.save(corner, RANK_TO_INT["A"], SUIT_TO_INT["h"], "H0") is True
    labels = json.load(open(tmp_path / "labels.json"))
    (key, val), = labels.items()
    assert val == {"rank": "A", "suit": "hearts"} and key.endswith("#H0")
    assert len(list(tmp_path.glob("*_H0.png"))) == 1
    assert w.save(corner, RANK_TO_INT["A"], SUIT_TO_INT["h"], "H0") is False   # dedup
    # a fresh writer loads the saved label and dedups a near-identical corner
    w2 = PC.TrainingWriter(str(tmp_path))
    assert len(w2.labels) == 1
    assert w2.save(corner, RANK_TO_INT["A"], SUIT_TO_INT["h"], "H0") is False
