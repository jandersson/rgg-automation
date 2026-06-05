"""Best-effort hole-card recognition for the semi-auto poker overlay.

This is the one place the project reads card *content*, and it is deliberately
**advisory, not authoritative**: the hero confirms/corrects it. But it's a lot
better than corners — measured leave-one-out on the labeled cards:

* **whole-card HOG + LinearSVC**: rank ~74% / suit ~84% on hole cards (vs the old
  corner template's ~47% rank), beating POKER.md's documented 80% whole-card
  result. Whole cards beat corners because the corner crop is contaminated by the
  centre pip and the neighbour card's index; a hole card is clean and separated.
* **suit colour** red/black ≈ 95% (ink-pixel redness) — shown as a reliable hint.

The reader trains two LinearSVCs on HOG features of the labeled whole-card crops
in ``data/poker_cards`` and **refits when you confirm/correct a hand**, so it
improves as you play. Card geometry (whole-card ROIs) is below; the crops are
re-cropped from the source frames by :func:`recrop_library_to_whole`.
"""
from __future__ import annotations

import glob
import json
import os

try:
    import cv2
    import numpy as np
    _HAVE = True
except Exception:  # pragma: no cover
    _HAVE = False

from ..cards import RANK_TO_INT, SUIT_TO_INT, INT_TO_RANK

# Whole-card ROIs relative to a slot's corner anchor: (dx, dy, w, h). Hole cards
# render bigger than the (smaller) board cards; both are normalised to the HOG
# window so they're comparable. Measured from real frames (white-blob bbox).
_HOLE_CARD = (0, -12, 278, 400)
_BOARD_CARD = (-15, 8, 250, 300)
_STORE = (137, 196)                # stored crop size (BGR, human-reviewable)
_HOG_WIN = (64, 96)                # HOG / classifier input size
# Suit pip box for the colour hint, within a NATIVE hole whole-card crop (the ROI
# starts 12px above the corner anchor, so the corner's suit box shifts down 12).
_HOLE_SUIT = (68, 112, 0, 52)      # (y0, y1, x0, x1)
_SUIT_LETTER = {"clubs": "c", "diamonds": "d", "hearts": "h", "spades": "s"}
_SUIT_NAME = {SUIT_TO_INT[v]: k for k, v in _SUIT_LETTER.items()}   # int -> "clubs"
_RED = {SUIT_TO_INT["h"], SUIT_TO_INT["d"]}


def whole_roi(anchor, slot):
    """(left, top, w, h) of the whole-card crop for a slot ('H0'/'B3'...)."""
    dx, dy, w, h = _HOLE_CARD if slot.startswith("H") else _BOARD_CARD
    return (anchor[0] + dx, anchor[1] + dy, w, h)


def _hog():
    return cv2.HOGDescriptor(_HOG_WIN, (16, 16), (8, 8), (8, 8), 9)


def _features(card_bgr, hog):
    """HOG feature vector of a whole-card crop (size-normalised to _HOG_WIN)."""
    g = cv2.cvtColor(cv2.resize(card_bgr, _HOG_WIN), cv2.COLOR_BGR2GRAY)
    return hog.compute(g).ravel()


def _is_red(suit_bgr):
    """True if this suit pip is red (hearts/diamonds) by ink-pixel redness — the
    average over the DARK pixels only (the white card body dilutes a whole-region
    mean). The most reliable single signal, used for the colour hint."""
    g = cv2.cvtColor(suit_bgr, cv2.COLOR_BGR2GRAY)
    ink = g < (int(g.mean()) - 10)
    if ink.sum() < 5:
        return False
    b, gr, r = (suit_bgr[..., 0].astype(int), suit_bgr[..., 1].astype(int),
                suit_bgr[..., 2].astype(int))
    return float((r - (gr + b) / 2)[ink].mean()) > 10


