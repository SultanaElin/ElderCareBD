import hashlib
import io
import os
import re
import tempfile
import unicodedata
import uuid
import warnings
from dataclasses import dataclass
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
PRIVATE_UPLOAD_DIR = Path(
    os.getenv(
        "ELDERCARE_PRIVATE_UPLOAD_DIR",
        str(BACKEND_DIR / "private_uploads"),
    )
).resolve()
LEGACY_UPLOAD_DIR = (BACKEND_DIR / "uploads").resolve()

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_WIDTH = 10_000
MAX_IMAGE_HEIGHT = 10_000
MAX_IMAGE_PIXELS = 25_000_000
READ_CHUNK_BYTES = 64 * 1024

_PRIVATE_KEY_PATTERN = re.compile(r"^[0-9a-f]{32}\.(?:jpg|png)$")
_FORMAT_CONTRACT = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
}


class ImageValidationError(Exception):
    def __init__(self, detail, status_code=400):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class StoredImage:
    storage_key: str
    original_name: str | None
    mime_type: str
    size_bytes: int
    sha256: str


def _pillow_modules():
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError as exc:
        raise RuntimeError(
            "Pillow is required for prescription image validation."
        ) from exc
    return Image, ImageOps, UnidentifiedImageError


def _safe_original_name(filename):
    if not filename:
        return None
    basename = Path(filename.replace("\\", "/")).name
    basename = "".join(
        character
        for character in basename
        if not unicodedata.category(character).startswith("C")
    ).strip()
    return basename[:255] or None


async def _read_bounded(upload):
    chunks = []
    total = 0
    while True:
        chunk = await upload.read(READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_IMAGE_BYTES:
            raise ImageValidationError(
                f"Prescription image must be {MAX_IMAGE_BYTES // (1024 * 1024)} MB or smaller.",
                status_code=413,
            )
        chunks.append(chunk)
    if total == 0:
        raise ImageValidationError("Prescription image is empty.")
    return b"".join(chunks)


def _validate_dimensions(width, height):
    if width <= 0 or height <= 0:
        raise ImageValidationError("Prescription image dimensions are invalid.")
    if (
        width > MAX_IMAGE_WIDTH
        or height > MAX_IMAGE_HEIGHT
        or width * height > MAX_IMAGE_PIXELS
    ):
        raise ImageValidationError(
            "Prescription image dimensions are too large.",
            status_code=413,
        )


def _decode_and_sanitize(raw_bytes):
    Image, ImageOps, UnidentifiedImageError = _pillow_modules()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw_bytes)) as verification_image:
                image_format = verification_image.format
                if image_format not in _FORMAT_CONTRACT:
                    raise ImageValidationError(
                        "Only genuine JPEG and PNG prescription images are accepted."
                    )
                _validate_dimensions(*verification_image.size)
                verification_image.verify()

            with Image.open(io.BytesIO(raw_bytes)) as decoded_image:
                if decoded_image.format != image_format:
                    raise ImageValidationError("Prescription image is malformed.")
                _validate_dimensions(*decoded_image.size)
                decoded_image.load()
                sanitized_image = ImageOps.exif_transpose(decoded_image)

                output = io.BytesIO()
                if image_format == "JPEG":
                    if sanitized_image.mode not in ("RGB", "L"):
                        sanitized_image = sanitized_image.convert("RGB")
                    sanitized_image.save(
                        output,
                        format="JPEG",
                        quality=95,
                        optimize=True,
                    )
                else:
                    if sanitized_image.mode not in (
                        "1",
                        "L",
                        "LA",
                        "P",
                        "RGB",
                        "RGBA",
                        "I",
                        "I;16",
                    ):
                        sanitized_image = sanitized_image.convert("RGBA")
                    sanitized_image.save(output, format="PNG", optimize=True)
    except ImageValidationError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ImageValidationError(
            "Only genuine, readable JPEG and PNG prescription images are accepted."
        ) from exc
    except Image.DecompressionBombError as exc:
        raise ImageValidationError(
            "Prescription image dimensions are too large.",
            status_code=413,
        ) from exc
    except Image.DecompressionBombWarning as exc:
        raise ImageValidationError(
            "Prescription image dimensions are too large.",
            status_code=413,
        ) from exc

    sanitized_bytes = output.getvalue()
    if len(sanitized_bytes) > MAX_IMAGE_BYTES:
        raise ImageValidationError(
            f"Sanitized prescription image must be {MAX_IMAGE_BYTES // (1024 * 1024)} MB or smaller.",
            status_code=413,
        )
    mime_type, extension = _FORMAT_CONTRACT[image_format]
    return sanitized_bytes, mime_type, extension


async def validate_and_store_upload(upload):
    raw_bytes = await _read_bounded(upload)
    sanitized_bytes, mime_type, extension = _decode_and_sanitize(raw_bytes)
    storage_key = f"{uuid.uuid4().hex}{extension}"
    PRIVATE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    final_path = PRIVATE_UPLOAD_DIR / storage_key
    temporary_path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=PRIVATE_UPLOAD_DIR,
            prefix=".prescription-",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(sanitized_bytes)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, final_path)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        raise

    return StoredImage(
        storage_key=storage_key,
        original_name=_safe_original_name(upload.filename),
        mime_type=mime_type,
        size_bytes=len(sanitized_bytes),
        sha256=hashlib.sha256(sanitized_bytes).hexdigest(),
    )


def delete_private_image(storage_key):
    if not storage_key or not _PRIVATE_KEY_PATTERN.fullmatch(storage_key):
        return
    (PRIVATE_UPLOAD_DIR / storage_key).unlink(missing_ok=True)


def resolve_image_path(image_path):
    if not image_path:
        return None

    if _PRIVATE_KEY_PATTERN.fullmatch(image_path):
        candidate = (PRIVATE_UPLOAD_DIR / image_path).resolve()
        return candidate if candidate.parent == PRIVATE_UPLOAD_DIR else None

    normalized = image_path.replace("\\", "/")
    parts = Path(normalized).parts
    if len(parts) == 2 and parts[0] == "uploads" and Path(parts[1]).name == parts[1]:
        candidate = (LEGACY_UPLOAD_DIR / parts[1]).resolve()
        return candidate if candidate.parent == LEGACY_UPLOAD_DIR else None
    return None


def validate_existing_image(path):
    Image, _, UnidentifiedImageError = _pillow_modules()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                if image.format not in _FORMAT_CONTRACT:
                    return None
                _validate_dimensions(*image.size)
                image.verify()
                return _FORMAT_CONTRACT[image.format][0]
    except (
        ImageValidationError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
    ):
        return None
