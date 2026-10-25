"""The browser pages: the rider app (/rider/), the customer's tracking link (/track/<token>)
and the admin live board (/dashboard). Plain HTML + JS that call the /api/v1 endpoints."""
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse

WEB = Path(__file__).resolve().parent.parent / "web"
router = APIRouter(include_in_schema=False)

_PAGE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Frame-Options": "DENY",           # no one can embed these pages to trick a tap
    "X-Content-Type-Options": "nosniff",
}


def _page(path: Path, media_type: str = "text/html; charset=utf-8", **extra) -> FileResponse:
    return FileResponse(path, media_type=media_type, headers={**_PAGE_HEADERS, **extra})


@router.get("/rider")
async def rider_redirect():
    return RedirectResponse("/rider/")


@router.get("/rider/")
async def rider_app():
    return _page(WEB / "rider" / "index.html")


@router.get("/rider/rider.js")
async def rider_js():
    return _page(WEB / "rider" / "rider.js", "text/javascript; charset=utf-8")


@router.get("/rider/sw.js")
async def rider_service_worker():
    return _page(WEB / "rider" / "sw.js", "text/javascript; charset=utf-8")


@router.get("/rider/manifest.webmanifest")
async def rider_manifest():
    return _page(WEB / "rider" / "manifest.webmanifest", "application/manifest+json")


@router.get("/rider/icon.svg")
async def rider_icon():
    return _page(WEB / "rider" / "icon.svg", "image/svg+xml")


@router.get("/track/{token}")
async def tracking_page(token: str):
    # the token is checked by the page's API call; the HTML is the same for everyone
    return _page(WEB / "track.html", **{"Cache-Control": "no-store"})


@router.get("/dashboard")
async def dashboard():
    return _page(WEB / "dashboard.html")
