"""Transfer-learned card reader (ResNet34) — the optional high-accuracy alternative
to the HOG+SVM ``HoleCardReader``.

Why it exists: leakage-free grouped CV puts this at ~98% on new clean cards and
~96% on obscured cards, versus HOG's ~68% / ~45% — HOG was memorising near-
duplicate frames and can't read a covered card. The cost: it needs ``torch`` +
``torchvision`` (imported lazily, only when this reader is selected, so the HOG
path stays dependency-free), and it does NOT hot-refit on corrections the way the
SVM does — the live model is fixed; corrections bank crops for the next retrain.

The model predicts RANK (13-way); SUIT is colour-gated exactly like the HOG reader
(``_is_red`` picks red/black, the 4-way suit head only chooses within that colour),
so the read never contradicts the reliable colour signal. ``recognize`` matches
``HoleCardReader.recognize`` so it drops into the detection path unchanged.
Inference is fine on CPU (~30 ms/card), so no GPU is needed at run time.
"""
from __future__ import annotations

import json
import os

_INPUT = 224
_IMAGENET_MEAN = (0.485, 0.456, 0.406)
_IMAGENET_STD = (0.229, 0.224, 0.225)


def _build_net(torch, n_rank, n_suit, pretrained=True):
    import torch.nn as nn
    from torchvision.models import resnet34, ResNet34_Weights

    class CardNet(nn.Module):
        def __init__(self):
            super().__init__()
            m = resnet34(weights=ResNet34_Weights.DEFAULT if pretrained else None)
            self.backbone = nn.Sequential(*list(m.children())[:-1])   # -> 512
            self.rank = nn.Linear(512, n_rank)
            self.suit = nn.Linear(512, n_suit)

        def forward(self, x):
            f = self.backbone(x).flatten(1)
            return self.rank(f), self.suit(f)

    return CardNet()


class CnnCardReader:
    """ResNet34 rank + colour-gated suit. Drop-in for ``HoleCardReader`` (same
    ``recognize`` signature/return). Inference only — trained offline by
    :func:`train_and_save`. ``add_exemplar``/``reload`` are no-ops: the CNN doesn't
    hot-update mid-session (the documented trade-off vs the SVM)."""

    def __init__(self, ckpt_path, device=None):
        import torch
        self._t = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        ck = torch.load(ckpt_path, map_location=self.device)
        self.rank_classes = list(ck["rank_classes"])    # head index -> rank int
        self.suit_classes = list(ck["suit_classes"])    # head index -> suit int
        self.net = _build_net(torch, len(self.rank_classes), len(self.suit_classes),
                              pretrained=False)     # we load our own weights below
        self.net.load_state_dict(ck["state"])
        self.net.to(self.device).eval()
        self._mean = torch.tensor(_IMAGENET_MEAN).view(1, 3, 1, 1).to(self.device)
        self._std = torch.tensor(_IMAGENET_STD).view(1, 3, 1, 1).to(self.device)

    def _tensor(self, card_bgr):
        import cv2
        rgb = cv2.cvtColor(cv2.resize(card_bgr, (_INPUT, _INPUT)),
                           cv2.COLOR_BGR2RGB).astype("float32") / 255.0
        t = self._t.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0).to(self.device)
        return (t - self._mean) / self._std

    def recognize(self, card_bgr, kind="H"):
        """``(card, info)`` with ``card=(rank, suit)`` ints and ``info['color']`` —
        same contract as ``HoleCardReader.recognize``, suit colour-gated."""
        from .poker_cards import _is_red, HoleCardReader, _RED
        with self._t.no_grad():
            rlog, slog = self.net(self._tensor(card_bgr))
        rank = self.rank_classes[int(rlog.argmax(1))]
        red = bool(_is_red(HoleCardReader._suit_region(card_bgr, kind)))
        allowed = _RED if red else ({0, 1, 2, 3} - _RED)
        sl = slog[0]
        cand = [(float(sl[i]), c) for i, c in enumerate(self.suit_classes) if c in allowed]
        suit = int(max(cand)[1]) if cand else int(self.suit_classes[int(sl.argmax())])
        return (rank, suit), {"color": "red" if red else "black"}

    def add_exemplar(self, *a, **k):     # CNN doesn't hot-update; corrections bank
        return None                       # crops for the next train_and_save

    def reload(self):                     # nothing to reload live
        return None


