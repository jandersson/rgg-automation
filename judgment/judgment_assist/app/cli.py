"""Manual advisor CLI — usable right now, no screen capture required.

Read your cards off the screen and type them; get the optimal play.

One-shot:
    py -m judgment_assist.app.cli blackjack --hand "T 6" --dealer T
    py -m judgment_assist.app.cli poker --hole "Ah As" --board "Kh 7c 2d" --opp 3 --pot 200 --to-call 50

Interactive (no --hand/--hole given):
    py -m judgment_assist.app.cli blackjack
    py -m judgment_assist.app.cli poker
"""
import argparse
import sys

from ..cards import parse_cards, cards_str, RANK_TO_INT, INT_TO_RANK
from ..blackjack.engine import BlackjackAdvisor, Rules
from ..blackjack.strategy import hand_total
from ..poker.advisor import advise


# ---------------------------------------------------------------- blackjack ---
def _ranks(spec):
    """Parse cards for blackjack where only rank matters ('T 6' or 'Th 6c')."""
    out = []
    for tok in spec.replace(",", " ").split():
        ch = tok[0].upper()
        if ch not in RANK_TO_INT:
            raise SystemExit(f"bad card {tok!r}")
        out.append(RANK_TO_INT[ch])
    return out


def _show_bj(adv, hand, up):
    total, soft = hand_total(hand)
    dec = adv.advise(hand, up)
    tc = adv.counter.true_count
    take_ins, _ = adv.insurance()
    hand_s = " ".join(INT_TO_RANK[r] for r in hand)
    print(f"  hand [{hand_s}] = {total}{' soft' if soft else ''}  vs dealer {INT_TO_RANK[up]}")
    print(f"  -> {dec.action.upper():9} ({dec.reason})")
    line = f"  true count {tc:+.1f}   suggested bet {adv.bet_units()}u"
    if take_ins and up == 14:
        line += "   | TAKE INSURANCE (count is high)"
    print(line)


def run_blackjack(a):
    rules = Rules(decks=a.decks, hit_soft_17=a.h17, surrender=a.surrender)
    adv = BlackjackAdvisor(rules)
    if a.seen:
        adv.observe(_ranks(a.seen))

    if a.hand and a.dealer:
        _show_bj(adv, _ranks(a.hand), _ranks(a.dealer)[0])
        return

    print("Blackjack advisor (decks=%d, %s). Per hand type:  <your cards> / <dealer up>"
          % (a.decks, "H17" if a.h17 else "S17"))
    print("Other commands:  seen <cards>   reset   bet   quit")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        if line in ("quit", "exit", "q"):
            break
        if line == "reset":
            adv.counter.reset(); print("  count reset"); continue
        if line == "bet":
            print(f"  true count {adv.counter.true_count:+.1f}  bet {adv.bet_units()}u"); continue
        if line.startswith("seen "):
            adv.observe(_ranks(line[5:])); print(f"  count {adv.counter.true_count:+.1f}"); continue
        if "/" not in line:
            print("  format: <your cards> / <dealer up>   e.g.  T 6 / T"); continue
        hand_s, up_s = line.split("/", 1)
        try:
            _show_bj(adv, _ranks(hand_s), _ranks(up_s)[0])
        except SystemExit as e:
            print(" ", e)


# -------------------------------------------------------------------- poker ---
def _show_poker(a):
    hole = parse_cards(a.hole)
    board = parse_cards(a.board) if a.board else []
    out = advise(hole, board, opponents=a.opp, to_call=a.to_call, pot=a.pot,
                 iters=a.iters, seed=a.seed)
    stage = {0: "preflop", 3: "flop", 4: "turn", 5: "river"}.get(len(board), f"{len(board)} cards")
    print(f"  {cards_str(hole)} | board [{cards_str(board)}] ({stage}) vs {a.opp} opp")
    if "made_hand" in out:
        print(f"  made hand: {out['made_hand']}")
    print(f"  equity {out['equity']*100:5.1f}%   (win {out['win']*100:.1f} / tie {out['tie']*100:.1f} / lose {out['lose']*100:.1f})")
    if a.to_call > 0:
        print(f"  pot odds {out['pot_odds']*100:.1f}%   call EV {out['call_ev_chips']:+.1f} chips")
    print(f"  -> {out['recommendation'].upper()}")


def run_poker(a):
    if a.hole:
        _show_poker(a)
        return
    print("Poker (Hold'em) advisor. Type:  <hole> | <board> | <opponents> [pot] [to_call]")
    print("  e.g.  Ah As | Kh 7c 2d | 3 | 200 | 50      (board/opp/pot/call optional)")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        if line in ("quit", "exit", "q"):
            break
        parts = [p.strip() for p in line.split("|")]
        a.hole = parts[0]
        a.board = parts[1] if len(parts) > 1 and parts[1] else ""
        a.opp = int(parts[2]) if len(parts) > 2 and parts[2] else a.opp
        a.pot = float(parts[3]) if len(parts) > 3 and parts[3] else 0
        a.to_call = float(parts[4]) if len(parts) > 4 and parts[4] else 0
        try:
            _show_poker(a)
        except Exception as e:  # noqa: BLE001 - keep the REPL alive on bad input
            print("  error:", e)


# --------------------------------------------------------------------- main ---
def build_parser():
    p = argparse.ArgumentParser(prog="judgment-assist")
    sub = p.add_subparsers(dest="game", required=True)

    bj = sub.add_parser("blackjack", help="blackjack basic-strategy + counting advisor")
    bj.add_argument("--hand", help="your cards, e.g. 'T 6'")
    bj.add_argument("--dealer", help="dealer up card, e.g. 'T'")
    bj.add_argument("--seen", help="cards already seen this shoe (feeds the count)")
    bj.add_argument("--decks", type=int, default=6)
    bj.add_argument("--h17", action="store_true", help="dealer hits soft 17")
    bj.add_argument("--surrender", action="store_true", help="late surrender allowed")
    bj.set_defaults(func=run_blackjack)

    pk = sub.add_parser("poker", help="Texas Hold'em equity + pot-odds advisor")
    pk.add_argument("--hole", help="your two hole cards, e.g. 'Ah As'")
    pk.add_argument("--board", default="", help="community cards, e.g. 'Kh 7c 2d'")
    pk.add_argument("--opp", type=int, default=1, help="number of opponents")
    pk.add_argument("--pot", type=float, default=0)
    pk.add_argument("--to-call", dest="to_call", type=float, default=0)
    pk.add_argument("--iters", type=int, default=20000)
    pk.add_argument("--seed", type=int, default=None)
    pk.set_defaults(func=run_poker)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
