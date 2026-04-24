"""CLI: python -m app.cli ingest --limit 5"""

from __future__ import annotations

import argparse
import asyncio
import os
# Ensure .env in project root is loadable; pydantic-settings uses cwd.
def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    in_p = sub.add_parser("ingest", help="Fetch FCL feed, store cases + BGE chunks")
    in_p.add_argument(
        "--limit",
        type=int,
        default=30,
        help="How many new cases to add (default 30; skips URLs already in DB)",
    )
    in_p.add_argument(
        "--pages",
        type=int,
        default=15,
        help="Max Atom feed pages to walk until limit new cases (default 15)",
    )
    in_p.add_argument(
        "--include-existing",
        action="store_true",
        help="Re-fetch all from feed, including URs already in DB (re-embed/refresh)",
    )
    args = p.parse_args()
    if args.cmd == "ingest":
        asyncio.run(_ingest(args))


async def _ingest(args: argparse.Namespace) -> None:
    from app.db import close_pool, get_pool
    from app.services import ingestion

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    os.chdir(root)

    pool = await get_pool()
    try:
        r = await ingestion.run_ingestion(
            pool,
            limit=args.limit,
            max_feed_pages=args.pages,
            skip_existing=not args.include_existing,
        )
        print(r)
    finally:
        await close_pool()


if __name__ == "__main__":
    main()
