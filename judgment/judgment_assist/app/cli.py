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
from ..mahjong.tiles import parse_hand, format_hand, hand_size
from ..mahjong.shanten import shanten
from ..mahjong.efficiency import discard_options, format_options, ukeire
from ..mahjong.tiles import tile_name
from ..shogi.board import ShogiState
from ..shogi.engine import UsiEngine, best_move as shogi_best_move


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
    rules = Rules(decks=a.decks, hit_soft_17=a.h17, surrender=a.surrender, split=a.split)
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


# ------------------------------------------------------------------ mahjong ---
def _show_mahjong(spec, seen_spec=None):
    counts = parse_hand(spec)
    seen = parse_hand(seen_spec) if seen_spec else None
    n = hand_size(counts)
    print(f"  hand [{format_hand(counts)}]  ({n} tiles)")
    if n % 3 == 2:  # a 14-tile decision: rank the discards
        opts = discard_options(counts, seen)
        best = opts[0]
        verdict = "WIN — tsumo!" if best["shanten"] < 0 else f"discard {tile_name(best['tile'])}"
        print(f"  -> {verdict}")
        print(format_options(opts))
    else:           # a 13-tile hand: report shanten + what improves it
        sh = shanten(counts)
        state = "WIN" if sh < 0 else "tenpai" if sh == 0 else f"{sh}-shanten"
        print(f"  {state}")
        if sh >= 0:
            accepts, total = ukeire(counts, seen)
            tiles = " ".join(f"{tile_name(t)}({k})" for t, k in accepts) or "—"
            print(f"  ukeire {total}  [{tiles}]")


def run_mahjong(a):
    if a.hand:
        _show_mahjong(a.hand, a.seen)
        return
    print("Mahjong efficiency advisor. Type a hand in riichi notation:")
    print("  e.g.  123m 456m 789m 123p 99s    (14 tiles -> best discard;")
    print("        13 tiles -> shanten + ukeire). 'seen <tiles>' marks dead tiles.")
    seen = None
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        if line in ("quit", "exit", "q"):
            break
        if line.startswith("seen "):
            seen = line[5:]
            print(f"  marking seen: {format_hand(parse_hand(seen))}")
            continue
        try:
            _show_mahjong(line, seen)
        except Exception as e:  # noqa: BLE001 - keep the REPL alive on bad input
            print("  error:", e)


# -------------------------------------------------------------------- shogi ---
def _show_shogi(state, engine, mate_moves, movetime):
    print(state.render())
    if state.is_game_over():
        print("  game over")
        return
    out = shogi_best_move(state, engine=engine, mate_moves=mate_moves, movetime_ms=movetime)
    if out["source"] == "mate":
        print(f"  -> {out['move']}   (forced mate in {out['mate_in']}: {' '.join(out['pv'])})")
    elif out["source"] == "engine":
        print(f"  -> {out['move']}   (engine, {movetime} ms)")
    else:
        print(f"  -> {out['note']}")


def run_shogi(a):
    engine = None
    if a.engine:
        engine = UsiEngine(a.engine).start()
    try:
        state = ShogiState(a.sfen) if a.sfen else ShogiState()
        if a.move:
            for mv in a.move.replace(",", " ").split():
                state.push_usi(mv)
        if a.sfen or a.move:
            _show_shogi(state, engine, a.mate, a.movetime)
            return
        print("Shogi advisor. Commands:")
        print("  sfen <SFEN>     set the position      move <usi...>   play move(s)")
        print("  go              (re)compute advice    show            print board")
        print("  reset           opening position      quit")
        state = ShogiState()
        _show_shogi(state, engine, a.mate, a.movetime)
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            if line in ("quit", "exit", "q"):
                break
            try:
                if line.startswith("sfen "):
                    state = ShogiState(line[5:].strip())
                elif line.startswith("move "):
                    for mv in line[5:].replace(",", " ").split():
                        state.push_usi(mv)
                elif line in ("reset",):
                    state = ShogiState()
                elif line in ("show", "go"):
                    pass
                else:
                    print("  ?  use: sfen / move / go / show / reset / quit"); continue
                _show_shogi(state, engine, a.mate, a.movetime)
            except Exception as e:  # noqa: BLE001 - keep the REPL alive
                print("  error:", e)
    finally:
        if engine is not None:
            engine.close()


# --------------------------------------------------------------------- main ---
def build_parser():
    p = argparse.ArgumentParser(prog="judgment-assist")
    sub = p.add_subparsers(dest="game", required=True)

    bj = sub.add_parser("blackjack", help="blackjack basic-strategy + counting advisor")
    bj.add_argument("--hand", help="your cards, e.g. 'T 6'")
    bj.add_argument("--dealer", help="dealer up card, e.g. 'T'")
    bj.add_argument("--seen", help="cards already seen this shoe (feeds the count)")
    bj.add_argument("--decks", type=int, default=6)
    bj.add_argument("--h17", action="store_true", help="dealer hits soft 17 (Judgment is S17)")
    bj.add_argument("--no-surrender", dest="surrender", action="store_false",
                    help="disable late surrender (Judgment offers it; on by default)")
    bj.add_argument("--no-split", dest="split", action="store_false",
                    help="disable split (set if this game has no Split option)")
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

    mj = sub.add_parser("mahjong", help="riichi shanten/ukeire efficiency advisor")
    mj.add_argument("--hand", help="tiles in riichi notation, e.g. '123m 456m 789m 123p 99s'")
    mj.add_argument("--seen", help="tiles dead elsewhere (discards/dora indicator) for honest ukeire")
    mj.set_defaults(func=run_mahjong)

    sg = sub.add_parser("shogi", help="shogi advisor: forced-mate solver + USI engine")
    sg.add_argument("--sfen", help="position as SFEN (default: opening position)")
    sg.add_argument("--move", help="USI move(s) to play from the position, e.g. '7g7f 3c3d'")
    sg.add_argument("--engine", help="path to a USI engine binary for positional advice")
    sg.add_argument("--mate", type=int, default=7, help="max forced-mate depth to search (attacker moves)")
    sg.add_argument("--movetime", type=int, default=1000, help="engine think time per move (ms)")
    sg.set_defaults(func=run_shogi)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
