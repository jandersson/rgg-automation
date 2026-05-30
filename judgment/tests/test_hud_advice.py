"""recommend_hard (totals-only advice for the HUD overlay) must agree with the
card-based recommend() on hard hands — same source of truth, different inputs."""
from judgment_assist.cards import RANK_TO_INT
from judgment_assist.blackjack.strategy import (
    recommend, recommend_hard, HIT, STAND,
)


def _dealer_rank(value):
    """Map a dealer up-card VALUE (2..11, 11=A) to a representative rank int."""
    return 14 if value == 11 else (10 if value == 10 else value)


def _hard_ranks(total):
    """A non-pair, ace-free rank list whose blackjack value is `total` (hard)."""
    out, rem = [], total
    while rem > 11:
        out.append(10); rem -= 10
    # rem now 2..11; if it would duplicate a 10 as a pair it's fine (we only
    # use these for hit/stand, never split), but avoid an ace.
    out.append(rem if rem >= 2 else 2)
    return out


def test_agrees_with_card_path_on_hard_hits_and_stands():
    mismatches = []
    for total in range(8, 21):          # hard 8..20
        for dval in range(2, 12):        # dealer 2..A
            hud = recommend_hard(total, dval).action
            # card-based, doubles/splits disabled so only hit/stand can return
            card = recommend(_hard_ranks(total), _dealer_rank(dval),
                             can_double=False, can_split=False).action
            # surrender isn't offered by recommend_hard; treat as its hit/stand base
            if card == "surrender":
                continue
            if hud != card:
                mismatches.append((total, dval, hud, card))
    assert not mismatches, f"hard-total advice diverged: {mismatches}"


def test_known_spots():
    assert recommend_hard(17, 7).action == STAND
    assert recommend_hard(16, 10).action == HIT          # no count
    assert recommend_hard(16, 10, true_count=0).action == STAND
    assert recommend_hard(12, 3).action == HIT
    assert recommend_hard(12, 4).action == STAND
    assert recommend_hard(11, 10).action == HIT          # totals-only: no double
    assert recommend_hard(20, 11).action == STAND
