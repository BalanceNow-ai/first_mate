"""Supabase access-token verification and role-based authorization.

Tokens are verified with the project's *signing* keys — never with the public anon
key. Two configurations are supported:

* ``AUTH_MODE=jwks``  — asymmetric keys (ES256/RS256/EdDSA) from the project's JWKS URL.
* ``AUTH_MODE=hs256`` — the project's server-only legacy JWT secret.

In both modes the algorithm is constrained, and ``exp``, ``iss``, ``aud`` and ``sub``
are required and checked. Roles come exclusively from ``users.role`` in our database;
token claims and user-editable metadata are never trusted for authorization.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Annotated, Any

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.config import Settings, get_settings
from app.core.errors import AppError
from app.database import get_db
from app.models.user import User

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)
ASYMMETRIC_ALGORITHMS = ["ES256", "RS256", "EdDSA"]
_jwk_clients: dict[str, jwt.PyJWKClient] = {}


@dataclass(frozen=True)
class Principal:
    """The verified identity carried by an access token."""

    subject: uuid.UUID
    email: str | None
    claims: dict[str, Any] = field(repr=False)


def _unauthorized(message: str = "Invalid or expired authentication token") -> AppError:
    return AppError(401, "invalid_token", message, headers={"WWW-Authenticate": "Bearer"})


def _jwk_client(url: str) -> jwt.PyJWKClient:
    client = _jwk_clients.get(url)
    if client is None:
        client = jwt.PyJWKClient(url, cache_keys=True, lifespan=600, timeout=5)
        _jwk_clients[url] = client
    return client


async def verify_access_token(token: str, settings: Settings | None = None) -> Principal:
    """Verify a Supabase access token and return its principal (raises AppError 401)."""
    settings = settings or get_settings()
    options = {"require": ["exp", "iat", "sub", "aud", "iss"]}
    try:
        header = jwt.get_unverified_header(token)
        alg = header.get("alg")
        if settings.auth_mode == "hs256":
            if alg != "HS256" or not settings.supabase_jwt_secret:
                raise _unauthorized()
            key: Any = settings.supabase_jwt_secret
            algorithms = ["HS256"]
        else:
            if alg not in ASYMMETRIC_ALGORITHMS or not settings.jwks_url:
                raise _unauthorized()
            signing_key = await run_in_threadpool(
                _jwk_client(settings.jwks_url).get_signing_key_from_jwt, token
            )
            key = signing_key.key
            algorithms = [alg]
        claims = jwt.decode(
            token,
            key,
            algorithms=algorithms,
            audience=settings.supabase_jwt_audience,
            issuer=settings.jwt_issuer,
            leeway=settings.jwt_leeway_seconds,
            options=options,
        )
    except AppError:
        raise
    except jwt.PyJWKClientError:
        logger.warning("JWKS lookup failed for presented token")
        raise _unauthorized() from None
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Authentication token has expired") from None
    except jwt.InvalidTokenError:
        raise _unauthorized() from None

    if claims.get("role") not in (None, "authenticated"):
        raise _unauthorized()
    if claims.get("is_anonymous") is True:
        raise AppError(403, "anonymous_not_allowed", "Anonymous sessions cannot use this API")
    try:
        subject = uuid.UUID(str(claims["sub"]))
    except (ValueError, KeyError):
        raise _unauthorized() from None
    email = claims.get("email")
    return Principal(subject=subject, email=email.lower() if isinstance(email, str) else None, claims=claims)


async def get_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    """Dependency: the verified token principal (no database lookup)."""
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise _unauthorized("Authentication required")
    principal = await verify_access_token(credentials.credentials)
    request.state.principal = principal
    return principal


async def get_optional_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal | None:
    """Dependency for public endpoints that personalise when a valid token is present."""
    if credentials is None:
        return None
    return await get_principal(request, credentials)


async def get_current_user(
    principal: Annotated[Principal, Depends(get_principal)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Dependency: the provisioned local user bound to the token subject."""
    user = (await db.execute(select(User).where(User.id == principal.subject))).scalar_one_or_none()
    if user is None:
        raise AppError(
            403,
            "profile_not_provisioned",
            "Your account profile has not been created yet. Complete sign-up to continue.",
        )
    return user


async def get_current_user_id(user: Annotated[User, Depends(get_current_user)]) -> uuid.UUID:
    return user.id


def require_roles(*roles: str):
    """Dependency factory: the current user must hold one of ``roles`` (admin implied)."""
    allowed = set(roles) | {"admin"}

    async def _dependency(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in allowed:
            raise AppError(403, "forbidden", "You do not have permission to perform this action")
        return user

    return _dependency


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
OptionalPrincipal = Annotated[Principal | None, Depends(get_optional_principal)]
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentUserId = Annotated[uuid.UUID, Depends(get_current_user_id)]
AdminUser = Annotated[User, Depends(require_roles("admin"))]
DispatcherUser = Annotated[User, Depends(require_roles("dispatcher"))]
OperatorUser = Annotated[User, Depends(require_roles("operator", "dispatcher"))]
