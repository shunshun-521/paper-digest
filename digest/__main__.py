"""CLI: python -m digest run [--dry-run] [--date YYYY-MM-DD]."""

from __future__ import annotations

import argparse
import sys

from digest.pipeline import run


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="digest")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run", help="build and deliver today's digest")
    run_parser.add_argument("--dry-run", action="store_true", help="use fixtures, write out/, do not send")
    run_parser.add_argument("--date", default=None, help="YYYY-MM-DD, default is today in Asia/Shanghai")
    args = parser.parse_args(argv)
    if args.command == "run":
        code = run(dry_run=args.dry_run, on_date=args.date)
        raise SystemExit(code)


if __name__ == "__main__":
    main(sys.argv[1:])
