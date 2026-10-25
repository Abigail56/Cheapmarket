import uuid

from fastapi import APIRouter, Depends, status
from sqlmodel import select

from app.api.deps import CurrentUser, RedisDep, SessionDep, rate_limit
from app.core.exceptions import Conflict, NotFound
from app.models.address import Address
from app.repositories import user_repo
from app.schemas.auth import (
    AddressCreate,
    AddressRead,
    AddressUpdate,
    ChangePasswordRequest,
    PhoneVerifyConfirm,
    UserRead,
    UserUpdate,
)
from app.services import auth_service

router = APIRouter(prefix="/users/me", tags=["USERS"])


@router.get("", response_model=UserRead)
async def me(user: CurrentUser):
    return user


@router.patch("", response_model=UserRead)
async def update_me(data: UserUpdate, user: CurrentUser, session: SessionDep):
    if data.phone and data.phone != user.phone:
        if await user_repo.get_by_phone(session, data.phone):
            raise Conflict("This phone number is already in use", code="phone_taken")
        user.phone = data.phone
        user.phone_verified_at = None  # a new number has to be verified again
    if data.full_name:
        user.full_name = data.full_name
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(data: ChangePasswordRequest, user: CurrentUser, session: SessionDep):
    await auth_service.change_password(session, user, data.current_password, data.new_password)


@router.post("/phone/verify", status_code=status.HTTP_202_ACCEPTED,
             dependencies=[Depends(rate_limit("phone-verify", 5))])
async def request_phone_verification(user: CurrentUser, redis: RedisDep):
    """Texts a 6-digit code to the phone number on your profile."""
    await auth_service.request_phone_verification(redis, user)
    return {"detail": "We've sent a code to your phone."}


@router.post("/phone/verify/confirm", response_model=UserRead)
async def confirm_phone_verification(
    data: PhoneVerifyConfirm, user: CurrentUser, session: SessionDep, redis: RedisDep
):
    return await auth_service.confirm_phone_verification(session, redis, user, data.code)


# --- addresses -------------------------------------------------------------
async def _get_address(session, user, address_id: uuid.UUID) -> Address:
    addr = await session.get(Address, address_id)
    if not addr or addr.user_id != user.id:
        raise NotFound("Address not found")
    return addr


async def _clear_default(session, user, except_id=None) -> None:
    rows = (await session.exec(select(Address).where(Address.user_id == user.id,
                                                      Address.is_default.is_(True)))).all()
    for a in rows:
        if a.id != except_id:
            a.is_default = False
            session.add(a)


@router.get("/addresses", response_model=list[AddressRead])
async def list_addresses(user: CurrentUser, session: SessionDep):
    stmt = select(Address).where(Address.user_id == user.id).order_by(
        Address.is_default.desc(), Address.created_at
    )
    return (await session.exec(stmt)).all()


@router.post("/addresses", response_model=AddressRead, status_code=status.HTTP_201_CREATED)
async def create_address(data: AddressCreate, user: CurrentUser, session: SessionDep):
    existing = (await session.exec(select(Address).where(Address.user_id == user.id))).all()
    addr = Address(**data.model_dump(), user_id=user.id)
    if not existing:
        addr.is_default = True  # first address is the default
    if addr.is_default:
        await _clear_default(session, user)
    session.add(addr)
    await session.commit()
    await session.refresh(addr)
    return addr


@router.patch("/addresses/{address_id}", response_model=AddressRead)
async def update_address(
    address_id: uuid.UUID, data: AddressUpdate, user: CurrentUser, session: SessionDep
):
    addr = await _get_address(session, user, address_id)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(addr, k, v)
    if data.is_default:
        await _clear_default(session, user, except_id=addr.id)
    session.add(addr)
    await session.commit()
    await session.refresh(addr)
    return addr


@router.delete("/addresses/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_address(address_id: uuid.UUID, user: CurrentUser, session: SessionDep):
    addr = await _get_address(session, user, address_id)
    await session.delete(addr)
    await session.commit()
