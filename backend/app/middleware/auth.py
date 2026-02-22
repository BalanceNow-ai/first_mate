"""Supabase JWT authentication middleware."""

import json
import uuid
from base64 import urlsafe_b64decode
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings

security = HTTPBearer()
settings = get_settings()

ALGORITHM = "HS256"


def _decode_jwt_payload(token: str) -> dict:
    """Decode a JWT payload without verification (for development)."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format")
    payload_b64 = parts[1]
    # Add padding if needed
    padding = 4 - len(payload_b64) % 4
    if padding != 4:
        payload_b64 += "=" * padding
    payload_bytes = urlsafe_b64decode(payload_b64)
    return json.loads(payload_bytes)


async def get_current_user_id(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
) -> uuid.UUID:
    """Extract and validate user ID from Supabase JWT token.

    In production, this validates the JWT against the Supabase JWT secret
    using PyJWT. In development with no Supabase configured, it falls back
    to extracting the 'sub' claim without full verification.
    """
    token = credentials.credentials

    try:
        if settings.supabase_anon_key:
            import jwt

            payload = jwt.decode(
                token,
                settings.supabase_anon_key,
                algorithms=[ALGORITHM],
                options={"verify_aud": False},
            )
        else:
            # Development fallback: decode without verification
            payload = _decode_jwt_payload(token)

        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing user ID",
            )
        return uuid.UUID(user_id)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication token: {e}",
        )


# Type alias for dependency injection
CurrentUserId = Annotated[uuid.UUID, Depends(get_current_user_id)]
