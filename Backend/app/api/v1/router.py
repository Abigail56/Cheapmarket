from fastapi import APIRouter

from app.api.v1.endpoints import auth, cart, catalog, orders, payments, rider, tracking, users
from app.api.v1.endpoints.admin import catalog as admin_catalog
from app.api.v1.endpoints.admin import deliveries as admin_deliveries
from app.api.v1.endpoints.admin import orders as admin_orders
from app.api.v1.endpoints.admin import riders as admin_riders
from app.api.v1.endpoints.admin import store as admin_store

api_router = APIRouter()
for r in (auth.router, users.router, catalog.router, cart.router, orders.router,
          payments.router, rider.router, tracking.router, admin_catalog.router,
          admin_orders.router, admin_deliveries.router, admin_riders.router, admin_store.router):
    api_router.include_router(r)
