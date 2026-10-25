import uuid

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.user import User


async def get_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def get_by_email(session: AsyncSession, email: str) -> User | None:
    return (await session.exec(select(User).where(User.email == email.lower()))).first()


async def get_by_phone(session: AsyncSession, phone: str) -> User | None:
    return (await session.exec(select(User).where(User.phone == phone))).first()
