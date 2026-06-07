import json

import pytest

from judgment_assist.app.shogi_labels_tab import piece_code


def test_piece_code_owner_and_promotion():
    assert piece_code("Pawn", yours=True, promoted=False) == "P"
    assert piece_code("Pawn", yours=False, promoted=False) == "p"
    assert piece_code("Rook", yours=False, promoted=True) == "+r"     # opponent Dragon
    assert piece_code("Bishop", yours=False, promoted=True) == "+b"   # opponent Horse
    assert piece_code("Silver", yours=True, promoted=True) == "+S"


def test_piece_code_gold_and_king_never_promote():
    assert piece_code("Gold", yours=True, promoted=True) == "G"
    assert piece_code("King", yours=False, promoted=True) == "k"


def test_save_and_remove_template_round_trip(tmp_path):
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    from judgment_assist.vision.shogi_pieces import (
        MANIFEST, remove_template, save_template_from_crop)

    crop = np.full((90, 80, 3), 100, np.uint8)
    save_template_from_crop(crop, "+r", str(tmp_path))
    man = json.load(open(tmp_path / MANIFEST, encoding="utf-8"))
    assert "+r" in man.values()
    stem = next(s for s, c in man.items() if c == "+r")
    assert (tmp_path / stem).exists()

    assert remove_template("+r", str(tmp_path)) is True
    assert "+r" not in json.load(open(tmp_path / MANIFEST, encoding="utf-8")).values()
    assert not (tmp_path / stem).exists()
    assert remove_template("+r", str(tmp_path)) is False        # already gone
