import base64
from io import BytesIO

from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError

from users.models import (
    LOGO_TEXT_SIZES,
    LOGO_TEXT_SPACINGS,
    LogoTextFontChoices,
    LogoTextWeightChoices,
)

MAX_LOGO_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_LOGO_DATA_URL_LENGTH = 40_000
MAX_LOGO_SIZE = (256, 64)
MAX_LOGO_SOURCE_PIXELS = 16 * 1024 * 1024
MAX_LOGO_TEXT_LENGTH = 32
ALLOWED_LOGO_FORMATS = {"JPEG", "PNG", "WEBP"}
UPLOAD_TOO_LARGE_MESSAGE = "Logo images must be 2 MB or smaller."
UNSUPPORTED_IMAGE_MESSAGE = "Use a PNG, JPEG, or WebP logo image."
INVALID_IMAGE_MESSAGE = "Use a valid PNG, JPEG, or WebP logo image."
IMAGE_DIMENSIONS_MESSAGE = "Logo image dimensions are too large."
COMPLEX_IMAGE_MESSAGE = "The normalized logo image is still too complex."
LONG_TEXT_MESSAGE = "Logo text must be 32 characters or fewer."
INVALID_TEXT_STYLE_MESSAGE = "Choose valid text logo typography settings."


def normalize_logo_upload(upload):
    """Return a small metadata-free WebP data URL from a validated raster image."""
    if upload.size > MAX_LOGO_UPLOAD_BYTES:
        raise ValidationError(UPLOAD_TOO_LARGE_MESSAGE)

    payload = upload.read(MAX_LOGO_UPLOAD_BYTES + 1)
    if len(payload) > MAX_LOGO_UPLOAD_BYTES:
        raise ValidationError(UPLOAD_TOO_LARGE_MESSAGE)

    try:
        with Image.open(BytesIO(payload)) as source:
            if source.format not in ALLOWED_LOGO_FORMATS:
                raise ValidationError(UNSUPPORTED_IMAGE_MESSAGE)
            if source.width * source.height > MAX_LOGO_SOURCE_PIXELS:
                raise ValidationError(IMAGE_DIMENSIONS_MESSAGE)
            source.load()
            image = source.convert("RGBA")
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as exc:
        raise ValidationError(INVALID_IMAGE_MESSAGE) from exc

    image.thumbnail(MAX_LOGO_SIZE, Image.Resampling.LANCZOS)
    for quality in (90, 80, 70, 60):
        output = BytesIO()
        image.save(output, "WEBP", quality=quality, method=6)
        encoded = base64.b64encode(output.getvalue()).decode("ascii")
        data_url = f"data:image/webp;base64,{encoded}"
        if len(data_url) <= MAX_LOGO_DATA_URL_LENGTH:
            return data_url

    raise ValidationError(COMPLEX_IMAGE_MESSAGE)


def normalize_logo_text(value):
    """Validate the short wordmark rendered beside the navigation."""
    cleaned = (value or "").strip() or "Floppy"
    if len(cleaned) > MAX_LOGO_TEXT_LENGTH:
        raise ValidationError(LONG_TEXT_MESSAGE)
    return cleaned


def normalize_logo_text_style(font, size, weight, spacing):
    """Return bounded typography values safe to expose as CSS variables."""
    try:
        normalized = (font, int(size), int(weight), int(spacing))
    except (TypeError, ValueError) as exc:
        raise ValidationError(INVALID_TEXT_STYLE_MESSAGE) from exc

    if (
        normalized[0] not in LogoTextFontChoices.values
        or normalized[1] not in LOGO_TEXT_SIZES
        or normalized[2] not in LogoTextWeightChoices.values
        or normalized[3] not in LOGO_TEXT_SPACINGS
    ):
        raise ValidationError(INVALID_TEXT_STYLE_MESSAGE)
    return normalized
