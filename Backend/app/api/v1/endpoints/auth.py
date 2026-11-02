import secrets
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.api.deps import (
    AuthContext,
    CurrentUser,
    RedisDep,
    SessionDep,
    get_auth_context,
    rate_limit,
)
from app.core.config import settings
from app.core.exceptions import BadRequest, Forbidden, Unauthorized
from app.models.rider_application import DocumentKind
from app.models.user import User, UserRole
from app.schemas.auth import (
    AuthResponse,
    ForgotPasswordRequest,
    GoogleSignIn,
    HandoffRedeem,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    RiderSignup,
    TokenPair,
    UserRead,
)
from app.services import auth_service, google_auth, rider_applications

router = APIRouter(prefix="/auth", tags=["AUTHENTICATION"])


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("register", 10))],
)
async def register(data: RegisterRequest, session: SessionDep):
    """Creates a customer account and logs it in. Admin accounts can only be created
    by an existing admin (POST /admin/users)."""
    user = await auth_service.register(session, data)
    tokens = auth_service.issue_tokens(user)
    return AuthResponse(**tokens.model_dump(), user=UserRead.model_validate(user))


async def _rider_signup_form(
    full_name: Annotated[str, Form()], phone: Annotated[str, Form()],
    vehicle_type: Annotated[str, Form()], id_type: Annotated[str, Form()],
    id_number: Annotated[str, Form()],
    email: Annotated[str | None, Form()] = None, password: Annotated[str | None, Form()] = None,
    google_id_token: Annotated[str | None, Form(description="Instead of email + password")] = None,
    plate_number: Annotated[str | None, Form()] = None, area: Annotated[str | None, Form()] = None,
    note: Annotated[str | None, Form()] = None,
) -> tuple[RiderSignup, str | None]:
    """The sign-up fields arrive as a multipart form (alongside the ID photos); validate
    them with the same rules as JSON. With a Google token, the email comes from Google
    (verified) and no password is needed."""
    google_sub = None
    if google_id_token:
        claims = await google_auth.verify(google_id_token)
        email, google_sub = claims["email"], claims["sub"]
        password = secrets.token_urlsafe(32)  # unusable: they sign in with Google
    try:
        data = RiderSignup(full_name=full_name, phone=phone, email=email, password=password,
                           vehicle_type=vehicle_type, id_type=id_type, id_number=id_number,
                           plate_number=plate_number, area=area, note=note)
    except ValidationError as e:
        raise RequestValidationError(e.errors(include_url=False)) from None
    return data, google_sub


@router.post("/rider-signup", status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(rate_limit("rider-signup", 5))])
async def rider_signup(
    form: Annotated[tuple[RiderSignup, str | None], Depends(_rider_signup_form)], session: SessionDep,
    id_front: Annotated[UploadFile, File(description="Photo/PDF of the ID card (front)")],
    selfie: Annotated[UploadFile, File(description="A clear photo of the applicant's face")],
    id_back: Annotated[UploadFile | None, File(description="Back of the ID card (optional)")] = None,
) -> dict:
    """"Become a rider" from the rider app (multipart form: the fields plus ID photos).
    The account can't sign in until an admin approves it; the applicant is texted the decision.
    ID documents are stored privately: only admins can view them, and each view is audited."""
    documents = {}
    for kind, upload in ((DocumentKind.ID_FRONT, id_front), (DocumentKind.ID_BACK, id_back),
                         (DocumentKind.SELFIE, selfie)):
        if upload is None:
            continue
        blob = await upload.read(settings.MAX_UPLOAD_BYTES + 1)
        if len(blob) > settings.MAX_UPLOAD_BYTES:
            raise BadRequest(f"The {kind.value.replace('_', ' ')} file is too big "
                             f"(max {settings.MAX_UPLOAD_BYTES // (1024 * 1024)} MB)", code="file_too_large")
        documents[kind] = blob
    data, google_sub = form
    await rider_applications.apply(session, data, documents, google_sub=google_sub)
    return {"status": "pending",
            "detail": "Thanks for applying! We'll text you as soon as your account is approved."}


