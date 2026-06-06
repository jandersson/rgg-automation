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
        self._card_dir = card_dir
        self._hog = _hog()
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        """Read the labeled crop library from disk into the training set and (re)fit
        the classifiers. Shared by ``__init__`` and :meth:`reload`."""
        labels_path = os.path.join(self._card_dir, "labels.json")
        if not os.path.exists(labels_path):
            raise RuntimeError(
                f"no labeled crops in {self._card_dir!r} — the hole-card reader needs "
                f"labels.json + the whole-card PNGs (label --poker, then re-crop)")
        labels = json.load(open(labels_path, encoding="utf-8"))
        X, rank, suit = [], [], []
        for key, lab in labels.items():
            if lab.get("_skip") or "rank" not in lab:
                continue
            frame, slot = key.split("#")
            crop = cv2.imread(os.path.join(self._card_dir, f"{frame}_{slot}.png"))
            if crop is None:
                continue
            X.append(_features(crop, self._hog))
            rank.append(RANK_TO_INT[lab["rank"]])
            suit.append(SUIT_TO_INT[_SUIT_LETTER[lab["suit"]]])
        if not X:
            raise RuntimeError(f"no usable exemplars in {self._card_dir!r}")
        self._X, self._rank, self._suit = X, rank, suit
        self._rank_clf = self._suit_clf = None
        self._fit()

    def reload(self):
        """Re-read the library from disk and refit — call after the Labels tab fixes,
        skips or deletes crops so the running detector reflects the edits at once."""
        self._load()

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

    def reload(self):
        """Re-sync the in-memory labels + dedup signatures from disk. The Labels tab
        edits labels.json directly; without this the writer would keep its stale copy
        and, on the next bank, **resurrect a deleted entry** (the POKER.md gotcha)."""
        self.labels = (json.load(open(self.labels_path, encoding="utf-8"))
                       if os.path.exists(self.labels_path) else {})
        self._sigs = []
        for key in self.labels:
            frame, slot = key.split("#")
            im = cv2.imread(os.path.join(self.dir, f"{frame}_{slot}.png"))
            if im is not None:
                self._sigs.append(self._sig(im))

    def _sig(self, crop):
        return cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (18, 26)).astype("int16")

    def save(self, card_bgr, rank_int, suit_int, slot):
        """Write one labeled whole-card crop unless a near-identical one exists.
        Returns the written PNG path (truthy) on a new exemplar, else ``None`` — the
        path lets the GUI's review tab show the crop that was banked."""
        sig = self._sig(card_bgr)
        if any(float(np.mean(np.abs(sig - s))) < self.dedup for s in self._sigs):
            return None
        self._seq += 1
        fid = f"live{self._pid}_{self._seq}"
        path = os.path.join(self.dir, f"{fid}_{slot}.png")
        cv2.imwrite(path, cv2.resize(card_bgr, _STORE))
        # A banked crop came from a play confirm/correction — human-verified — so
        # it's reviewed (the Labels tab shows ✓ and counts it).
        self.labels[f"{fid}#{slot}"] = {"rank": INT_TO_RANK[rank_int],
                                        "suit": _SUIT_NAME[suit_int], "reviewed": True}
        self._sigs.append(sig)
        with open(self.labels_path, "w", encoding="utf-8") as f:
            json.dump(self.labels, f, indent=1)
        return path


_SUIT_FULL = {"c": "clubs", "d": "diamonds", "h": "hearts", "s": "spades"}


