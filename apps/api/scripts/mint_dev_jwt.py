"""Mint a dev JWT for acceptance scripts — seeds the user and signs locally.

Avoids shipping a token-minting endpoint in the API: acceptance runs on the
same host, so it can reach Postgres and AUTH_SECRET directly.

Usage: uv run python scripts/mint_dev_jwt.py some-email@example.com
Prints the signed token to stdout.
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone

from jose import jwt

from adelia.config import settings
from adelia.db import AsyncSessionLocal
from adelia.models import User


async def main(email: str) -> None:
    if not settings.auth_secret:
        raise SystemExit("AUTH_SECRET not set")
    async with AsyncSessionLocal() as session:
        user = User(email=email)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        user_id = str(user.id)
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    print(jwt.encode(payload, settings.auth_secret, algorithm="HS256"))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
