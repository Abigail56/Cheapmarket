import hashlib
import io
from pathlib import Path

import httpx
from PIL import Image

from app.core.config import settings
from app.services import storage

GPS_TAG, ORIENTATION_TAG, MAKE_TAG = 0x8825, 0x0112, 0x010F


def make_image(fmt: str, size=(64, 48), color=(30, 120, 60), gps=False, orientation=None) -> bytes:
    """A real image; optionally with the EXIF a phone adds (GPS position, camera, rotation)."""
    img = Image.new("RGB", size, color)
    exif = Image.Exif()
    if gps:
        exif[MAKE_TAG] = "PhoneMaker X1"
        exif[GPS_TAG] = {1: "N", 2: (6.0, 31.0, 28.0), 3: "E", 4: (3.0, 22.0, 45.0)}  # Lagos
    if orientation:
        exif[ORIENTATION_TAG] = orientation
    out = io.BytesIO()
    img.save(out, fmt, exif=exif.tobytes() if (gps or orientation) else b"")
    return out.getvalue()


def exif_of(data: bytes) -> dict:
    with Image.open(io.BytesIO(data)) as img:
        return dict(img.getexif())


PNG = make_image("PNG")
JPEG = make_image("JPEG")
WEBP = make_image("WEBP")


async def upload(client, headers, data, name="pic.png", ctype="image/png", **params):
    return await client.post("/admin/uploads/images", headers=headers, params=params,
                             files={"file": (name, data, ctype)})


async def test_admin_uploads_image_and_it_is_served(client, admin):
    r = await upload(client, admin["headers"], PNG)
    assert r.status_code == 201, r.text
    url = r.json()["url"]
    assert url.startswith(settings.MEDIA_BASE_URL + "/products/") and url.endswith(".png")
    name = url.rsplit("/", 1)[1]
    stored = (Path(settings.MEDIA_DIR) / "products" / name).read_bytes()
    with Image.open(io.BytesIO(stored)) as img:  # re-encoded, same picture
        assert img.format == "PNG" and img.size == (64, 48)
    served = await client.get(f"http://test/media/products/{name}")
    assert served.status_code == 200 and served.content == stored


async def test_type_is_detected_from_content_not_name(client, admin):
    assert (await upload(client, admin["headers"], JPEG, name="x.png")).json()["url"].endswith(".jpg")
    r = await upload(client, admin["headers"], WEBP, folder="categories")
    assert "/categories/" in r.json()["url"] and r.json()["url"].endswith(".webp")
    # text pretending to be a PNG, SVG (can carry scripts), and a real header on junk are refused
    for data in (b"not an image at all", b"<svg xmlns='http://www.w3.org/2000/svg'></svg>",
                 b"\x89PNG\r\n\x1a\n" + b"\x00" * 64):
        r = await upload(client, admin["headers"], data)
        assert r.status_code == 400 and r.json()["error"]["code"] == "unsupported_image"


async def test_location_and_camera_data_are_stripped(client, admin):
    phone_photo = make_image("JPEG", gps=True)
    assert GPS_TAG in exif_of(phone_photo) and MAKE_TAG in exif_of(phone_photo)
    url = (await upload(client, admin["headers"], phone_photo, name="p.jpg", ctype="image/jpeg")).json()["url"]
    stored = (Path(settings.MEDIA_DIR) / "products" / url.rsplit("/", 1)[1]).read_bytes()
    assert exif_of(stored) == {}
    assert b"PhoneMaker" not in stored


async def test_sideways_phone_photos_are_turned_upright(client, admin):
    # 80x40 picture whose EXIF says "rotate 90°" (how phones save portrait shots)
    sideways = make_image("JPEG", size=(80, 40), orientation=6)
    url = (await upload(client, admin["headers"], sideways, name="p.jpg", ctype="image/jpeg")).json()["url"]
    stored = (Path(settings.MEDIA_DIR) / "products" / url.rsplit("/", 1)[1]).read_bytes()
    with Image.open(io.BytesIO(stored)) as img:
        assert img.size == (40, 80)  # rotated for real, so it shows upright without EXIF


async def test_decompression_bombs_are_refused(client, admin, monkeypatch):
    monkeypatch.setattr(storage, "MAX_PIXELS", 1000)
    r = await upload(client, admin["headers"], make_image("PNG", size=(100, 100)))
    assert r.status_code == 400 and r.json()["error"]["code"] == "image_too_large"


async def test_upload_size_limit(client, admin, monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_BYTES", 32)
    r = await upload(client, admin["headers"], PNG)
    assert r.status_code == 400 and r.json()["error"]["code"] == "file_too_large"


async def test_only_admins_can_upload(client, customer):
    assert (await upload(client, customer["headers"], PNG)).status_code == 403
    assert (await upload(client, {}, PNG)).status_code == 401


async def test_cloudinary_backend_signs_upload(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content
        return httpx.Response(200, json={"secure_url": "https://res.cloudinary.com/demo/x.png"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(storage.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(storage.time, "time", lambda: 1700000000)
    for k, v in {"STORAGE_BACKEND": "cloudinary", "CLOUDINARY_CLOUD_NAME": "demo",
                 "CLOUDINARY_API_KEY": "key", "CLOUDINARY_API_SECRET": "secret"}.items():
        monkeypatch.setattr(settings, k, v)
    url = await storage.save_image(PNG, "products")
    assert url == "https://res.cloudinary.com/demo/x.png"
    assert seen["url"] == "https://api.cloudinary.com/v1_1/demo/image/upload"
    body = seen["body"].decode("latin-1")
    public_id = body.split('name="public_id"\r\n\r\n')[1].split("\r\n")[0]
    expected = hashlib.sha1(
        f"folder=cheapmarketdeal/products&public_id={public_id}&timestamp=1700000000secret".encode()
    ).hexdigest()
    assert expected in body