class HoleCardReader:
    """Whole-card rank+suit recognition, trained on the labeled crop library and
    refit on the fly as the hero confirms/corrects hands. Advisory — pair with
    human correction."""

    def __init__(self, card_dir="data/poker_cards"):
        if not _HAVE:
            raise RuntimeError("card reader needs numpy + opencv")
        import threading
        labels_path = os.path.join(card_dir, "labels.json")
        if not os.path.exists(labels_path):
            raise RuntimeError(
                f"no labeled crops in {card_dir!r} — the hole-card reader needs "
                f"labels.json + the whole-card PNGs (label --poker, then re-crop)")
        labels = json.load(open(labels_path, encoding="utf-8"))
        self._hog = _hog()
        self._lock = threading.Lock()
        self._X, self._rank, self._suit = [], [], []
        for key, lab in labels.items():
            if lab.get("_skip") or "rank" not in lab:
                continue
            frame, slot = key.split("#")
            crop = cv2.imread(os.path.join(card_dir, f"{frame}_{slot}.png"))
            if crop is None:
                continue
            self._X.append(_features(crop, self._hog))
            self._rank.append(RANK_TO_INT[lab["rank"]])
            self._suit.append(SUIT_TO_INT[_SUIT_LETTER[lab["suit"]]])
        if not self._X:
            raise RuntimeError(f"no usable exemplars in {card_dir!r}")
        self._rank_clf = self._suit_clf = None
        self._fit()

    def _fit(self):
        """(Re)train the rank + suit classifiers. Each is ('svc', clf) or, when
        only one class is present (degenerate early on), ('const', label)."""
        from sklearn.svm import LinearSVC

        def train(y):
            if len(set(y)) < 2:
                return ("const", y[0])
            return ("svc", LinearSVC(C=1.0, max_iter=5000).fit(self._X, y))

        rank_m, suit_m = train(self._rank), train(self._suit)
        with self._lock:
            self._rank_clf, self._suit_clf = rank_m, suit_m

    def recognize(self, card_bgr, kind="H"):
        """Recognise a (native) whole-card crop — ``kind`` 'H' (hole) or 'B'
        (board), which have different crop geometry. Returns ``(card, info)`` with
        ``card = (rank, suit)`` and ``info['color']`` ('red'/'black'). The suit is
        colour-gated — the SVM only picks among suits of the detected colour — so
        the read never contradicts the reliable colour signal."""
        f = _features(card_bgr, self._hog).reshape(1, -1)
        red = bool(_is_red(self._suit_region(card_bgr, kind)))
        with self._lock:
            rank_m, suit_m = self._rank_clf, self._suit_clf
        rank = rank_m[1] if rank_m[0] == "const" else int(rank_m[1].predict(f)[0])
        suit = self._suit_of_colour(suit_m, f, red)
        return (rank, suit), {"color": "red" if red else "black"}

    @staticmethod
    def _suit_region(card, kind):
        """The little suit-pip patch for the red/black colour test, by card kind.
        Hole and board crops frame the card differently, so the pip sits in a
        different place (regions measured to ~95% / ~94% on the labels)."""
        h, w = card.shape[:2]
        if kind == "H" and h >= 112:
            return card[68:112, 0:52]                  # native hole crop
        if kind == "H":
            return card[int(0.17 * h):int(0.28 * h), 0:max(1, int(0.19 * w))]
        return card[int(0.10 * h):int(0.30 * h), 12:max(13, int(0.30 * w))]   # board

    @staticmethod
    def _suit_of_colour(suit_m, f, red):
        """Best suit of the detected colour: among the same-colour suits, take the
        one the SVM scores highest (falls back to plain predict if it can't rank)."""
        if suit_m[0] == "const":
            return suit_m[1]
        clf = suit_m[1]
        allowed = _RED if red else ({0, 1, 2, 3} - _RED)
        df = clf.decision_function(f)
        classes = list(clf.classes_)
        if getattr(df, "ndim", 1) == 2 and df.shape[1] == len(classes) and len(classes) > 2:
            cand = [(df[0][i], c) for i, c in enumerate(classes) if c in allowed]
            if cand:
                return int(max(cand)[1])
        return int(clf.predict(f)[0])

    def add_exemplar(self, card_bgr, rank_int, suit_int):
        """Add a confirmed/corrected whole-card crop and refit, so detection
        improves within the session."""
        self._X.append(_features(card_bgr, self._hog))
        self._rank.append(rank_int)
        self._suit.append(suit_int)
        self._fit()

    def read_hole(self, frame_bgr, cfg):
        """Detect both hole cards from a full frame. ``None`` for an empty /
        animating / dimmed slot (presence gated on the bright corner)."""
        from .poker import card_present
        cw, ch = cfg["corner"]
        out = []
        for i, (x, y) in enumerate(cfg["hole"]):
            corner = frame_bgr[y:y + ch, x:x + cw]
            l, t, w, h = whole_roi((x, y), f"H{i}")
            whole = frame_bgr[t:t + h, l:l + w]
            if corner.shape[:2] != (ch, cw) or not card_present(corner) \
                    or whole.shape[:2] != (h, w):
                out.append(None)
            else:
                out.append(self.recognize(whole))
        return out