class LabelLibrary:
    """Read/edit the poker label library — the crop PNGs + ``labels.json`` shared by
    the offline labeler and the live ``TrainingWriter``. Pure file ops (no tk), so
    the GUI Labels tab is a thin view over this and the logic is unit-tested.

    A labels.json value is ``{"rank","suit"}`` (labeled), ``{"_skip": true}`` (a bad
    crop excluded from training) or ``{}`` (captured but not yet labeled). Suits are
    stored as full names ('clubs'…); ``set_label``/``add`` accept a letter too."""

    def __init__(self, card_dir="data/poker_cards"):
        if not _HAVE:
            raise RuntimeError("label library needs numpy + opencv")
        self.dir = card_dir
        os.makedirs(card_dir, exist_ok=True)
        self.labels_path = os.path.join(card_dir, "labels.json")
        self.reload()

    def reload(self):
        self.labels = (json.load(open(self.labels_path, encoding="utf-8"))
                       if os.path.exists(self.labels_path) else {})

    def _save(self):
        with open(self.labels_path, "w", encoding="utf-8") as f:
            json.dump(self.labels, f, indent=1)

    def _path(self, key):
        frame, slot = key.split("#")
        return os.path.join(self.dir, f"{frame}_{slot}.png")

    def entries(self):
        """Every label entry that still has a crop on disk, newest first by mtime.
        Each: ``{key, frame, slot, path, rank, suit, skip, labeled, reviewed, guess,
        mtime}``. ``reviewed`` marks a human-verified label (set on a tab edit or a
        play confirm); ``guess`` is the detector's pre-fill for an unlabeled crop."""
        out = []
        for key, lab in self.labels.items():
            path = self._path(key)
            if not os.path.exists(path):
                continue
            frame, slot = key.split("#")
            out.append({"key": key, "frame": frame, "slot": slot, "path": path,
                        "rank": lab.get("rank"), "suit": lab.get("suit"),
                        "skip": bool(lab.get("_skip")), "labeled": "rank" in lab,
                        "reviewed": bool(lab.get("reviewed")), "guess": lab.get("_guess"),
                        "mtime": os.path.getmtime(path)})
        return sorted(out, key=lambda e: e["mtime"], reverse=True)

    def set_label(self, key, rank, suit):
        """Fix/assign a crop's rank + suit (suit as 'c'/'d'/'h'/'s' or full name).
        A hand-set label is verified, so it's marked reviewed."""
        self.labels[key] = {"rank": rank, "suit": _SUIT_FULL.get(suit, suit),
                            "reviewed": True}
        self._save()

    def set_skip(self, key):
        """Mark a crop ``_skip`` — kept on disk but excluded from training (a review
        decision, so reviewed too)."""
        self.labels[key] = {"_skip": True, "reviewed": True}
        self._save()

    def set_reviewed(self, key, value=True):
        """Mark a crop reviewed without changing its label — 'this one is correct'."""
        lab = self.labels.get(key)
        if lab is None:
            return
        if value:
            lab["reviewed"] = True
        else:
            lab.pop("reviewed", None)
        self._save()

    def delete(self, key):
        """Remove the label entry and its crop PNG from disk."""
        self.labels.pop(key, None)
        self._save()
        path = self._path(key)
        if os.path.exists(path):
            os.remove(path)

    def add(self, crop_bgr, frame_id, slot, rank=None, suit=None, guess=None):
        """Write a new whole-card crop (captured/imported) and its label entry. With
        ``rank`` it's a finished (reviewed) label; otherwise it's unlabeled — ``{}``,
        or ``{"_guess": {...}}`` when the detector offered a pre-fill (``guess`` is a
        ``(rank, suit)`` pair). Returns (key, path)."""
        key, path = f"{frame_id}#{slot}", os.path.join(self.dir, f"{frame_id}_{slot}.png")
        cv2.imwrite(path, cv2.resize(crop_bgr, _STORE))
        if rank:
            self.labels[key] = {"rank": rank, "suit": _SUIT_FULL.get(suit, suit),
                                "reviewed": True}
        elif guess:
            gr, gs = guess
            self.labels[key] = {"_guess": {"rank": gr, "suit": _SUIT_FULL.get(gs, gs)}}
        else:
            self.labels[key] = {}
        self._save()
        return key, path

    def suspect_labels(self, k=5):
        """Flag likely-mislabeled crops by kNN label consistency: for each labeled
        crop, look at its ``k`` nearest neighbours (HOG-feature distance) among the
        rest; if its rank is NOT the neighbourhood's majority, the label is suspect
        — a real mislabel, or a genuinely hard crop, either way worth a human look.
        Returns ``[{key, label, suggest, votes}, …]`` worst (strongest disagreement)
        first. Pure read; changes nothing."""
        import collections
        hog = _hog()
        keys, ranks, suits, feats = [], [], [], []
        for key, lab in self.labels.items():
            if lab.get("_skip") or "rank" not in lab:
                continue
            crop = cv2.imread(self._path(key))
            if crop is None:
                continue
            keys.append(key)
            ranks.append(lab["rank"])
            suits.append(lab["suit"])
            feats.append(_features(crop, hog))
        if len(keys) <= k:
            return []
        X = np.array(feats)
        suspects = []
        for i, key in enumerate(keys):
            d = np.linalg.norm(X - X[i], axis=1)
            nbr = [j for j in np.argsort(d) if j != i][:k]
            rank_votes = collections.Counter(ranks[j] for j in nbr)
            top_rank, votes = rank_votes.most_common(1)[0]
            if top_rank != ranks[i] and votes >= (k // 2 + 1):
                suit_top = collections.Counter(suits[j] for j in nbr).most_common(1)[0][0]
                suspects.append({
                    "key": key,
                    "label": ranks[i] + _SUIT_LETTER[suits[i]],
                    "suggest": top_rank + _SUIT_LETTER[suit_top],
                    "votes": votes})
        return sorted(suspects, key=lambda s: s["votes"], reverse=True)

    def is_dup(self, crop_bgr, thresh=7):
        """True if a near-identical crop is already in the library (same dedup metric
        the live writer uses) — so capture/import don't flood with repeats."""
        sig = cv2.resize(cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY),
                         (18, 26)).astype("int16")
        for key in self.labels:
            im = cv2.imread(self._path(key))
            if im is None:
                continue
            s = cv2.resize(cv2.cvtColor(cv2.resize(im, _STORE), cv2.COLOR_BGR2GRAY),
                           (18, 26)).astype("int16")
            if float(np.mean(np.abs(sig - s))) < thresh:
                return True
        return False


def whole_card_crops(frame_bgr, cfg):
    """The whole-card crop of every currently face-up slot (2 hole + up to 5 board)
    in a frame, for capturing new training crops. Gated on the bright corner (empty/
    animating/dimmed slots are skipped), using the same geometry the live reader and
    banker use. Returns ``[(slot, crop_bgr), …]``."""
    from .poker import card_present
    cw, ch = cfg["corner"]
    slots = ([(f"H{i}", x, y) for i, (x, y) in enumerate(cfg.get("hole", []))] +
             [(f"B{i}", x, y) for i, (x, y) in enumerate(cfg.get("board", []))])
    out = []
    for slot, x, y in slots:
        corner = frame_bgr[y:y + ch, x:x + cw]
        if corner.shape[:2] != (ch, cw) or not card_present(corner):
            continue
        l, t, w, h = whole_roi((x, y), slot)
        whole = frame_bgr[t:t + h, l:l + w]
        if whole.shape[:2] == (h, w):
            out.append((slot, whole))
    return out


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
