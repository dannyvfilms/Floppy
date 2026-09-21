import base64
import json
import re
from io import BytesIO

from django.core.exceptions import ValidationError

from users.appearance import parse_custom_theme
from users.models import (
    LOGO_TEXT_INPUT_MAX_LENGTH,
    LOGO_TEXT_SIZES,
    LOGO_TEXT_SPACINGS,
    LOGO_TEXT_STORAGE_MAX_LENGTH,
    LogoStyleChoices,
    LogoTextFillChoices,
    LogoTextFontChoices,
    LogoTextWeightChoices,
    ThemeChoices,
)

MAX_LOGO_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_LOGO_DATA_URL_LENGTH = 40_000
MAX_LOGO_SIZE = (256, 64)
MAX_LOGO_SOURCE_PIXELS = 16 * 1024 * 1024
ALLOWED_LOGO_FORMATS = {"JPEG", "PNG", "WEBP"}
UPLOAD_TOO_LARGE_MESSAGE = "Logo images must be 2 MB or smaller."
UNSUPPORTED_IMAGE_MESSAGE = "Use a PNG, JPEG, or WebP logo image."
INVALID_IMAGE_MESSAGE = "Use a valid PNG, JPEG, or WebP logo image."
IMAGE_DIMENSIONS_MESSAGE = "Logo image dimensions are too large."
COMPLEX_IMAGE_MESSAGE = "The normalized logo image is still too complex."
LONG_TEXT_MESSAGE = (
    f"Logo text must be {LOGO_TEXT_INPUT_MAX_LENGTH} characters or fewer."
)
INVALID_TEXT_STYLE_MESSAGE = "Choose valid text logo typography settings."
INVALID_TEXT_FILL_MESSAGE = "Choose valid wordmark colors."
HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}\Z")
PUBLIC_LOGO_DATA = re.compile(r"data:image/webp;base64,[A-Za-z0-9+/]+={0,2}\Z")

DEFAULT_PUBLIC_BRANDING = {
    "theme": ThemeChoices.SYSTEM,
    "custom_theme": {},
    "logo_style": LogoStyleChoices.COLORFUL,
    "logo_text": "Floppy",
    "logo_text_font": LogoTextFontChoices.DISPLAY,
    "logo_text_size": 23,
    "logo_text_weight": LogoTextWeightChoices.EXTRABOLD,
    "logo_text_spacing": -1,
    "logo_text_fill": LogoTextFillChoices.THEME_GRADIENT,
    "logo_text_color_start": "#1f2937",
    "logo_text_color_end": "#2563eb",
    "custom_logo_data": "",
}


def normalize_logo_upload(upload):
    """Return a small metadata-free WebP data URL from a validated raster image."""
    from PIL import Image, UnidentifiedImageError

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


def normalize_logo_text(value, *, max_length=LOGO_TEXT_INPUT_MAX_LENGTH):
    """Validate the short wordmark rendered beside the navigation."""
    cleaned = (value or "").strip() or "Floppy"
    if len(cleaned) > max_length:
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


def normalize_logo_text_fill(fill, color_start, color_end):
    """Constrain wordmark paint values before they reach inline CSS."""
    if fill not in LogoTextFillChoices.values:
        raise ValidationError(INVALID_TEXT_FILL_MESSAGE)
    if not isinstance(color_start, str) or not HEX_COLOR.fullmatch(color_start):
        raise ValidationError(INVALID_TEXT_FILL_MESSAGE)
    if not isinstance(color_end, str) or not HEX_COLOR.fullmatch(color_end):
        raise ValidationError(INVALID_TEXT_FILL_MESSAGE)
    return fill, color_start.lower(), color_end.lower()


def public_branding_snapshot(user):
    """Freeze only the validated display fields needed on public pages."""
    snapshot = {
        key: getattr(user, key)
        for key in DEFAULT_PUBLIC_BRANDING
    }
    return validated_public_branding(snapshot)


def can_publish_public_appearance(user):
    """Allow the instance owner, or an explicit superuser, to brand public pages."""
    if not getattr(user, "is_authenticated", False) or getattr(user, "is_demo", False):
        return False
    if user.is_superuser:
        return True
    owner_id = (
        user._meta.model.objects.filter(is_demo=False)
        .order_by("date_joined", "pk")
        .values_list("pk", flat=True)
        .first()
    )
    return user.pk == owner_id


def validated_public_branding(value):
    """Fall back to the stock logo if a stored public snapshot is malformed."""
    if not isinstance(value, dict) or not value:
        return DEFAULT_PUBLIC_BRANDING.copy()
    if value.get("logo_style") not in LogoStyleChoices.values:
        return DEFAULT_PUBLIC_BRANDING.copy()
    theme = value.get("theme", ThemeChoices.SYSTEM)
    if theme not in ThemeChoices.values:
        return DEFAULT_PUBLIC_BRANDING.copy()
    try:
        custom_theme = parse_custom_theme(json.dumps(value.get("custom_theme", {})))
        text = normalize_logo_text(
            value.get("logo_text"), max_length=LOGO_TEXT_STORAGE_MAX_LENGTH
        )
        font, size, weight, spacing = normalize_logo_text_style(
            value.get("logo_text_font"),
            value.get("logo_text_size"),
            value.get("logo_text_weight"),
            value.get("logo_text_spacing"),
        )
        fill, color_start, color_end = normalize_logo_text_fill(
            value.get("logo_text_fill"),
            value.get("logo_text_color_start"),
            value.get("logo_text_color_end"),
        )
        image_data = value.get("custom_logo_data", "")
    except (TypeError, ValidationError):
        return DEFAULT_PUBLIC_BRANDING.copy()
    if not isinstance(image_data, str) or len(image_data) > MAX_LOGO_DATA_URL_LENGTH:
        return DEFAULT_PUBLIC_BRANDING.copy()
    if image_data and not PUBLIC_LOGO_DATA.fullmatch(image_data):
        return DEFAULT_PUBLIC_BRANDING.copy()
    if value["logo_style"] == LogoStyleChoices.CUSTOM and not image_data:
        return DEFAULT_PUBLIC_BRANDING.copy()
    return {
        "theme": theme,
        "custom_theme": custom_theme,
        "logo_style": value["logo_style"],
        "logo_text": text,
        "logo_text_font": font,
        "logo_text_size": size,
        "logo_text_weight": weight,
        "logo_text_spacing": spacing,
        "logo_text_fill": fill,
        "logo_text_color_start": color_start,
        "logo_text_color_end": color_end,
        "custom_logo_data": image_data,
    }


def brand_for_viewer(user):
    """Keep private branding private until an admin publishes a snapshot."""
    if getattr(user, "is_authenticated", False):
        return user
    from app.models.application_settings import ApplicationSettings

    stored = (
        ApplicationSettings.objects.filter(pk=1)
        .values_list("public_branding", flat=True)
        .first()
    )
    return validated_public_branding(stored)
