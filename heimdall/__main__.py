import asyncio
import sys
from argparse import ArgumentParser
from pathlib import Path

from .entrypoints import cli, serve


def main(
    argv: list[str] | None = None,
) -> int:
    if argv is None:
        argv = sys.argv[1:]
        invoked = Path(sys.argv[0]).name
        if invoked in {"cli", "serve"} and not argv:
            argv = [invoked]

    parser = ArgumentParser(
        prog="heimdall",
        description="DevOps agent for a homelab",
    )
    commands = parser.add_subparsers(dest="command", required=False)
    commands.add_parser("cli", help="connect to a running agent REPL")
    commands.add_parser("serve", help="run the agent control API")

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    if args.command == "cli":
        return asyncio.run(cli())
    elif args.command == "serve":
        return asyncio.run(serve())
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    raise SystemExit(main(argv=sys.argv[1:]))
