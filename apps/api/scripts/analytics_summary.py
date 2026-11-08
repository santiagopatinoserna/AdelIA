"""Print the analytics summary as JSON, straight from the database.

The same document GET /analytics/summary returns to an admin, for a local
backoffice or a quick look on the server without a browser session:

    uv --directory apps/api run python scripts/analytics_summary.py --days 30 > summary.json

It reads the database named by the usual settings (.env / environment) and
writes nothing.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys


async def _main(days: int) -> None:
    from adelia.db import engine
    from adelia.services import analytics

    try:
        data = await analytics.summary(days)
    finally:
        await engine.dispose()
    json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=30)
    asyncio.run(_main(parser.parse_args().days))
