import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, UploadFile, status

from app.api.deps import AdminUser, SessionDep
from app.core.config import settings
from app.core.exceptions import BadRequest, Conflict, NotFound
from app.models.category import Category
from app.models.product import Product
from app.repositories import catalog_repo
from app.schemas.catalog import (
    CategoryCreate,
    CategoryRead,
    CategoryUpdate,
    DiscountApply,
    ProductAdminRead,
    ProductCreate,
    ProductUpdate,
    StockAdjust,
)
from app.services import audit, storage
from app.services.catalog_service import invalidate_catalog_cache, unique_slug
from app.utils.pagination import Page, PageParams

router = APIRouter(prefix="/admin", tags=["ADMIN: CATALOG"])


# ---------------------------------- categories --------------------------------
@router.get("/categories", response_model=list[CategoryRead])
async def list_categories(_: AdminUser, session: SessionDep):
    return await catalog_repo.list_categories(session, active_only=False)


@router.post("/categories", response_model=CategoryRead, status_code=status.HTTP_201_CREATED)
async def create_category(data: CategoryCreate, admin: AdminUser, session: SessionDep):
    if data.parent_id and not await session.get(Category, data.parent_id):
        raise NotFound("Parent category not found")
    cat = Category(**data.model_dump(exclude={"slug"}),
                   slug=await unique_slug(session, Category, data.slug or data.name))
    session.add(cat)
    audit.record(session, admin, "category.create", cat, changes=audit.snapshot(cat))
    await session.commit()
    await session.refresh(cat)
    await invalidate_catalog_cache()
    return cat


@router.patch("/categories/{category_id}", response_model=CategoryRead)
async def update_category(category_id: uuid.UUID, data: CategoryUpdate, admin: AdminUser, session: SessionDep):
    cat = await session.get(Category, category_id)
    if not cat:
        raise NotFound("Category not found")
    changes = data.model_dump(exclude_unset=True)
    if "parent_id" in changes and changes["parent_id"] == cat.id:
        raise BadRequest("A category cannot be its own parent")
    if changes.get("slug"):
        changes["slug"] = await unique_slug(session, Category, changes["slug"], exclude_id=cat.id)
    before = audit.snapshot(cat, list(changes))
    for k, v in changes.items():
        setattr(cat, k, v)
    session.add(cat)
    audit.record(session, admin, "category.update", cat, changes=audit.diff(before, cat))
    await session.commit()
    await session.refresh(cat)
    await invalidate_catalog_cache()
    return cat


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(category_id: uuid.UUID, admin: AdminUser, session: SessionDep):
    cat = await session.get(Category, category_id)
    if not cat:
        raise NotFound("Category not found")
    _, count = await catalog_repo.search_products(session, category_ids=[cat.id],
                                                  active_only=False, limit=1)
    if count:
        raise Conflict("Move this category's products to another category first", code="category_in_use")
    audit.record(session, admin, "category.delete", cat, changes=audit.snapshot(cat))
    await session.delete(cat)
    await session.commit()
    await invalidate_catalog_cache()


# ----------------------------------- products ---------------------------------
@router.get("/products", response_model=Page[ProductAdminRead])
async def list_products(
    _: AdminUser, session: SessionDep, params: Annotated[PageParams, Depends()],
    q: str | None = None, category_id: uuid.UUID | None = None,
    low_stock: bool = Query(False, description="Only items at or below the low-stock threshold"),
):
    from sqlalchemy import func, or_
    from sqlmodel import select

    conds = []
    if q:
        conds.append(or_(Product.name.ilike(f"%{q}%"), Product.slug.ilike(f"%{q}%")))
    if category_id:
        conds.append(Product.category_id == category_id)
    if low_stock:
        conds.append(Product.stock_qty <= settings.LOW_STOCK_THRESHOLD)
    total = (await session.exec(select(func.count()).select_from(Product).where(*conds))).one()
    rows = (await session.exec(select(Product).where(*conds).order_by(Product.name)
                               .offset(params.offset).limit(params.size))).all()
    return Page[ProductAdminRead].build([ProductAdminRead.model_validate(p) for p in rows], total, params)


@router.post("/products", response_model=ProductAdminRead, status_code=status.HTTP_201_CREATED)
async def create_product(data: ProductCreate, admin: AdminUser, session: SessionDep):
    if not await session.get(Category, data.category_id):
        raise NotFound("Category not found")
    if data.compare_at_price is not None and data.compare_at_price < data.price:
        raise BadRequest("compare_at_price should be higher than price")
    product = Product(**data.model_dump(exclude={"slug"}),
                      slug=await unique_slug(session, Product, data.slug or data.name))
    session.add(product)
    audit.record(session, admin, "product.create", product, changes=audit.snapshot(product))
    await session.commit()
    await session.refresh(product)
    await invalidate_catalog_cache()
    return product


