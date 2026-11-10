"""Command line entry points: `carbon <command>` and the carbon_start/_end/_report aliases."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .paths import Failure, UsageError


def _setup_streams() -> None:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                pass


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="carbon",
        description="Track the energy, emissions and token usage of AI-assisted coding.",
    )
    p.add_argument("--version", action="version", version=f"carbon-skill {__version__}")
    sub = p.add_subparsers(dest="command", metavar="command")

    run_help = "a label (its newest run) or @<id>; default: this session's run"
    s = sub.add_parser("start", help="begin tracking a new run; returns within a few seconds")
    s.add_argument("label", nargs="?")
    s = sub.add_parser("end", help="stop, then print the report")
    s.add_argument("label", nargs="?", help=run_help)
    s = sub.add_parser("report", help="report for a past or live run")
    s.add_argument("label", nargs="?", help=run_help)
    s = sub.add_parser("compare", help="two runs side by side, with deltas")
    s.add_argument("a", metavar="A", help="first run (or the idle run with --baseline): label or @<id>")
    s.add_argument("b", metavar="B", help="second run (or the task run with --baseline): label or @<id>")
    s.add_argument("--baseline", action="store_true", help="subtract idle run A, scaled to B's duration, from B")
    s = sub.add_parser("list", aliases=["history"], help="every run, newest first, with totals")
    s.add_argument("--session", action="store_true", help="only runs started from this session")
    s.add_argument("--label", help="only runs with this label")
    s.add_argument("-n", type=int, default=20, help="show the newest N (default 20; 0 for all)")
    s = sub.add_parser("delete", help="delete one stopped run")
    s.add_argument("label", help="a label (deletes its newest run) or @<id>")
    s = sub.add_parser("export", help="a run's samples as CodeCarbon CSV, or the database as SQL")
    s.add_argument("label", nargs="?", help=run_help + " (not with --format sql)")
    s.add_argument("--format", choices=["csv", "sql"], default="csv")
    s.add_argument("-o", "--output", metavar="FILE", help="write to FILE instead of stdout")
    s = sub.add_parser("install-skill", help="install the skill into your coding agent(s)")
    s.add_argument("--agent", default="all", choices=["claude-code", "codex", "all"])
    s.add_argument("--remove", action="store_true", help="remove the skill folders this program installed")
    s.add_argument("--force", action="store_true", help="replace a carbon skill this program did not install (backed up first)")
    s = sub.add_parser("doctor", help="check the installation")
    s.add_argument("--no-measure", action="store_true", help="skip the 12-second test measurement")
    return p


def _dispatch(args: argparse.Namespace) -> int:
    cmd = args.command
    if cmd == "start":
        from . import start

        return start.command(args.label)
    if cmd == "end":
        from . import end

        return end.command_end(args.label)
    if cmd == "report":
        from . import end

        return end.command_report(args.label)
    if cmd in ("list", "history"):
        from . import end

        return end.command_list(args.session, args.label, args.n)
    if cmd == "delete":
        from . import end

        return end.command_delete(args.label)
    if cmd == "export":
        from . import export

        return export.command(args.label, args.format, args.output)
    if cmd == "compare":
        from . import compare

        return compare.command(args.a, args.b, args.baseline)
    if cmd == "install-skill":
        from . import agents

        return agents.command(args.agent, args.remove, args.force)
    if cmd == "doctor":
        from . import doctor

        return doctor.command(measure=not args.no_measure)
    _parser().print_help()
    return 2


def main(argv: list[str] | None = None) -> int:
    _setup_streams()
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["_monitor"]:
        if len(argv) != 2:
            print("usage: carbon _monitor <run id>", file=sys.stderr)
            return 2
        from . import monitor

        return monitor.run(argv[1])
    try:
        return _dispatch(_parser().parse_args(argv))
    except UsageError as exc:
        print(f"carbon: {exc}", file=sys.stderr)
        return 2
    except Failure as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


def _alias(command: str) -> int:
    return main([command, *sys.argv[1:]])


def main_start() -> int:
    return _alias("start")


def main_end() -> int:
    return _alias("end")


def main_report() -> int:
    return _alias("report")
