"""Locate blackjack cards on the felt and expose each card's corner rank index.

The table prints a lot of white text on the green felt — "BLACK JACK", "PAY 3 TO
2", the "Dealer must stand on 17…" banner, "INSURANCE PAYS" — so a plain
white-pixel search yields many false positives. The distinguishing feature is
*fill*: a card face is a solid white rectangle, while printed text is thin
strokes. Filtering connected components by fill ratio (filled area / bbox area)
and a minimum card size cleanly separates cards from text.

A blackjack hand is dealt as a downward cascade with a fixed offset, so every
card's top-left rank+suit index stays exposed along the left edge of the
cluster. ``corner_index_boxes`` walks that left edge top-to-bottom and returns
one ROI per card, positioned on the rank glyph — feed those to
``CardRecognizer(mode="rank")`` for Hi-Lo counting. Suit is ignored for counting
but the same corners carry it for later (poker / dedup) use.

Tuned for 1920x1080; the play-area window and size thresholds scale from frame
height so other resolutions degrade gracefully rather than silently missing
cards.
"""
from __future__ import annotations

try:
    import cv2
    import numpy as np
    _HAVE_DEPS = True
except Exception:  # pragma: no cover
    _HAVE_DEPS = False


def _card_mask(img):
    """Binary mask of solid card-fill pixels inside the play area."""
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    white = cv2.inRange(hsv, (0, 0, 150), (180, 80, 255))
    # play area only: drop the HUD badges / side panels / table edges
    area = np.zeros_like(white)
    area[int(0.11 * h):int(0.72 * h), int(0.16 * w):int(0.86 * w)] = 255
    white = cv2.bitwise_and(white, area)
    return cv2.morphologyEx(white, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))


def find_card_clusters(img, min_fill=0.55):
    """Return solid card-fill clusters as ``[(x, y, w, h), ...]`` left-to-right.

    A cluster is one hand (cards overlap into a single blob). ``min_fill``
    rejects printed felt text, whose strokes leave a sparse bounding box."""
    if not _HAVE_DEPS:
        raise RuntimeError("vision needs: pip install numpy opencv-python")
    H, W = img.shape[:2]
    mask = _card_mask(img)
    min_w, min_h = int(0.035 * W), int(0.083 * H)   # ~one card at 1080p
    n, _lab, stats, _c = cv2.connectedComponentsWithStats(mask, connectivity=8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if w < min_w or h < min_h:
            continue
        if area / float(w * h) < min_fill:
            continue
        out.append((int(x), int(y), int(w), int(h)))
    out.sort(key=lambda b: b[0])
    return out


def corner_index_boxes(img, cluster, max_cards=8):
    """Top-to-bottom rank-index ROIs along a cluster's exposed left edge.

    Returns ``[(x, y, w, h), ...]`` in absolute frame coords — one per visible
    card, sized to the rank glyph (the suit sits just below it and is excluded).
    """
    if not _HAVE_DEPS:
        raise RuntimeError("vision needs: pip install numpy opencv-python")
    cx, cy, cw, ch = cluster
    strip_w = max(40, int(0.20 * cw))
    strip = img[cy:cy + ch, cx:cx + strip_w]
    hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
    ink = cv2.inRange(hsv, (0, 0, 0), (180, 255, 150))   # dark/colored glyph ink
    ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, _lab, stats, _c = cv2.connectedComponentsWithStats(ink, connectivity=8)
    H = strip.shape[0]
    glyphs = []
    for i in range(1, n):
        gx, gy, gw, gh, a = stats[i]
        if a < 20 or gh < 0.04 * H or gh > 0.25 * H:
            continue
        glyphs.append((int(gx), int(gy), int(gw), int(gh)))
    glyphs.sort(key=lambda b: b[1])     # top-to-bottom
    # rank + suit alternate down the edge; keep the rank (upper of each pair)
    boxes, last_y = [], -999
    for gx, gy, gw, gh in glyphs:
        if gy - last_y < int(0.06 * H):   # same index pair as previous glyph
            continue
        boxes.append((cx + gx, cy + gy, gw, gh))
        last_y = gy
        if len(boxes) >= max_cards:
            break
    return boxes