class TrainingWriter:
    """Persists confirmed/corrected whole-card crops as new labeled exemplars in
    the ``data/poker_cards`` format the reader (and ``label --poker``) use — so the
    library grows as you play and each launch reads better. Deduped against the
    existing crops so confirming a static hand repeatedly doesn't flood the set."""

    def __init__(self, card_dir="data/poker_cards", dedup=7):
        if not _HAVE:
            raise RuntimeError("training writer needs numpy + opencv")
        self.dir, self.dedup = card_dir, dedup
        os.makedirs(card_dir, exist_ok=True)
        self.labels_path = os.path.join(card_dir, "labels.json")
        self.labels = (json.load(open(self.labels_path, encoding="utf-8"))
                       if os.path.exists(self.labels_path) else {})
        self._sigs = []
        for key in self.labels:
            frame, slot = key.split("#")
            im = cv2.imread(os.path.join(card_dir, f"{frame}_{slot}.png"))
            if im is not None:
                self._sigs.append(self._sig(im))
        self._seq, self._pid = 0, os.getpid()

    def _sig(self, crop):
        return cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (18, 26)).astype("int16")

    def save(self, card_bgr, rank_int, suit_int, slot):
        """Write one labeled whole-card crop unless a near-identical one exists.
        Returns True if a new exemplar was written."""
        sig = self._sig(card_bgr)
        if any(float(np.mean(np.abs(sig - s))) < self.dedup for s in self._sigs):
            return False
        self._seq += 1
        fid = f"live{self._pid}_{self._seq}"
        cv2.imwrite(os.path.join(self.dir, f"{fid}_{slot}.png"),
                    cv2.resize(card_bgr, _STORE))
        self.labels[f"{fid}#{slot}"] = {"rank": INT_TO_RANK[rank_int],
                                        "suit": _SUIT_NAME[suit_int]}
        self._sigs.append(sig)
        with open(self.labels_path, "w", encoding="utf-8") as f:
            json.dump(self.labels, f, indent=1)
        return True


def recrop_library_to_whole(card_dir, frames_dir, config_path="config/regions.json"):
    """One-time migration: rewrite each labeled corner crop as a whole-card crop,
    re-cropped from its source frame (labels transfer by frame#slot). Leaves
    labels.json untouched. Returns (rewritten, missing) counts."""
    cfg = json.load(open(config_path, encoding="utf-8"))["poker"]
    anchors = {**{f"H{i}": xy for i, xy in enumerate(cfg["hole"])},
               **{f"B{i}": xy for i, xy in enumerate(cfg["board"])}}
    labels = json.load(open(os.path.join(card_dir, "labels.json"), encoding="utf-8"))
    done = missing = 0
    for key, lab in labels.items():
        if lab.get("_skip") or "rank" not in lab:
            continue
        frame, slot = key.split("#")
        im = cv2.imread(os.path.join(frames_dir, f"{frame}.png"))
        if im is None or slot not in anchors:
            missing += 1
            continue
        l, t, w, h = whole_roi(anchors[slot], slot)
        crop = im[max(t, 0):t + h, max(l, 0):l + w]
        if crop.size == 0:
            missing += 1
            continue
        cv2.imwrite(os.path.join(card_dir, f"{frame}_{slot}.png"), cv2.resize(crop, _STORE))
        done += 1
    return done, missing
