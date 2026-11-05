"""``python -m app.cli <command>`` — discovers commands from modules in this package."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
import pkgutil
import sys

import app.cli as pkg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    for info in sorted(pkgutil.iter_modules(pkg.__path__), key=lambda m: m.name):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"app.cli.{info.name}")
        if hasattr(module, "register"):
            module.register(sub)
    args = parser.parse_args(argv)
    result = args.handler(args)
    if inspect.isawaitable(result):
        result = asyncio.run(result)
    return int(result or 0)


if __name__ == "__main__":
    sys.exit(main())
