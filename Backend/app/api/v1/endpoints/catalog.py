from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.api.deps import SessionDep
from app.repositories import catalog_repo
from app.schemas.catalog import CategoryRead, ProductRead, ProductSort, ZoneRead
from app.services import catalog_service
from app.utils.pagination import Page, PageParams

router = APIRouter(tags=["CATALOG"])


@router.get("/categories", response_model=list[CategoryRead])
async def list_categories(session: SessionDep):
    return await catalog_service.get_categories(session)


@router.get("/products", response_model=Page[ProductRead])
async def list_products(
    session: SessionDep,
    params: Annotated[PageParams, Depends()],
    category: str | None = Query(None, description="Category slug (includes subcategories)"),
    q: str | None = Query(None, min_length=1, max_length=100, description="Search name/description"),
    featured: bool | None = None,
    in_stock_only: bool = False,
    min_price: Decimal | None = Query(None, ge=0),
    max_price: Decimal | None = Query(None, ge=0),
    sort: ProductSort = "newest",
):
    data = await catalog_service.get_products(
        session, params, category=category, q=q, featured=featured,
        in_stock_only=in_stock_only, min_price=min_price, max_price=max_price, sort=sort,
    )
    # Cached JSON is returned as-is (response_model above is for the API docs)
    return JSONResponse(content=data)


@router.get("/products/{slug}", response_model=ProductRead)
async def get_product(slug: str, session: SessionDep):
    return await catalog_service.get_product(session, slug)


@router.get("/delivery-zones", response_model=list[ZoneRead])
async def list_zones(session: SessionDep):
    """Zones + fees, so the checkout page can show the delivery cost."""
    return await catalog_repo.list_active_zones(session)
