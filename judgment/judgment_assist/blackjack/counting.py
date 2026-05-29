"""Hi-Lo card counting.

Hi-Lo tag: 2-6 = +1, 7-9 = 0, 10/J/Q/K/A = -1. True count = running count /
decks remaining. Bet sizing ramps with the true count.

NOTE: counting only earns anything if Judgment deals from a *persistent shoe*.
If the game reshuffles every hand, the running count resets each hand and the
true count is meaningless — call ``reset()`` on every reshuffle. The capture
layer is meant to detect reshuffles so we can confirm which world we're in.
"""

# keyed by rank int (2..14); 11=J 12=Q 13=K 14=A all count as -1
HILO = {2: 1, 3: 1, 4: 1, 5: 1, 6: 1, 7: 0, 8: 0, 9: 0,
        10: -1, 11: -1, 12: -1, 13: -1, 14: -1}


class HiLoCounter:
    def __init__(self, decks=6):
        self.decks = decks
        self.running = 0
        self.seen = 0

    def see(self, rank):
        self.running += HILO[rank]
        self.seen += 1

    def see_many(self, ranks):
        for r in ranks:
            self.see(r)

    @property
    def decks_remaining(self):
        # floor at quarter-deck so true count stays finite near the cut card
        return max(0.25, (52 * self.decks - self.seen) / 52.0)

    @property
    def true_count(self):
        return self.running / self.decks_remaining

    def bet_units(self, base=1, spread=8):
        """Simple 1-to-`spread` ramp: bet ``max(1, floor(true_count))`` units,
        capped at ``spread``. Below TC 1, bet the base unit."""
        tc = self.true_count
        if tc < 1:
            return base
        return base * min(spread, int(tc))

    def reset(self):
        """Call on a detected reshuffle."""
        self.running = 0
        self.seen = 0
