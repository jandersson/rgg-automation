"""Harvest rank-glyph corner crops from captured frames, for building the
13-rank blackjack template library.

This is the "harvest corner crops via locate.py" step. It runs the verified
localizer (``find_card_clusters`` + ``corner_index_boxes`` from ``vision.locate``)
over the screenshot library and dumps, into ``--out`` (default ``data/crops``):

  * ``<frame>__c<cluster>i<idx>.png`` — one padded rank-glyph crop per card
  * ``_contact.png``                 — a labeled contact sheet of every crop, so
                                        you can eyeball the whole pile at once and
                                        map each index to a rank
  * ``_index.json``                  — ``{tile_index: crop_path}`` for the sheet
  * ``_overlays/<frame>`` (``--overlays``) — the source frame with cluster boxes
                                        (green) and the padded corner ROIs (red)
                                        drawn on, to sanity-check localization

Only ``in_hand`` frames carry dealt cards, so by default we read the state
manifest ``sort_frames`` writes and keep just those. Pass ``--only ""`` to harvest
every frame regardless of state.

    uv run python -m judgment_assist.capture.harvest                # in_hand crops + sheet
    uv run python -m judgment_assist.capture.harvest --overlays     # also debug overlays
    uv run python -m judgment_assist.capture.harvest --only ""      # every frame

Workflow: skim ``_contact.png``, pick one clean exposure of each rank, copy it to
``data/templates/<rank>.png`` (A K Q J T 9..2), then round-trip verify before
committing — see ``judgment_assist.capture.verify_templates``.
"""
from __future__ import annotations

import argparse
import json
import os

from ..vision.locate import find_card_clusters, corner_index_boxes


def _load_states(path):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def _frames(src, states, only):
    """Top-level frame_*.png in ``src``, filtered to ``only`` state if given."""
    names = sorted(f for f in os.listdir(src)
                   if f.startswith("frame_") and f.endswith(".png"))
    if only:
        names = [f for f in names if states.get(f) == only]
    return names


def _pad_box(box, pad, W, H):
    x, y, w, h = box
    px, py = int(round(w * pad)), int(round(h * pad))
    x0, y0 = max(0, x - px), max(0, y - py)
    x1, y1 = min(W, x + w + px), min(H, y + h + py)
    return x0, y0, x1 - x0, y1 - y0