def train_and_save(card_dir="data/poker_cards", out_path=None, epochs=70, device=None):
    """Fine-tune ResNet34 on ALL labeled crops in ``card_dir`` and save a checkpoint
    (weights + rank/suit class orders). No holdout — this is the deployable model.
    Returns the output path."""
    import cv2
    import numpy as np
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    from ..cards import RANK_TO_INT, SUIT_TO_INT
    from .poker_cards import _SUIT_LETTER
    dev = device or ("cuda" if torch.cuda.is_available() else "cpu")
    out_path = out_path or os.path.join(card_dir, "cnn_card.pt")
    labels = json.load(open(os.path.join(card_dir, "labels.json"), encoding="utf-8"))
    imgs, ranks, suits = [], [], []
    for key, lab in labels.items():
        if lab.get("_skip") or "rank" not in lab:
            continue
        frame, slot = key.split("#")
        im = cv2.imread(os.path.join(card_dir, f"{frame}_{slot}.png"))
        if im is None:
            continue
        imgs.append(im)
        ranks.append(RANK_TO_INT[lab["rank"]])
        suits.append(SUIT_TO_INT[_SUIT_LETTER[lab["suit"]]])
    rank_classes = sorted(set(ranks))
    suit_classes = sorted(set(suits))
    rmap = {c: i for i, c in enumerate(rank_classes)}
    smap = {c: i for i, c in enumerate(suit_classes)}
    T = torch.stack([torch.from_numpy(
        cv2.cvtColor(cv2.resize(im, (_INPUT, _INPUT)), cv2.COLOR_BGR2RGB).astype("float32") / 255
        ).permute(2, 0, 1) for im in imgs]).to(dev)
    yr = torch.tensor([rmap[r] for r in ranks], device=dev)
    ys = torch.tensor([smap[s] for s in suits], device=dev)
    mean = torch.tensor(_IMAGENET_MEAN, device=dev).view(1, 3, 1, 1)
    std = torch.tensor(_IMAGENET_STD, device=dev).view(1, 3, 1, 1)

    def light(x):
        n = x.shape[0]
        out = x * (0.85 + 0.3 * torch.rand(n, 1, 1, 1, device=dev))
        m = out.mean(dim=(1, 2, 3), keepdim=True)
        out = (out - m) * (0.85 + 0.3 * torch.rand(n, 1, 1, 1, device=dev)) + m
        return ((out + 0.02 * torch.randn_like(out)).clamp(0, 1) - mean) / std

    net = _build_net(torch, len(rank_classes), len(suit_classes)).to(dev)
    opt = torch.optim.Adam(net.parameters(), lr=3e-4, weight_decay=1e-4)
    sch = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
    lossf = nn.CrossEntropyLoss(label_smoothing=0.1)
    n = len(imgs)
    for e in range(epochs):
        net.train()
        perm = torch.randperm(n, device=dev)
        for i in range(0, n, 16):
            idx = perm[i:i + 16]
            opt.zero_grad()
            rl, slg = net(light(T[idx]))
            (lossf(rl, yr[idx]) + lossf(slg, ys[idx])).backward()
            opt.step()
        sch.step()
    net.eval()
    with torch.no_grad():
        rl, slg = net((T - mean) / std)
        tr_rank = (rl.argmax(1) == yr).float().mean().item()
        tr_suit = (slg.argmax(1) == ys).float().mean().item()
    torch.save({"state": net.state_dict(), "rank_classes": rank_classes,
                "suit_classes": suit_classes}, out_path)
    return out_path, n, tr_rank, tr_suit


def main(argv=None):
    """Retrain the deployable CNN from the current labels:
        uv run python -m judgment_assist.vision.cnn_cards"""
    import argparse
    p = argparse.ArgumentParser(prog="judgment-assist train-cnn")
    p.add_argument("--card-dir", default="data/poker_cards")
    p.add_argument("--out", default=None, help="checkpoint path (default: <card-dir>/cnn_card.pt)")
    p.add_argument("--epochs", type=int, default=70)
    a = p.parse_args(argv)
    out, n, tr_rank, tr_suit = train_and_save(a.card_dir, a.out, a.epochs)
    print(f"trained on {n} crops -> {out}  "
          f"(train rank {100*tr_rank:.0f}% / suit {100*tr_suit:.0f}%)")


if __name__ == "__main__":
    main()
