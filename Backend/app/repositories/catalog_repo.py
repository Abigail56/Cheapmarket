import uuid
from decimal import Decimal

from sqlalchemy import func, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.category import Category
from app.models.delivery_zone import DeliveryZone
from app.models.product import Product

SORTS = {
    "newest": lambda: Product.created_at.desc(),
    "price_asc": lambda: Product.price.asc(),
    "price_desc": lambda: Product.price.desc(),
    "name": lambda: Product.name.asc(),
}


async def list_categories(session: AsyncSession, active_only: bool = True) -> list[Category]:
    stmt = select(Category).order_by(Category.sort_order, Category.name)
    if active_only:
        stmt = stmt.where(Category.is_active.is_(True))
    return list((await session.exec(stmt)).all())


async def get_category_by_slug(session: AsyncSession, slug: str) -> Category | None:
    return (await session.exec(select(Category).where(Category.slug == slug))).first()


async def category_ids_with_children(session: AsyncSession, category_id: uuid.UUID) -> list[uuid.UUID]:
    kids = (await session.exec(select(Category.id).where(Category.parent_id == category_id))).all()
    return [category_id, *kids]


async def search_products(
    session: AsyncSession,
    *,
    category_ids: list[uuid.UUID] | None = None,
    q: str | None = None,
    featured: bool | None = None,
    in_stock_only: bool = False,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    sort: str = "newest",
    active_only: bool = True,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[Product], int]:
    conds = []
    if active_only:
        conds.append(Product.is_active.is_(True))
    if category_ids:
        conds.append(Product.category_id.in_(category_ids))
    if q:
        like = f"%{q.strip()}%"
        conds.append(or_(Product.name.ilike(like), Product.description.ilike(like)))
    if featured is not None:
        conds.append(Product.is_featured.is_(featured))
    if in_stock_only:
        conds.append(Product.stock_qty > 0)
    if min_price is not None:
        conds.append(Product.price >= min_price)
    if max_price is not None:
        conds.append(Product.price <= max_price)

    total = (await session.exec(select(func.count()).select_from(Product).where(*conds))).one()
    stmt = (
        select(Product)
        .where(*conds)
        .order_by(SORTS.get(sort, SORTS["newest"])(), Product.id)
        .offset(offset)
        .limit(limit)
    )
    return list((await session.exec(stmt)).all()), total


async def get_product_by_slug(session: AsyncSession, slug: str) -> Product | None:
    return (await session.exec(select(Product).where(Product.slug == slug))).first()


async def list_active_zones(session: AsyncSession) -> list[DeliveryZone]:
    stmt = select(DeliveryZone).where(DeliveryZone.is_active.is_(True)).order_by(DeliveryZone.name)
    return list((await session.exec(stmt)).all())
