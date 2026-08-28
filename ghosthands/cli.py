"""Command-line entry point for ghosthands."""
import argparse
import importlib.util
import os
import sys

from .agent import Agent
from .brain import Grounder, Planner
from .config import Config
from .hands import PicoHands, discover_pico_port, make_hands, serial_ports


def load_task(path):
    spec = importlib.util.spec_from_file_location("gh_task", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load task file %s" % path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.GOAL, mod.GUIDE, getattr(mod, "MAX_STEPS", 20)


def doctor(ping=False, port=None):
    """Print board discovery details and optionally verify the firmware handshake."""
    ports = serial_ports()
    print("Serial devices:")
    if not ports:
        print("  (none)")
    for serial_port in ports:
        detail = getattr(serial_port, "description", "") or "unknown device"
        print("  %s  %s" % (getattr(serial_port, "device", "?"), detail))
    try:
        selected = discover_pico_port(ports, explicit_port=port)
    except RuntimeError as exc:
        print("Board: not ready - %s" % exc)
        return 1
    print("Board: %s" % selected)
    if ping:
        reply = PicoHands(selected).ping()
        print("Ping: %s" % (reply or "no response"))
        if not (reply.get("ok") and reply.get("pong") and reply.get("kbd") and reply.get("abs_mouse")):
            return 1
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="ghosthands")
    parser.add_argument("--goal-file")
    parser.add_argument("--goal")
    parser.add_argument("--guide", default="")
    parser.add_argument("--run-dir", default=None)
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("--hands", choices=("pico", "dryrun"), default=None)
    parser.add_argument("--port", help="explicit board serial port (otherwise auto-detect)")
    parser.add_argument("--live", action="store_true", help="confirm that real HID actions may run")
    parser.add_argument("--doctor", action="store_true", help="show board/serial readiness and exit")
    parser.add_argument("--ping", action="store_true", help="with --doctor, ping the flashed board")
    parser.add_argument(
        "--allow-browser-navigation", action="store_true",
        help="allow navigate actions to control Safari with AppleScript",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.doctor:
        return doctor(ping=args.ping, port=args.port)
    if args.ping:
        print("--ping requires --doctor", file=sys.stderr)
        return 2
    if args.goal_file:
        goal, guide, max_steps = load_task(args.goal_file)
    elif args.goal:
        goal, guide, max_steps = args.goal, args.guide, args.max_steps
    else:
        print("need --goal-file or --goal", file=sys.stderr)
        return 2
    if not Config.api_key:
        print("no OPENROUTER_API_KEY (env or ~/.config/ghosthands/openrouter.env)", file=sys.stderr)
        return 2

    backend = args.hands or Config.hands_backend
    if backend == "pico" and not args.live:
        print("real HID is locked; add --live after checking the goal and run directory", file=sys.stderr)
        return 2
    hands = make_hands(backend, port=args.port)
    # A dry run must never mutate browser state. For real runs, navigation is also
    # opt-in because it bypasses the hardware hands.
    browser_nav = backend != "dryrun" and args.allow_browser_navigation
    agent = Agent(Planner(), Grounder(), hands, run_dir=args.run_dir, browser_nav=browser_nav)
    print("planner=%s grounder=%s hands=%s run_dir=%s" % (
        Config.planner_model, Config.grounder_model, backend, agent.run_dir
    ))
    print("stop before the next action: touch %s" % os.path.join(agent.run_dir, "ABORT"))
    try:
        result = agent.run(goal, guide, max_steps=max_steps)
    except KeyboardInterrupt:
        print("interrupted; releasing held keys/buttons")
        result = "aborted"
    finally:
        try:
            hands.release_all()
        except Exception as exc:
            print("warning: could not confirm key/button release: %s" % exc, file=sys.stderr)
    print("RESULT:", result)
    return 0 if result == "done" else 1
