"""Locate blackjack cards on the felt and expose each card's corner rank index.

Two facts about this table drive the approach:

* The cards are **cream**, not white — a sampled card body is roughly HSV
  S=87 V=110, so a naive "bright, desaturated" gate misses them. The mask gate
  here is deliberately loose on value/saturation.
* The felt prints a lot of light text — "BLACK JACK", "PAY 3 TO 2", the
  "Dealer must stand on 17…" banner, "INSURANCE PAYS" — which a loose mask also
  catches. The discriminator is *solidity*: a card face has a large solid core,
  whereas text is thin strokes. **Eroding** the mask keeps card cores and
  dissolves the strokes. (An earlier fill-ratio filter was tried and reverted:
  it rejected text but also rejected cascaded card stacks, whose staircase shape
  has a sparse bounding box — it found cards in only 7/72 frames. Erosion finds
  them in ~61/72.)

A blackjack hand is dealt as a downward cascade with a fixed offset, so every
card's top-left rank+suit index stays exposed along the left edge of the
cluster. ``corner_index_boxes`` walks that left edge top-to-bottom and returns
one ROI per card on the rank glyph — feed those to ``CardRecognizer(mode="rank")``.

Tuned for 1920x1080; the play-area window and sizes scale from frame dimensions
so other resolutions degrade gracefully rather than silently missing cards.
"""
from __future__ import annotations

try:
    import cv2
    import numpy as np
    _HAVE_DEPS = True
except Exception:  # pragma: no cover
    _HAVE_DEPS = False

# card body is cream (sampled ~S=87, V=110): gate loose on S/V, erosion cleans up
_WHITE_LO = (0, 0, 140)
_WHITE_HI = (180, 90, 255)


def _card_mask(img):
    """Binary mask of card-fill pixels inside the play area (pre-erosion)."""
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    white = cv2.inRange(hsv, _WHITE_LO, _WHITE_HI)
    area = np.zeros_like(white)
    area[int(0.11 * h):int(0.74 * h), int(0.15 * w):int(0.87 * w)] = 255
    return cv2.bitwise_and(white, area)


def find_card_clusters(img, erode=21, min_core_area=900):
    """Return card-fill clusters as ``[(x, y, w, h), ...]`` left-to-right.

    Erodes the card mask by an ``erode``-px square so only solid card cores
    survive (printed felt text dissolves), then takes each surviving component's
    bounding box, grown back by the erosion radius to approximate the card's true
    extent. A cluster is one hand (cascaded cards merge into one core)."""
    if not _HAVE_DEPS:
        raise RuntimeError("vision needs: pip install numpy opencv-python")
    H, W = img.shape[:2]
    mask = _card_mask(img)
    core = cv2.erode(mask, np.ones((erode, erode), np.uint8))
    n, _lab, stats, _c = cv2.connectedComponentsWithStats(core, connectivity=8)
    pad = erode // 2
    out = []
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        if a < min_core_area:
            continue
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(W, x + w + pad), min(H, y + h + pad)
        out.append((int(x0), int(y0), int(x1 - x0), int(y1 - y0)))
    out.sort(key=lambda b: b[0])
    return out


def corner_index_boxes(img, cluster, max_cards=8):
    """Top-to-bottom rank-index ROIs along a cluster's exposed left edge.

    Returns ``[(x, y, w, h), ...]`` in absolute frame coords — one per visible
    card, sized to the rank glyph (the suit sits just below and is skipped).

    NOTE: cluster *finding* is validated on real frames; rank *reading* through
    these ROIs awaits the 13-rank template library and a round-trip check."""
    if not _HAVE_DEPS:
        raise RuntimeError("vision needs: pip install numpy opencv-python")
    cx, cy, cw, ch = cluster
    strip_w = max(40, int(0.20 * cw))
    strip = img[cy:cy + ch, cx:cx + strip_w]
    if strip.size == 0:
        return []
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
    boxes, last_y = [], -999
    for gx, gy, gw, gh in glyphs:
        if gy - last_y < int(0.06 * H):   # same rank/suit pair as previous
            continue
        boxes.append((cx + gx, cy + gy, gw, gh))
        last_y = gy
        if len(boxes) >= max_cards:
            break
    return boxes
