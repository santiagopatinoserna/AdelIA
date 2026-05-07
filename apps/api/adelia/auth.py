from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from adelia.config import settings


bearer_scheme = HTTPBearer()


def decode_session_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.auth_secret, algorithms=["HS256"])


async def get_current_user_id(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
) -> UUID:
    try:
        payload = decode_session_token(credentials.credentials)
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
        return UUID(sub)
    except ValueError:
        raise HTTPException(status_code=401, detail="Token sub is not a valid UUID")
