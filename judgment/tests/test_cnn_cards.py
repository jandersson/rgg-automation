"""CnnCardReader interface + colour-gating (no training/download — a random-weight
checkpoint is enough to exercise load + recognize)."""
import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")
torch = pytest.importorskip("torch")
pytest.importorskip("torchvision")

from judgment_assist.vision import cnn_cards as C
from judgment_assist.vision import poker_cards as PC
from judgment_assist.cards import RANK_TO_INT, SUIT_TO_INT


def _red_whole():
    """A native hole-card crop with red ink in the suit-test region."""
    c = np.full((400, 278, 3), 235, np.uint8)
    y0, y1, x0, x1 = PC._HOLE_SUIT
    c[y0:y1, x0 + 4:x1 - 4] = (40, 40, 180)   # red pip on white -> dark-red ink for _is_red
    return c


def test_cnn_reader_recognize_and_colour_gate(tmp_path):
    rank_classes = sorted(RANK_TO_INT.values())          # 13 ranks
    suit_classes = sorted(SUIT_TO_INT.values())          # 4 suits
    net = C._build_net(torch, len(rank_classes), len(suit_classes), pretrained=False)
    ckpt = tmp_path / "m.pt"
    torch.save({"state": net.state_dict(), "rank_classes": rank_classes,
                "suit_classes": suit_classes}, ckpt)

    reader = C.CnnCardReader(str(ckpt), device="cpu")
    (rank, suit), info = reader.recognize(_red_whole(), kind="H")
    assert rank in rank_classes                          # valid rank
    assert info["color"] == "red" and suit in PC._RED    # colour read + suit gated to red
    # drop-in: no-op hooks the advisor calls
    assert reader.add_exemplar(None, 0, 0) is None and reader.reload() is None
