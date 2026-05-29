"""Blackjack advisor: ties basic strategy + Hi-Lo counting together and layers
in Judgment's house rules (Six-Card Charlie, insurance from the count)."""
from dataclasses import dataclass, field

from .strategy import recommend, hand_total, bust_probability, Decision, HIT
from .counting import HiLoCounter


@dataclass
class Rules:
    decks: int = 6                 # unknown for Judgment until measured
    hit_soft_17: bool = False
    das: bool = True               # double after split
    surrender: bool = False
    charlie: int = 6               # six-card charlie auto-win
    blackjack_pays: float = 2.5    # Judgment pays 2.5x the bet for a natural
    insurance_tc: float = 3.0      # take insurance at/above this true count
    charlie_hit_threshold: float = 0.5  # push for charlie while bust prob below this


@dataclass
class BlackjackAdvisor:
    rules: Rules = field(default_factory=Rules)
    counter: HiLoCounter = None

    def __post_init__(self):
        if self.counter is None:
            self.counter = HiLoCounter(self.rules.decks)

    def observe(self, ranks):
        """Feed every card you see (yours, other players', dealer's) to the count."""
        self.counter.see_many(ranks)

    def insurance(self):
        """Return ``(take: bool, true_count)``. Only +EV when the deck is rich
        in tens, i.e. a high count — and only if it's a persistent shoe."""
        tc = self.counter.true_count
        return tc >= self.rules.insurance_tc, tc

    def bet_units(self, base=1, spread=8):
        return self.counter.bet_units(base, spread)

    def advise(self, player_ranks, dealer_up, can_double=True, can_split=True):
        total, _soft = hand_total(player_ranks)
        n = len(player_ranks)

        # Six-Card Charlie: one card short of an automatic win and not yet bust.
        # Reaching `charlie` cards without busting wins outright, so it's usually
        # right to hit a stiff hand here even when basic strategy would stand.
        if total <= 21 and self.rules.charlie - 1 <= n < self.rules.charlie:
            pb = bust_probability(player_ranks)
            if pb < self.rules.charlie_hit_threshold:
                return Decision(HIT, f"hit for six-card charlie (bust≈{pb:.0%}, "
                                     f"{self.rules.charlie - n} card to auto-win)")

        return recommend(
            player_ranks, dealer_up,
            can_double=can_double,
            can_split=can_split,
            can_surrender=self.rules.surrender,
            true_count=self.counter.true_count,
            hit_soft_17=self.rules.hit_soft_17,
        )