@router.get("/config")
async def auth_config() -> dict:
    """What the sign-in pages need to know: the Google client ID (null = no Google button)."""
    return {"google_client_id": settings.GOOGLE_CLIENT_ID if google_auth.enabled() else None,
            "shop_url": settings.FRONTEND_URL}


HANDOFF_PREFIX = "auth:handoff:"
HANDOFF_SECONDS = 60
STAFF_ROLES = (UserRole.ADMIN, UserRole.RIDER)


@router.post("/handoff", dependencies=[Depends(rate_limit("handoff", 10))])
async def create_handoff(user: CurrentUser, redis: RedisDep) -> dict[str, str]:
    """A short-lived, single-use code that moves an admin or rider from the shop to the
    dashboard or rider app, which are a separate site. Only this code goes in the address bar, never a token."""
    if user.role not in STAFF_ROLES:
        raise Forbidden("Only staff accounts use this")
    code = secrets.token_urlsafe(32)
    await redis.set(f"{HANDOFF_PREFIX}{code}", str(user.id), ex=HANDOFF_SECONDS)
    return {"code": code}


@router.post("/handoff/redeem", response_model=TokenPair, dependencies=[Depends(rate_limit("handoff-redeem", 20))])
async def redeem_handoff(data: HandoffRedeem, session: SessionDep, redis: RedisDep):
    user_id = await redis.getdel(f"{HANDOFF_PREFIX}{data.code}")
    user = await session.get(User, uuid.UUID(user_id)) if user_id else None
    if not user or user.role not in STAFF_ROLES:
        raise Unauthorized("That sign-in link has expired. Please sign in again.", code="handoff_invalid")
    await auth_service.check_can_sign_in(session, user)
    return auth_service.issue_tokens(user)


@router.post("/google", response_model=AuthResponse,
             dependencies=[Depends(rate_limit("google", 10))])
async def google_sign_in(data: GoogleSignIn, session: SessionDep):
    """"Continue with Google". Signs in the account with this Google identity (linking it to an
    existing account with the same verified email), or creates a customer account when
    `create_account` is true. Never grants admin or rider roles."""
    claims = await google_auth.verify(data.id_token)
    user = await google_auth.find_or_create(session, claims, create=data.create_account)
    await auth_service.check_can_sign_in(session, user)
    tokens = auth_service.issue_tokens(user)
    return AuthResponse(**tokens.model_dump(), user=UserRead.model_validate(user))


@router.post("/login", response_model=TokenPair, dependencies=[Depends(rate_limit("login", 5))])
async def login(data: LoginRequest, session: SessionDep, redis: RedisDep):
    user = await auth_service.authenticate(session, redis, data.email, data.password)
    return auth_service.issue_tokens(user)


@router.post("/refresh", response_model=TokenPair, dependencies=[Depends(rate_limit("refresh", 30))])
async def refresh(data: RefreshRequest, session: SessionDep, redis: RedisDep):
    return await auth_service.refresh(session, redis, data.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    redis: RedisDep,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    data: RefreshRequest | None = None,
):
    await auth_service.logout(redis, ctx.payload, data.refresh_token if data else None)


@router.post("/password/forgot", status_code=status.HTTP_202_ACCEPTED,
             dependencies=[Depends(rate_limit("pw-forgot", 5))])
async def forgot_password(data: ForgotPasswordRequest, session: SessionDep, redis: RedisDep):
    """Emails a 6-digit reset code. Always answers the same way, whether or not that
    account exists."""
    await auth_service.request_password_reset(session, redis, data.email)
    return {"detail": "If that account exists, we've sent it a reset code."}


@router.post("/password/reset", status_code=status.HTTP_204_NO_CONTENT,
             dependencies=[Depends(rate_limit("pw-reset", 10))])
async def reset_password(data: ResetPasswordRequest, session: SessionDep, redis: RedisDep):
    """Sets a new password with the emailed code. Signs out every device."""
    await auth_service.reset_password(session, redis, data.email, data.code, data.new_password)
