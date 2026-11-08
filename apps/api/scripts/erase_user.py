"""Erase one guest account by id, the way DELETE /users/me erases an account.

For the test guests that smoke runs and other agents leave behind once their
session is gone (2026-11-08). Inside the API container:

    /app/.venv/bin/python scripts/erase_user.py --id <uuid>          # dry run
    /app/.venv/bin/python scripts/erase_user.py --id <uuid> --yes    # erase

The dry run is the default and changes nothing: it prints how many rows each
table holds for that account, never what they say. With --yes the account goes
through services/account_erasure, the same function the endpoint calls (rows
deleted with their tombstones in one transaction), and then the blob sweep of
its own keys. The endpoint runs that sweep after its 204; a script that exited
first would kill it, so here it is awaited. A blob storage cannot delete now
keeps its tombstone and the hourly sweep retries it, as after the endpoint.

Guests only (users.is_guest). Any other account is refused, and there is no
flag to force it: a mother erases her own account from Settings.

Exit codes: 0 done (or dry run), 1 no account with that id, 3 refused (not a
guest), 2 bad arguments.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path
from typing import TextIO

# This checkout's package first: a worktree may share another checkout's venv.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

NOT_FOUND = 1
REFUSED = 3


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--id", type=uuid.UUID, required=True, help="the guest's users.id")
    parser.add_argument("--yes", action="store_true", help="erase for real (default: dry run)")
    return parser.parse_args(argv)


async def _row_counts(db, user_id: uuid.UUID) -> list[tuple[str, int]]:
    """Rows per table that point at this account: every foreign key to
    users.id, and every `user_id` column, since chunks, entities and chat
    messages carry one and reach the account through their parent's cascade.
    What hangs from those rows without either (a briefing's citations) goes
    with them by ON DELETE CASCADE and is not listed."""
    import sqlalchemy as sa

    from adelia.db import Base

    out: list[tuple[str, int]] = [("users", 1)]
    for table in Base.metadata.sorted_tables:
        columns = {fk.parent.name: fk.parent for fk in table.foreign_keys
                   if fk.column.table.name == "users" and fk.column.name == "id"}
        if table.name != "users" and "user_id" in table.c:
            columns["user_id"] = table.c.user_id
        for name in sorted(columns):
            column = columns[name]
            n = int(await db.scalar(
                sa.select(sa.func.count()).select_from(table).where(column == user_id)) or 0)
            if n:
                label = table.name if column.name == "user_id" else f"{table.name}.{column.name}"
                out.append((label, n))
    return out


async def _guest_or_refusal(db, user_id: uuid.UUID, out: TextIO) -> int | None:
    from adelia.models import User

    user = await db.get(User, user_id)
    if user is None:
        print(f"no account with id {user_id}: nothing to do", file=out)
        return NOT_FOUND
    if not user.is_guest:
        print(f"refused: {user_id} is not a guest account. This script only erases guests;"
              " an account is erased by its owner from Settings.", file=out)
        return REFUSED
    return None


async def run(argv: list[str], out: TextIO = sys.stdout) -> int:
    """The whole command, without disposing the engine (main does)."""
    import sqlalchemy as sa

    from adelia.db import AsyncSessionLocal
    from adelia.models import BlobTombstone, User
    from adelia.routers.users import sweep_blob_tombstones
    from adelia.services import account_erasure

    args = parse_args(argv)
    async with AsyncSessionLocal() as db:
        refusal = await _guest_or_refusal(db, args.id, out)
        if refusal is not None:
            return refusal
        created = await db.scalar(sa.select(User.created_at).where(User.id == args.id))
        counts = await _row_counts(db, args.id)

    width = max(len(label) for label, _ in counts)
    when = created.strftime("%Y-%m-%d %H:%M UTC") if created else "unknown date"
    print(f"guest {args.id}, created {when}", file=out)
    print("rows " + ("to erase:" if args.yes else "that would be erased:"), file=out)
    for label, n in counts:
        print(f"  {label:<{width}}  {n}", file=out)

    if not args.yes:
        print("dry run: nothing was changed. Run again with --yes to erase it.", file=out)
        return 0

    # Checked again in the session that erases: the dry-run read above is
    # already closed and nothing may be erased on a stale answer.
    async with AsyncSessionLocal() as db:
        refusal = await _guest_or_refusal(db, args.id, out)
        if refusal is not None:
            return refusal
        keys = await account_erasure.erase_account(db, args.id)

    # No session is held while storage works (sweep_blob_tombstones).
    if keys:
        await sweep_blob_tombstones(keys=keys)
    async with AsyncSessionLocal() as db:
        left = int(await db.scalar(
            sa.select(sa.func.count()).select_from(BlobTombstone)
            .where(BlobTombstone.s3_key.in_(keys))) or 0) if keys else 0
    print(f"erased. blobs: {len(keys) - left} deleted, {left} left for the hourly sweep",
          file=out)
    return 0


async def _main(argv: list[str]) -> int:
    from adelia.db import engine

    try:
        return await run(argv)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(sys.argv[1:])))
