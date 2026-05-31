"""Pipeline test for the rank reader: a synthetic cream-card-on-felt frame with a
dark rank glyph at the corner is located, scanned, and read back. Skipped if
numpy/opencv aren't present. Real-frame behaviour is validated separately against
data/screens (e.g. 00931 8+J, 00413 10+3).
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from judgment_assist.vision.reader import read_ranks, read_cluster_ranks
from judgment_assist.vision.recognizer import CardRecognizer
from judgment_assist.cards import RANK_TO_INT

H, W = 1080, 1920
FELT = (70, 120, 40)
CREAM = (230, 235, 235)


def _frame_with_card(glyph="7", gx=812, gy=398):
    f = np.zeros((H, W, 3), np.uint8)
    f[:] = FELT
    f[360:610, 800:950] = CREAM                     # a card in the play area
    cv2.putText(f, glyph, (gx, gy), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (25, 25, 25), 2)
    return f


def _templates(tmp_path, names):
    d = tmp_path / "t"; d.mkdir()
    # crop each template from the SAME rendering so it self-matches under scan
    for n in names:
        f = _frame_with_card(n)
        cv2.imwrite(str(d / f"{n}.png"), f[378:412, 806:846])
    return CardRecognizer(str(d), mode="rank", min_confidence=0.5)


def test_read_ranks_locates_and_reads_a_card(tmp_path):
    rec = _templates(tmp_path, ["7", "A", "K"])
    ranks = read_ranks(_frame_with_card("7"), rec, min_score=0.6)
    assert RANK_TO_INT["7"] in ranks, ranks


def test_blank_felt_reads_nothing(tmp_path):
    rec = _templates(tmp_path, ["7", "A", "K"])
    blank = np.zeros((H, W, 3), np.uint8); blank[:] = FELT
    assert read_ranks(blank, rec) == []
