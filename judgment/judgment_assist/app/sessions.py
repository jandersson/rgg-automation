"""Report on tracked game sessions — spot if something is off.

    py -m judgment_assist.app.sessions data/sessions/sessions.db

Prints the outcome distribution (vs a rough basic-strategy baseline), the dealer
up-card distribution (with a uniformity chi-square), and the player-total spread.
Large deviations point at either the game (unfair deal / odd rules) or our own
pipeline (reader misreads) — the next step is then to dig into the offending
signal, not to trust the headline.
"""
from __future__ import annotations

import argparse
import os

from ..sessions import summarize


def _bar(frac, width=24):
    fill = int(round(frac * width))
    return "#" * fill + "-" * (width - fill)


def format_report(s):
    out = [f"sessions: {s['sessions']}   hands: {s['hands']}"]
    if not s["hands"]:
        out.append("  (no hands recorded yet)")
        return "\n".join(out)

    n = s["hands"]
    out.append("\noutcomes (observed % / baseline %):")
    base = s["outcome_baseline"]
    for k in sorted(s["outcomes"], key=lambda k: -s["outcomes"][k]):
        c = s["outcomes"][k]
        frac = c / n
        b = base.get(k)
        btxt = f"  base ~{b*100:.0f}%" if b is not None else ""
        out.append(f"  {k:10s} {c:4d}  {frac*100:5.1f}%  {_bar(frac)}{btxt}")

    out.append("\ndealer up-card:")
    du = s["dealer_up"]
    dtot = sum(du.values()) or 1
    for v in sorted(du):
        label = {11: "A", 10: "10"}.get(v, str(v))
        out.append(f"  {label:>3}  {du[v]:4d}  {_bar(du[v]/dtot)}")
    chi = s["dealer_chi_square"]
    if chi:
        flag = "  <-- looks non-uniform, investigate" if chi["chi2"] > 2.5 * chi["dof"] else ""
        out.append(f"  chi-square vs fair deck: {chi['chi2']} (dof {chi['dof']}, n={chi['total']}){flag}")
    else:
        out.append("  (need >=20 dealer up-cards for a uniformity check)")

    out.append("\nplayer total spread: " +
               ", ".join(f"{k}:{v}" for k, v in s["player_total"].items()))
    return "\n".join(out)


def main(argv=None):
    p = argparse.ArgumentParser(prog="judgment-assist sessions")
    p.add_argument("db", help="path to the session SQLite DB (live --db)")
    a = p.parse_args(argv)
    if not os.path.exists(a.db):
        raise SystemExit(f"no DB at {a.db} — run the live advisor with --db {a.db} first")
    print(format_report(summarize(a.db)))


if __name__ == "__main__":
    main()
