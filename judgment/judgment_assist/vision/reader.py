"""Read blackjack card ranks from a frame.

Composes ``locate.find_card_clusters`` (where are the card piles) with
``CardRecognizer.scan_ranks`` (which ranks, found by sliding templates over a
cluster's corner). For each cluster the scanned region is **expanded left and up
past the cluster bbox**: the erosion-based cluster box hugs a card's solid core,
but a court card's corner letter (J/Q/K) sits at the extreme top-left, just
outside it. Measured on a real J: 0.31 best-match scanning the bare cluster vs
0.95 once the region is expanded ~35px left. ``width_frac`` reaches right enough
to catch diagonal cascades (cards stepping down-and-left leave the top card's
corner well to the right); 0.40 catches them without the wider 0.45+ window's
false Q matches into the card interior.

Returns suit-agnostic rank ints — exactly what Hi-Lo counting needs.

KNOWN LIMITS (template scan-matching is fragile on the hard cases; see the
hybrid scan-locate / resize-classify plan): dense 3+ card cascades can confuse
near-neighbours (8 vs 9) or under-score a weak glyph, and a rank seen only in
the opposite colour to its template can fall under ``min_score``.
"""
from __future__ import annotations

from .locate import find_card_clusters


def read_cluster_ranks(frame_bgr, cluster, recognizer,
                       left_pad=35, up_pad=15, width_frac=0.40, min_score=0.6):
    """Ranks in one cluster, top-to-bottom: ``[(label, score, (x, y, w, h)), ...]``
    with boxes in absolute frame coords. ``label`` is a rank int."""
    cx, cy, cw, ch = cluster
    H, W = frame_bgr.shape[:2]
    x0 = max(0, cx - left_pad)
    y0 = max(0, cy - up_pad)
    x1 = min(W, cx + int(width_frac * cw))
    region = frame_bgr[y0:cy + ch, x0:x1]
    if region.size == 0:
        return []
    out = recognizer.scan_ranks(region, min_score=min_score)
    return [(label, score, (x0 + bx, y0 + by, bw, bh))
            for label, score, (bx, by, bw, bh) in out]


def read_ranks(frame_bgr, recognizer, **kw):
    """Every recognised rank in the frame as a flat list of rank ints, ordered
    top-to-bottom across all clusters. Order is informational — counting only
    needs the multiset."""
    dets = []
    for cluster in find_card_clusters(frame_bgr):
        dets.extend(read_cluster_ranks(frame_bgr, cluster, recognizer, **kw))
    dets.sort(key=lambda d: d[2][1])  # absolute y
    return [label for label, _score, _box in dets]
