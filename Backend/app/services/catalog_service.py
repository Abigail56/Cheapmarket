import hashlib
import json
import uuid
from decimal import Decimal

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import NotFound
from app.db.redis import cache_delete_prefix, cache_get, cache_set
from app.repositories import catalog_repo
from app.schemas.catalog import CategoryRead, ProductRead
from app.utils.pagination import Page, PageParams
from app.utils.slug import slugify

PRODUCTS_PREFIX = "cache:products:"
CATEGORIES_KEY = "cache:categories"


async def invalidate_catalog_cache() -> None:
    await cache_delete_prefix("cache:products:")
    await cache_delete_prefix(CATEGORIES_KEY)


async def get_categories(session: AsyncSession) -> list[dict]:
    cached = await cache_get(CATEGORIES_KEY)
    if cached is not None:
        return cached
    rows = await catalog_repo.list_categories(session)
    data = [CategoryRead.model_validate(r).model_dump(mode="json") for r in rows]
    await cache_set(CATEGORIES_KEY, data)
    return data


async def get_products(
    session: AsyncSession,
    params: PageParams,
    *,
    category: str | None,
    q: str | None,
    featured: bool | None,
    in_stock_only: bool,
    min_price: Decimal | None,
    max_price: Decimal | None,
    sort: str,
) -> dict:
    raw_key = json.dumps(
        [category, q, featured, in_stock_only, str(min_price), str(max_price), sort,
         params.page, params.size]
    )
    key = PRODUCTS_PREFIX + hashlib.sha1(raw_key.encode()).hexdigest()
    cached = await cache_get(key)
    if cached is not None:
        return cached

    category_ids = None
    if category:
        cat = await catalog_repo.get_category_by_slug(session, category)
        if not cat or not cat.is_active:
            raise NotFound("Category not found")
        category_ids = await catalog_repo.category_ids_with_children(session, cat.id)

    items, total = await catalog_repo.search_products(
        session, category_ids=category_ids, q=q, featured=featured, in_stock_only=in_stock_only,
        min_price=min_price, max_price=max_price, sort=sort,
        offset=params.offset, limit=params.size,
    )
    page = Page[ProductRead].build(
        [ProductRead.model_validate(p) for p in items], total, params
    )
    data = page.model_dump(mode="json")
    await cache_set(key, data)
    return data


async def get_product(session: AsyncSession, slug: str):
    product = await catalog_repo.get_product_by_slug(session, slug)
    if not product or not product.is_active:
        raise NotFound("Product not found")
    return product


async def unique_slug(session: AsyncSession, model, base: str, exclude_id: uuid.UUID | None = None) -> str:
    """slugify + add -2, -3 ... if taken."""
    slug, n = slugify(base), 1
    while True:
        stmt = select(model.id).where(model.slug == slug)
        found = (await session.exec(stmt)).first()
        if found is None or found == exclude_id:
            return slug
        n += 1
        slug = f"{slugify(base)}-{n}"
