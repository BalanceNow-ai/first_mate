"""Identity: idempotent local profile provisioning bound to the verified token subject.

Sign-up, sign-in, refresh and sign-out happen against Supabase Auth from the client.
This router only mirrors the verified identity into a local profile. The user id and
email are taken from the verified access token — never from the request body.
"""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.rate_limit import auth_limit
from app.database import get_db, utcnow
from app.middleware.auth import CurrentPrincipal, CurrentUser
from app.models.user import User
from app.schemas.user import ProvisionRequest, ProvisionResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])


async def _provision(
    body: ProvisionRequest, principal: CurrentPrincipal, response: Response, db: AsyncSession
) -> ProvisionResponse:
    existing = await db.get(User, principal.subject)
    if existing is not None:
        changed = False
        if body.full_name and not existing.full_name:
            existing.full_name, changed = body.full_name, True
        if body.phone and not existing.phone:
            existing.phone, changed = body.phone, True
        if changed:
            await db.flush()
        response.status_code = status.HTTP_200_OK
        return ProvisionResponse.model_validate(existing).model_copy(update={"created": False})

    if not principal.email:
        raise AppError(400, "email_required", "Your sign-in does not include an email address")
    clash = (
        await db.execute(select(User).where(func.lower(User.email) == principal.email))
    ).scalar_one_or_none()
    if clash is not None:
        # The email belongs to a different identity (e.g. a deleted and re-created auth
        # account). Never re-bind another account's data to this subject.
        raise AppError(
            409,
            "email_bound_to_other_account",
            "This email is already linked to a different account. Contact support.",
        )

    user = User(
        id=principal.subject,
        email=principal.email,
        full_name=body.full_name,
        phone=body.phone,
        role="customer",
        email_verified_at=utcnow(),
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        # Concurrent provisioning of the same subject: return the winner's row.
        await db.rollback()
        winner = await db.get(User, principal.subject)
        if winner is None:
            raise AppError(409, "provisioning_conflict", "Account could not be provisioned") from None
        response.status_code = status.HTTP_200_OK
        return ProvisionResponse.model_validate(winner).model_copy(update={"created": False})
    response.status_code = status.HTTP_201_CREATED
    return ProvisionResponse.model_validate(user).model_copy(update={"created": True})


@router.post(
    "/provision",
    response_model=ProvisionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(auth_limit())],
)
async def provision_profile(
    body: ProvisionRequest,
    principal: CurrentPrincipal,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> ProvisionResponse:
    """Create (201) or return (200) the local profile for the authenticated subject."""
    return await _provision(body, principal, response, db)


@router.post(
    "/register",
    response_model=ProvisionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(auth_limit())],
    deprecated=True,
)
async def register_user(
    body: ProvisionRequest,
    principal: CurrentPrincipal,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> ProvisionResponse:
    """Deprecated alias of ``/auth/provision`` (identity always comes from the token)."""
    return await _provision(body, principal, response, db)


@router.get("/me", response_model=UserResponse)
async def get_me(user: CurrentUser) -> User:
    """The authenticated user's profile (403 ``profile_not_provisioned`` if absent)."""
    return user
