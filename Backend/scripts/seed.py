"""Sample data for development. Safe to run repeatedly (it only adds what's missing).

    python -m scripts.seed
"""
import asyncio
from decimal import Decimal

from sqlmodel import select

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import AsyncSessionLocal, engine
from app.models import Category, Coupon, DeliveryZone, DiscountType, Product, User, UserRole
from app.utils.slug import slugify

CATEGORIES = ["Vegetables", "Fruits", "Staples", "Dairy & Eggs", "Meat & Fish", "Pantry"]

# (name, category, unit, price, compare_at, stock, featured)
PRODUCTS = [
    ("Tomatoes (basket)", "Vegetables", "basket", 2500, 3000, 60, True),
    ("Fresh Pepper (rodo)", "Vegetables", "small basket", 1800, None, 40, False),
    ("Onions", "Vegetables", "1 kg", 1200, 1500, 80, False),
    ("Spinach (ugu)", "Vegetables", "bunch", 500, None, 100, False),
    ("Plantain", "Fruits", "bunch", 1500, 1800, 50, True),
    ("Oranges", "Fruits", "10 pcs", 1000, None, 70, False),
    ("Pineapple", "Fruits", "1 pc", 1200, 1500, 40, False),
    ("Watermelon", "Fruits", "1 pc", 2500, 3000, 25, False),
    ("Rice (local)", "Staples", "5 kg", 9500, 10500, 45, True),
    ("Beans (brown)", "Staples", "2 kg", 4200, None, 50, False),
    ("Garri (white)", "Staples", "2 kg", 1800, 2200, 90, False),
    ("Yam tubers", "Staples", "3 pcs", 6000, None, 30, False),
    ("Eggs", "Dairy & Eggs", "crate of 30", 4500, 5000, 60, True),
    ("Fresh Milk", "Dairy & Eggs", "1 L", 1600, None, 40, False),
    ("Chicken", "Meat & Fish", "1 kg", 5500, 6000, 35, False),
    ("Catfish", "Meat & Fish", "1 kg", 4800, None, 20, False),
    ("Palm Oil", "Pantry", "2 L", 5200, 5800, 40, False),
    ("Groundnut Oil", "Pantry", "1 L", 3200, None, 40, False),
]

ZONES = [  # name, fee, free-delivery threshold: rename these to your real delivery areas
    ("Zone A: City Centre", 1500, 20000),
    ("Zone B: Suburbs", 2500, 30000),
    ("Zone C: Outskirts", 3500, None),
]


async def main() -> None:
    if settings.ENVIRONMENT == "production" and settings.ADMIN_PASSWORD == "ChangeMe123!":
        raise SystemExit("Refusing to seed production with the default admin password.")

    async with AsyncSessionLocal() as s:
        # admin
        if not (await s.exec(select(User).where(User.email == settings.ADMIN_EMAIL.lower()))).first():
            s.add(User(email=settings.ADMIN_EMAIL.lower(), full_name=settings.ADMIN_NAME,
                       password_hash=hash_password(settings.ADMIN_PASSWORD), role=UserRole.ADMIN))
            print(f"+ admin user {settings.ADMIN_EMAIL}")
        demo_rider = (await s.exec(select(User).where(User.email == "rider@example.com"))).first()
        if settings.ENVIRONMENT == "local" and not demo_rider:  # demo rider for the delivery flow
            s.add(User(email="rider@example.com", full_name="Demo Rider", phone="+2348000000001",
                       password_hash=hash_password("Rider12345!"), role=UserRole.RIDER))
            print("+ demo rider rider@example.com / Rider12345!")

        # categories
        cats: dict[str, Category] = {}
        for i, name in enumerate(CATEGORIES):
            slug = slugify(name)
            cat = (await s.exec(select(Category).where(Category.slug == slug))).first()
            if not cat:
                cat = Category(name=name, slug=slug, sort_order=i)
                s.add(cat)
                print(f"+ category {name}")
            cats[name] = cat
        await s.flush()

        # products
        for name, cat_name, unit, price, compare, stock, featured in PRODUCTS:
            slug = slugify(name)
            if not (await s.exec(select(Product).where(Product.slug == slug))).first():
                s.add(Product(category_id=cats[cat_name].id, name=name, slug=slug, unit=unit,
                              price=Decimal(price), compare_at_price=Decimal(compare) if compare else None,
                              stock_qty=stock, is_featured=featured))
                print(f"+ product {name}")

        # zones
        for name, fee, free_min in ZONES:
            if not (await s.exec(select(DeliveryZone).where(DeliveryZone.name == name))).first():
                s.add(DeliveryZone(name=name, delivery_fee=Decimal(fee),
                                   free_delivery_min=Decimal(free_min) if free_min else None))
                print(f"+ zone {name}")

        # coupon
        if not (await s.exec(select(Coupon).where(Coupon.code == "WELCOME10"))).first():
            s.add(Coupon(code="WELCOME10", discount_type=DiscountType.PERCENT, value=Decimal(10),
                         min_order=Decimal(5000)))
            print("+ coupon WELCOME10 (10% off orders of 5,000+)")

        await s.commit()
    await engine.dispose()
    print("Seed complete.")


if __name__ == "__main__":
    asyncio.run(main())
