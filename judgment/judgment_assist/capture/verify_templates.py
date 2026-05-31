"""Round-trip check for the blackjack rank-template library.

The discipline rule for this project: **never commit a template without a real
programmatic round-trip check on real frames.** This tool is that check. Given

  * a templates dir (``data/templates/<rank>.png`` — what ``CardRecognizer`` loads),
  * the harvested crops (``data/crops``, from ``harvest.py``), and
  * a ground-truth labels file mapping crop filename -> rank,

it loads ``CardRecognizer(mode="rank")`` and recognises every labeled crop, then
reports accuracy, every misread (file, expected, got, score), and a confusion
matrix. It exits non-zero if any labeled crop misreads or any of the 13 ranks
lacks a template — so it can gate a commit.

Build the labels file by skimming ``data/crops/_contact.png`` (each tile is
captioned with its index; ``_index.json`` maps index -> crop filename). Label
format is either::

    {"frame_00002__c0i0.png": "6", "frame_00029__c0i1.png": "9", ...}

(crop filename -> rank) or, more convenient off the contact sheet, by tile index::

    {"by_index": {"0": "6", "1": "6", "14": "9", ...}}

    uv run python -m judgment_assist.capture.verify_templates \
        --labels data/crops/_labels.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

from ..cards import RANK_TO_INT, INT_TO_RANK


ALL_RANKS = list(RANK_TO_INT)  # '2'..'9','T','J','Q','K','A'


def _load_labels(path, crops_dir):
    """Return ``{crop_filename: 'RANK'}`` from either label form."""
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    if "by_index" in raw:
        idx_path = os.path.join(crops_dir, "_index.json")
        if not os.path.exists(idx_path):
            raise SystemExit(f"by_index labels need {idx_path} (run harvest first)")
        with open(idx_path, encoding="utf-8") as fh:
            index = json.load(fh)
        out = {}
        for k, rank in raw["by_index"].items():
            fn = index.get(str(k))
            if fn is None:
                raise SystemExit(f"tile index {k!r} not in {idx_path}")
            out[fn] = rank
        return out
    return raw


def run(a):
    import cv2  # noqa: F401  (imported so a missing cv2 fails loud, like siblings)
    from ..vision.recognizer import CardRecognizer

    labels = _load_labels(a.labels, a.crops)
    for fn, rank in labels.items():
        if rank.strip().upper() not in RANK_TO_INT:
            raise SystemExit(f"label for {fn!r} is not a rank: {rank!r}")

    rec = CardRecognizer(a.templates, mode="rank", min_confidence=a.min_confidence)
    have = {INT_TO_RANK[r] for r in rec.templates}
    missing = [r for r in ALL_RANKS if r not in have]

    total = correct = below = 0
    misreads = []
    confusion = defaultdict(lambda: defaultdict(int))  # expected -> got -> n
    for fn, rank in sorted(labels.items()):
        path = os.path.join(a.crops, fn)
        img = cv2.imread(path)
        if img is None:
            print(f"  WARN: missing crop {fn}")
            continue
        total += 1
        label, score = rec.recognize(img)
        got = INT_TO_RANK[label] if label is not None else "?"
        confusion[rank][got] += 1
        if label is None:
            below += 1
            misreads.append((fn, rank, "(below-conf)", score))
        elif label == RANK_TO_INT[rank]:
            correct += 1
        else:
            misreads.append((fn, rank, got, score))

    print(f"templates : {a.templates}  ({len(rec.templates)}/13 ranks present)")
    if missing:
        print(f"  MISSING ranks: {' '.join(missing)}")
    print(f"labeled crops: {total}")
    if total:
        print(f"  correct    : {correct} ({100*correct/total:.1f}%)")
        print(f"  misread    : {len(misreads) - below}")
        print(f"  below-conf : {below}")
    if misreads:
        print("misreads (file expected->got @score):")
        for fn, exp, got, score in misreads:
            print(f"  {fn:32} {exp} -> {got}  @ {score:.3f}")

    print("confusion (expected: got=n ...):")
    for exp in ALL_RANKS:
        if exp in confusion:
            row = " ".join(f"{g}={n}" for g, n in sorted(confusion[exp].items()))
            print(f"  {exp}: {row}")

    ok = (not missing) and (total > 0) and (len(misreads) == 0)
    print("\nROUND-TRIP:", "PASS" if ok else "FAIL")
    if not ok:
        sys.exit(1)


def main(argv=None):
    p = argparse.ArgumentParser(prog="judgment-assist verify-templates")
    p.add_argument("--labels", default="data/crops/_labels.json",
                   help="ground-truth crop->rank labels (filename or by_index form)")
    p.add_argument("--templates", default="data/templates")
    p.add_argument("--crops", default="data/crops")
    p.add_argument("--min-confidence", dest="min_confidence", type=float, default=0.6)
    run(p.parse_args(argv))


if __name__ == "__main__":
    main()
