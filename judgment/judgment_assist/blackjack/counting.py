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


from collections import Counter


class ShoeCounter:
    """Maintain a Hi-Lo count from frame-by-frame rank reads of the live table.

    A dealt card stays on screen for many frames, so naively counting every read
    would multiply-count it. Instead we track the current hand's rank multiset and
    only credit a rank when MORE of it appears than we've already counted (a hit or
    a freshly revealed card). A hand ends only after a *sustained* run of card-free
    frames (``clear_frames``) — a real between-hands gap lasts seconds, whereas the
    brief no-card blips mid-hand (deal/hit animation, the result screen dimming the
    table) are 1-2 frames; a single card frame resets the empty counter, so a blip
    never splits one hand into two or double-counts its cards. The running count
    carries across hands until ``reset()`` (a reshuffle / new shoe).

    Reads are noisy, so a frame's multiset must repeat for ``confirm`` consecutive
    frames before its growth is credited — a one-frame misread won't bump the count.
    (8 and 9 are both Hi-Lo 0, so the common 8<->9 flicker is count-neutral anyway.)

    LIMITATION: only cards the reader localizes are counted. Dealer cards at the
    table edge often aren't localized, so this is a best-effort count, not yet a
    complete shoe count — improving dealer-card capture is future work (issue #5).
    """

    def __init__(self, decks=6, confirm=2, clear_frames=5):
        self.counter = HiLoCounter(decks=decks)
        self.confirm = confirm
        self.clear_frames = clear_frames
        self._hand = Counter()   # ranks already credited for the hand in progress
        self._stable = None      # last frame's multiset (for the confirm gate)
        self._stable_n = 0
        self._empty_n = 0
        self.hands = 0           # completed hands observed

    def observe(self, ranks):
        """Feed the ranks (rank ints) visible this frame; ``ranks`` may be empty."""
        fc = Counter(int(r) for r in ranks)
        if not fc:
            self._empty_n += 1
            if self._empty_n >= self.clear_frames and self._hand:
                self._hand.clear()          # sustained clear -> hand finished
                self.hands += 1
                self._stable, self._stable_n = None, 0
            return
        self._empty_n = 0
        if fc == self._stable:
            self._stable_n += 1
        else:
            self._stable, self._stable_n = fc, 1
        if self._stable_n < self.confirm:
            return
        for rank, n in fc.items():
            extra = n - self._hand.get(rank, 0)
            for _ in range(max(0, extra)):   # only growth is a new card
                self.counter.see(rank)
            if extra > 0:
                self._hand[rank] = n

    def reset(self):
        """New shoe / reshuffle: zero the running count and per-hand state."""
        self.counter.reset()
        self._hand.clear()
        self._stable, self._stable_n, self._empty_n = None, 0, 0

    @property
    def running(self):
        return self.counter.running

    @property
    def true_count(self):
        return self.counter.true_count

    @property
    def seen(self):
        return self.counter.seen

    def bet_units(self, base=1, spread=8):
        return self.counter.bet_units(base=base, spread=spread)
