"""Smoke test for the corner-crop harvester. Synthetic frame (no game capture),
skipped if numpy/opencv aren't present. Real-frame coverage (300 crops from the
72 in_hand frames) is validated against data/screens, not here.
"""
import glob
import json
import os

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from judgment_assist.capture import harvest

H, W = 1080, 1920
FELT = (70, 120, 40)


def _frame_with_card():
    f = np.zeros((H, W, 3), np.uint8)
    f[:] = FELT
    # a solid cream card with a dark "7" rank glyph in the corner
    f[350:520, 800:910] = (230, 235, 235)
    cv2.putText(f, "7", (812, 392), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (20, 20, 20), 2)
    return f


def test_harvest_writes_crops_sheet_and_index(tmp_path):
    src = tmp_path / "screens"; src.mkdir()
    cv2.imwrite(str(src / "frame_00000.png"), _frame_with_card())
    out = tmp_path / "crops"

    harvest.main(["--src", str(src), "--only", "", "--out", str(out)])

    crops = glob.glob(str(out / "frame_00000__c*i*.png"))
    assert crops, "expected at least one corner crop"
    assert (out / "_contact.png").exists()
    index = json.load(open(out / "_index.json", encoding="utf-8"))
    assert len(index) == len(crops)
    # every indexed crop actually exists on disk
    for name in index.values():
        assert os.path.exists(out / name)


def test_only_filter_needs_manifest(tmp_path):
    src = tmp_path / "screens"; src.mkdir()
    cv2.imwrite(str(src / "frame_00000.png"), _frame_with_card())
    # --only in_hand with no manifest present should refuse, not silently harvest all
    with pytest.raises(SystemExit):
        harvest.main(["--src", str(src), "--only", "in_hand",
                      "--states", str(tmp_path / "nope.json"),
                      "--out", str(tmp_path / "crops")])