def _contact_sheet(cv2, np, crops, cols, tile_w, tile_h, cap_h):
    """Grid of all crops, each captioned with its tile index. ``crops`` is a list
    of (index, bgr_image)."""
    if not crops:
        return None
    rows = (len(crops) + cols - 1) // cols
    cell_h = tile_h + cap_h
    sheet = np.full((rows * cell_h, cols * tile_w, 3), 40, np.uint8)
    for n, (idx, crop) in enumerate(crops):
        r, c = divmod(n, cols)
        oy, ox = r * cell_h, c * tile_w
        ch, cw = crop.shape[:2]
        scale = min(tile_w / max(cw, 1), tile_h / max(ch, 1))
        nw, nh = max(1, int(cw * scale)), max(1, int(ch * scale))
        resized = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_NEAREST)
        py, px = oy + (tile_h - nh) // 2, ox + (tile_w - nw) // 2
        sheet[py:py + nh, px:px + nw] = resized
        cv2.putText(sheet, str(idx), (ox + 2, oy + tile_h + cap_h - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (180, 255, 180), 1)
        cv2.rectangle(sheet, (ox, oy), (ox + tile_w - 1, oy + cell_h - 1), (70, 70, 70), 1)
    return sheet


def run(a):
    import cv2

    try:
        import numpy as np
    except Exception:  # pragma: no cover
        raise SystemExit("harvest needs: pip install numpy opencv-python")

    states = _load_states(a.states)
    if a.only and not states:
        raise SystemExit(
            f"--only {a.only!r} needs the state manifest {a.states!r}; run "
            f"`uv run python -m judgment_assist.capture.sort_frames` first, "
            f"or pass --only \"\" to harvest every frame.")

    frames = _frames(a.src, states, a.only)
    if not frames:
        raise SystemExit(f"no matching frames in {a.src} (only={a.only!r})")

    os.makedirs(a.out, exist_ok=True)
    if a.overlays:
        os.makedirs(os.path.join(a.out, "_overlays"), exist_ok=True)

    sheet_crops, index_map = [], {}
    n_frames = n_clusters = n_crops = 0
    zero_cluster = []
    tile_idx = 0

    for fn in frames:
        img = cv2.imread(os.path.join(a.src, fn))
        if img is None:
            continue
        n_frames += 1
        H, W = img.shape[:2]
        clusters = find_card_clusters(img)
        if not clusters:
            zero_cluster.append(fn)
        ov = img.copy() if a.overlays else None
        stem = os.path.splitext(fn)[0]
        for ci, cl in enumerate(clusters):
            n_clusters += 1
            if ov is not None:
                cx, cy, cw, ch = cl
                cv2.rectangle(ov, (cx, cy), (cx + cw, cy + ch), (0, 255, 0), 2)
            for bi, box in enumerate(corner_index_boxes(img, cl, max_cards=a.max_cards)):
                x, y, w, h = _pad_box(box, a.pad, W, H)
                if w < 4 or h < 4:
                    continue
                crop = img[y:y + h, x:x + w]
                name = f"{stem}__c{ci}i{bi}.png"
                cv2.imwrite(os.path.join(a.out, name), crop)
                n_crops += 1
                index_map[tile_idx] = name
                sheet_crops.append((tile_idx, crop))
                tile_idx += 1
                if ov is not None:
                    cv2.rectangle(ov, (x, y), (x + w, y + h), (0, 0, 255), 2)
        if ov is not None:
            cv2.imwrite(os.path.join(a.out, "_overlays", fn), ov)

    # contact sheet(s). One tall sheet is unreadable for labeling, so --page-size
    # paginates into _contact_NNN.png; tile captions stay GLOBAL so by_index
    # labels are unambiguous across pages.
    sheets = []
    if sheet_crops:
        if a.page_size and a.page_size > 0:
            for p in range(0, len(sheet_crops), a.page_size):
                chunk = sheet_crops[p:p + a.page_size]
                s = _contact_sheet(cv2, np, chunk, a.cols, a.tile_w, a.tile_h, a.cap_h)
                name = f"_contact_{p // a.page_size:03d}.png"
                cv2.imwrite(os.path.join(a.out, name), s)
                sheets.append(name)
        else:
            s = _contact_sheet(cv2, np, sheet_crops, a.cols, a.tile_w, a.tile_h, a.cap_h)
            cv2.imwrite(os.path.join(a.out, "_contact.png"), s)
            sheets.append("_contact.png")
    with open(os.path.join(a.out, "_index.json"), "w", encoding="utf-8") as fh:
        json.dump(index_map, fh, indent=2)

    print(f"harvested from {n_frames} frames (only={a.only!r})")
    print(f"  clusters found : {n_clusters}")
    print(f"  crops written  : {n_crops} -> {a.out}")
    print(f"  contact sheet  : {len(sheets)} page(s), {len(sheet_crops)} tiles "
          f"({', '.join(sheets[:3])}{' ...' if len(sheets) > 3 else ''})")
    if zero_cluster:
        print(f"  {len(zero_cluster)} frame(s) with NO cluster: "
              f"{', '.join(zero_cluster[:8])}{' ...' if len(zero_cluster) > 8 else ''}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="judgment-assist harvest")
    p.add_argument("--src", default="data/screens", help="frame folder")
    p.add_argument("--states", default="data/screens/_states.json",
                   help="state manifest from sort_frames (for --only)")
    p.add_argument("--only", default="in_hand",
                   help='keep frames of this state only; "" = all frames')
    p.add_argument("--out", default="data/crops", help="where to dump crops")
    p.add_argument("--pad", type=float, default=0.35,
                   help="fraction of glyph box added as margin on each side")
    p.add_argument("--max-cards", dest="max_cards", type=int, default=8)
    p.add_argument("--overlays", action="store_true",
                   help="also write source frames with cluster/ROI boxes drawn")
    p.add_argument("--cols", type=int, default=12, help="contact-sheet columns")
    p.add_argument("--tile-w", dest="tile_w", type=int, default=64)
    p.add_argument("--tile-h", dest="tile_h", type=int, default=80)
    p.add_argument("--cap-h", dest="cap_h", type=int, default=16)
    p.add_argument("--page-size", dest="page_size", type=int, default=0,
                   help="tiles per contact sheet (0 = one big sheet)")
    run(p.parse_args(argv))


if __name__ == "__main__":
    main()