@router.get("/products/{product_id}", response_model=ProductAdminRead)
async def get_product(product_id: uuid.UUID, _: AdminUser, session: SessionDep):
    product = await session.get(Product, product_id)
    if not product:
        raise NotFound("Product not found")
    return product


@router.patch("/products/{product_id}", response_model=ProductAdminRead)
async def update_product(product_id: uuid.UUID, data: ProductUpdate, admin: AdminUser, session: SessionDep):
    product = await session.get(Product, product_id)
    if not product:
        raise NotFound("Product not found")
    changes = data.model_dump(exclude_unset=True)
    if changes.get("category_id") and not await session.get(Category, changes["category_id"]):
        raise NotFound("Category not found")
    if changes.get("slug"):
        changes["slug"] = await unique_slug(session, Product, changes["slug"], exclude_id=product.id)
    before = audit.snapshot(product, list(changes))
    for k, v in changes.items():
        setattr(product, k, v)
    if product.compare_at_price is not None and product.compare_at_price < product.price:
        raise BadRequest("compare_at_price should be higher than price")
    session.add(product)
    audit.record(session, admin, "product.update", product, changes=audit.diff(before, product))
    await session.commit()
    await session.refresh(product)
    await invalidate_catalog_cache()
    return product


@router.post("/products/discount")
async def apply_discount(data: DiscountApply, admin: AdminUser, session: SessionDep) -> dict[str, int]:
    """Puts products on sale by percentage, always worked out from the normal price, so a
    new discount replaces the old one instead of stacking. `percent: 0` ends the discount."""
    from sqlmodel import select

    query = select(Product)
    if data.product_ids is not None:
        query = query.where(Product.id.in_(data.product_ids))
    if data.category_id:
        query = query.where(Product.category_id == data.category_id)
    rows = (await session.exec(query.with_for_update())).all()
    updated = 0
    for product in rows:
        normal = max(product.price, product.compare_at_price or product.price)
        if normal <= 0:
            continue
        before = audit.snapshot(product, ["price", "compare_at_price"])
        if data.percent:
            product.compare_at_price = normal
            product.price = (normal * (100 - data.percent) / 100).quantize(Decimal(1), ROUND_HALF_UP)
        else:
            product.compare_at_price = None
            product.price = normal
        session.add(product)
        audit.record(session, admin, "product.discount", product, changes=audit.diff(before, product))
        updated += 1
    await session.commit()
    await invalidate_catalog_cache()
    return {"updated": updated}


@router.post("/products/{product_id}/stock", response_model=ProductAdminRead)
async def adjust_stock(product_id: uuid.UUID, data: StockAdjust, admin: AdminUser, session: SessionDep):
    """Restock or correct stock. Send either {"set": 50} or {"delta": 20}."""
    if (data.set is None) == (data.delta is None):
        raise BadRequest("Provide exactly one of 'set' or 'delta'")
    product = await session.get(Product, product_id, with_for_update=True)
    if not product:
        raise NotFound("Product not found")
    new_qty = data.set if data.set is not None else product.stock_qty + data.delta
    if new_qty < 0:
        raise BadRequest("Stock cannot go below zero")
    audit.record(session, admin, "product.stock", product,
                 changes={"stock_qty": [product.stock_qty, new_qty]})
    product.stock_qty = new_qty
    session.add(product)
    await session.commit()
    await session.refresh(product)
    await invalidate_catalog_cache()
    return product


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_product(product_id: uuid.UUID, admin: AdminUser, session: SessionDep):
    """Soft delete (hides the product). Past orders keep their data."""
    product = await session.get(Product, product_id)
    if not product:
        raise NotFound("Product not found")
    audit.record(session, admin, "product.deactivate", product,
                 changes={"is_active": [product.is_active, False]})
    product.is_active = False
    session.add(product)
    await session.commit()
    await invalidate_catalog_cache()


# ------------------------------------ images ----------------------------------
@router.post("/uploads/images", status_code=status.HTTP_201_CREATED)
async def upload_image(
    file: UploadFile, _: AdminUser,
    folder: Literal["products", "categories"] = "products",
) -> dict[str, str]:
    """Upload a JPEG/PNG/WebP (max 5 MB by default). Put the returned `url` in a
    product's or category's `image_url`."""
    data = await file.read(settings.MAX_UPLOAD_BYTES + 1)
    if len(data) > settings.MAX_UPLOAD_BYTES:
        raise BadRequest(f"Images must be {settings.MAX_UPLOAD_BYTES // (1024 * 1024)} MB or smaller",
                         code="file_too_large")
    return {"url": await storage.save_image(data, folder)}
