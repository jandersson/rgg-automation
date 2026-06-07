"""A minimal stand-in USI engine for tests — speaks just enough of the protocol
to exercise judgment_assist.shogi.engine.UsiEngine without a real binary.

It always recommends ``7g7f`` (a legal opening move) so the driver round-trip is
deterministic. Launched as ``[sys.executable, this_file]``.
"""
import sys


def main():
    for line in sys.stdin:
        cmd = line.strip()
        if cmd == "usi":
            print("id name mock-usi")
            print("usiok")
        elif cmd == "isready":
            print("readyok")
        elif cmd.startswith("go"):
            print("bestmove 7g7f")
        elif cmd == "quit":
            break
        # setoption / position / usinewgame: accept silently
        sys.stdout.flush()


if __name__ == "__main__":
    main()
