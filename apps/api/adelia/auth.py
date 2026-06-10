from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from adelia.config import settings


bearer_scheme = HTTPBearer()


def decode_session_token(token: str) -> dict[str, Any]:
    if not settings.auth_secret:
        # An empty secret would happily verify tokens signed with "" —
        # i.e. anyone could forge a session. Refuse to authenticate at all.
        raise RuntimeError("AUTH_SECRET not configured")
    return jwt.decode(token, settings.auth_secret, algorithms=["HS256"])


async def get_current_user_id(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
) -> UUID:
    try:
        payload = decode_session_token(credentials.credentials)
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server auth not configured",
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Token missing sub")
    try:
        user_id = UUID(sub)
    except ValueError:
        raise HTTPException(status_code=401, detail="Token sub is not a valid UUID")

    # Tokens must not outlive the account (GDPR erasure): a JWT is only a
    # claim — the user row is the source of truth.
    from adelia.db import AsyncSessionLocal
    from adelia.models import User

    async with AsyncSessionLocal() as session:
        exists = await session.get(User, user_id)
    if exists is None:
        raise HTTPException(status_code=401, detail="Unknown user")
    return user_id
