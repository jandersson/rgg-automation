"""Tests for the template-matching recogniser, using synthetic glyph images so
they run without the game. Skipped automatically if numpy/opencv aren't present.
"""
import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from judgment_assist.vision.recognizer import CardRecognizer
from judgment_assist.cards import RANK_TO_INT, parse_card


def _glyph(text):
    img = np.zeros((48, 36, 3), dtype=np.uint8)
    cv2.putText(img, text, (1, 38), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
    return img


def _write(d, name, img):
    cv2.imwrite(str(d / f"{name}.png"), img)


def test_rank_mode_recognizes_each_rank(tmp_path):
    d = tmp_path / "t"; d.mkdir()
    names = ["A", "K", "Q", "J", "T", "9", "5", "2"]
    imgs = {n: _glyph(n) for n in names}
    for n, g in imgs.items():
        _write(d, n, g)
    rec = CardRecognizer(str(d), mode="rank", min_confidence=0.5)
    assert len(rec.templates) == len(names)
    for n in names:
        label, score = rec.recognize(imgs[n])
        assert label == RANK_TO_INT[n], (n, label, score)
        assert score > 0.99


def test_card_mode_returns_tuples_and_ignores_rank_files(tmp_path):
    d = tmp_path / "t"; d.mkdir()
    cards = ["As", "Kd", "9c", "Th"]
    imgs = {c: _glyph(c) for c in cards}
    for c, g in imgs.items():
        _write(d, c, g)
    _write(d, "A", _glyph("A"))  # stray rank-mode file: card mode must ignore it
    rec = CardRecognizer(str(d), mode="card", min_confidence=0.5)
    assert len(rec.templates) == len(cards)
    for c in cards:
        label, _ = rec.recognize(imgs[c])
        assert label == parse_card(c)


def test_recognize_many(tmp_path):
    d = tmp_path / "t"; d.mkdir()
    for n in ["A", "K", "9"]:
        _write(d, n, _glyph(n))
    rec = CardRecognizer(str(d), mode="rank", min_confidence=0.5)
    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    frame[10:58, 10:46] = _glyph("A")
    frame[100:148, 10:46] = _glyph("9")
    labels = rec.recognize_many(frame, [[10, 10, 36, 48], [10, 100, 36, 48]])
    assert labels == [RANK_TO_INT["A"], RANK_TO_INT["9"]]


def test_below_confidence_returns_none(tmp_path):
    d = tmp_path / "t"; d.mkdir()
    for n in ["A", "K", "9"]:
        _write(d, n, _glyph(n))
    rec = CardRecognizer(str(d), mode="rank", min_confidence=0.95)
    # a rank not in the library shouldn't match anything strongly
    label, score = rec.recognize(_glyph("5"))
    assert label is None, (label, score)


def test_empty_library_raises(tmp_path):
    d = tmp_path / "empty"; d.mkdir()
    with pytest.raises(RuntimeError):
        CardRecognizer(str(d), mode="rank")
