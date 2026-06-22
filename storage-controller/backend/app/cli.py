"""Command-line entry point.

Usage:
    storage-controller seed-demo     # idempotently load demo storage units
    storage-controller seed-profiles # (re)seed built-in monitoring profiles
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from .db import dispose_engine, get_session_factory
from .logging_config import configure_logging
from .seed import seed_built_in_profiles, seed_demo_data


async def _seed_demo() -> None:
    factory = get_session_factory()
    async with factory() as session:
        await seed_built_in_profiles(session)
        created = await seed_demo_data(session)
    print(f"Demo seed complete. Created {created} storage unit(s).")
    await dispose_engine()


async def _seed_profiles() -> None:
    factory = get_session_factory()
    async with factory() as session:
        created = await seed_built_in_profiles(session)
    print(f"Built-in profiles synced. Created {created} new profile(s).")
    await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    configure_logging("INFO")
    parser = argparse.ArgumentParser(prog="storage-controller")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed-demo", help="Idempotently load demo storage units")
    sub.add_parser("seed-profiles", help="(Re)seed built-in monitoring profiles")

    args = parser.parse_args(argv)
    if args.command == "seed-demo":
        asyncio.run(_seed_demo())
    elif args.command == "seed-profiles":
        asyncio.run(_seed_profiles())
    return 0


if __name__ == "__main__":
    sys.exit(main())
