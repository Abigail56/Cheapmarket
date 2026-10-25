"""Image uploads for products and categories.

"local" (default) writes to MEDIA_DIR, which the app serves at /media. Fine for one
server; use "cloudinary" when you run more than one, or want a CDN and resizing."""
import asyncio
import hashlib
import io
import time
import uuid
from pathlib import Path

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import settings
from app.core.exceptions import AppError, BadRequest


class StorageError(AppError):
    status_code, code = 502, "storage_error"


def image_extension(data: bytes) -> str:
    """Identifies the image from its first bytes; the browser's Content-Type and the
    file name are easy to fake. SVG is refused on purpose (it can carry scripts)."""
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    raise BadRequest("Upload a JPEG, PNG or WebP image", code="unsupported_image")


# Refuse images bigger than this many pixels (~40 MP: more than any phone photo).
# Stops "decompression bombs": tiny files that expand to gigabytes in memory.
MAX_PIXELS = 40_000_000
_PIL_FORMATS = {"jpg": "JPEG", "png": "PNG", "webp": "WEBP"}


def _clean(data: bytes, ext: str) -> bytes:
    """Re-encode from pixels only. Drops ALL metadata (EXIF: GPS location, camera serial,
    time; XMP; comments), after turning the picture the right way up, so a phone photo
    can't reveal where it was taken. Also means only a real, decodable image is stored."""
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.format != _PIL_FORMATS[ext]:
                raise BadRequest("The file is not the kind of image it claims to be", code="unsupported_image")
            if img.width * img.height > MAX_PIXELS:
                raise BadRequest("That image is too large", code="image_too_large")
            img = ImageOps.exif_transpose(img)  # apply the phone's rotation before dropping EXIF
            icc = img.info.get("icc_profile")    # colour profile only: keeps colours right
            out = io.BytesIO()
            if ext == "jpg":
                img.convert("RGB").save(out, "JPEG", quality=88, optimize=True, icc_profile=icc)
            elif ext == "png":
                if img.mode not in ("RGB", "RGBA", "L", "LA", "P"):
                    img = img.convert("RGBA")
                img.save(out, "PNG", optimize=True, icc_profile=icc)
            else:
                img.save(out, "WEBP", quality=85, icc_profile=icc)
            return out.getvalue()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError) as e:
        if isinstance(e, Image.DecompressionBombError):
            raise BadRequest("That image is too large", code="image_too_large") from None
        raise BadRequest("That image is damaged or not a real picture", code="unsupported_image") from None


async def clean_image(data: bytes) -> tuple[bytes, str]:
    """(cleaned bytes, extension). Runs in a thread: decoding is CPU work."""
    ext = image_extension(data)
    return await asyncio.to_thread(_clean, data, ext), ext


DOCUMENT_TYPES = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp", "pdf": "application/pdf"}


def document_content_type(data: bytes) -> str:
    """For ID documents: a photo (JPEG/PNG/WebP) or a PDF, judged by the file's bytes."""
    if data.startswith(b"%PDF-"):
        return DOCUMENT_TYPES["pdf"]
    try:
        return DOCUMENT_TYPES[image_extension(data)]
    except BadRequest:
        raise BadRequest("ID documents must be a photo (JPEG, PNG, WebP) or a PDF",
                         code="unsupported_document") from None


async def clean_document(data: bytes) -> tuple[str, bytes]:
    """(content type, bytes to store) for an ID document: photos are cleaned like any other
    image; PDFs are kept as they are (they carry no GPS location)."""
    content_type = document_content_type(data)
    if content_type == DOCUMENT_TYPES["pdf"]:
        return content_type, data
    cleaned, _ = await clean_image(data)
    return content_type, cleaned


async def save_image(data: bytes, folder: str) -> str:
    """Cleans the image (see _clean), stores it and returns its public URL."""
    data, ext = await clean_image(data)
    name = f"{uuid.uuid4().hex}.{ext}"
    if settings.STORAGE_BACKEND == "cloudinary":
        return await _cloudinary_upload(data, folder, name)
    path = Path(settings.MEDIA_DIR) / folder / name
    await asyncio.to_thread(_write, path, data)
    return f"{settings.MEDIA_BASE_URL.rstrip('/')}/{folder}/{name}"


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


async def _cloudinary_upload(data: bytes, folder: str, name: str) -> str:
    if not (settings.CLOUDINARY_CLOUD_NAME and settings.CLOUDINARY_API_KEY
            and settings.CLOUDINARY_API_SECRET):
        raise BadRequest("Cloudinary is not configured", code="provider_not_configured")
    params = {"folder": f"cheapmarketdeal/{folder}", "public_id": name.rsplit(".", 1)[0],
              "timestamp": str(int(time.time()))}
    # Cloudinary signature: sha1 of the sorted params + API secret
    to_sign = "&".join(f"{k}={params[k]}" for k in sorted(params))
    signature = hashlib.sha1((to_sign + settings.CLOUDINARY_API_SECRET).encode()).hexdigest()
    url = f"https://api.cloudinary.com/v1_1/{settings.CLOUDINARY_CLOUD_NAME}/image/upload"
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(url, data={**params, "api_key": settings.CLOUDINARY_API_KEY,
                                        "signature": signature},
                             files={"file": (name, data)})
    except httpx.HTTPError as e:
        raise StorageError("Could not upload the image right now") from e
    if r.status_code != 200:
        raise StorageError("Could not upload the image right now")
    return r.json()["secure_url"]
