"""Gives the sample catalogue its stock photos (app/web/static/catalog). Safe to run repeatedly:
it only fills products and categories that have no image, so uploaded photos are kept.

    python -m scripts.seed_images                 # base URL taken from MEDIA_BASE_URL
    python -m scripts.seed_images --base http://localhost:8010
    python -m scripts.seed_images --replace ugu   # also overwrite the image of these slugs
"""
import argparse
import asyncio
from pathlib import Path

from sqlmodel import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal, engine
from app.models import Category, Product
from app.services.catalog_service import invalidate_catalog_cache

CATALOG = Path(__file__).resolve().parent.parent / "app" / "web" / "static" / "catalog"


async def main(base: str, replace: set[str]) -> None:
    async with AsyncSessionLocal() as s:
        for model, prefix in ((Category, "cat-"), (Product, "")):
            for row in (await s.exec(select(model))).all():
                if not (CATALOG / f"{prefix}{row.slug}.jpg").is_file():
                    print(f"- no photo for {row.slug}")
                elif not row.image_url or row.slug in replace:
                    row.image_url = f"{base}/static/catalog/{prefix}{row.slug}.jpg"
                    s.add(row)
                    print(f"+ {row.slug}")
        await s.commit()
    await invalidate_catalog_cache()
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=settings.MEDIA_BASE_URL.removesuffix("/media"))
    parser.add_argument("--replace", nargs="*", default=[], help="slugs whose existing image to overwrite")
    args = parser.parse_args()
    asyncio.run(main(args.base.rstrip("/"), set(args.replace)))
