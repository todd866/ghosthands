"""Smallest possible demo: no LLM, just prove the hands work by tracing a square."""
import argparse
import time
from ghosthands import make_hands

parser = argparse.ArgumentParser()
parser.add_argument("--live", action="store_true", help="confirm real mouse/keyboard input")
parser.add_argument("--port")
args = parser.parse_args()
if not args.live:
    parser.error("this moves the real pointer and types; re-run with --live")

h = make_hands("pico", port=args.port)
print("ping:", h.ping())
pts = [(0.35, 0.35), (0.65, 0.35), (0.65, 0.65), (0.35, 0.65), (0.35, 0.35)]
for x, y in pts:
    print(h.move(x, y)); time.sleep(0.3)
print(h.type("ghosthands was here"))
