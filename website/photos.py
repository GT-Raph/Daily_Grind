"""Turn a photo an administrator uploads from their computer into a menu-ready image."""
import uuid
from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 40_000_000  # about a 50-megapixel camera; anything bigger is refused before decoding
MENU_PHOTO_SIDE = 640  # matches the supplied menu artwork
ACCEPTED_FORMATS = {"JPEG", "PNG", "WEBP"}

NOT_A_PHOTO = "This file isn't a photo the menu can use. Choose a JPG, PNG or WebP image."


def prepare_menu_photo(upload, product_id):
    """Check the upload is a real image, then re-save it as a WebP no larger than 640 pixels.

    Re-saving also drops hidden metadata, such as the location a phone records in its photos.
    """
    if upload.size > MAX_UPLOAD_BYTES:
        raise ValidationError("This photo is larger than 8 MB. Choose a smaller file, or export it at a lower quality.")
    try:
        with Image.open(upload) as probe:
            image_format = probe.format
            width, height = probe.size
            probe.verify()
        if image_format not in ACCEPTED_FORMATS:
            raise ValidationError(NOT_A_PHOTO)
        if width * height > MAX_PIXELS:
            raise ValidationError("This photo has too many pixels. Resize it to under 40 megapixels and try again.")
        upload.seek(0)
        with Image.open(upload) as source:
            source.load()
            # Phones store some photos sideways with a rotation flag; apply it before the flag is dropped.
            image = ImageOps.exif_transpose(source)
    except ValidationError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError):
        raise ValidationError(NOT_A_PHOTO)

    has_transparency = "transparency" in image.info or image.mode in ("RGBA", "LA")
    image = image.convert("RGBA" if has_transparency else "RGB")
    image.thumbnail((MENU_PHOTO_SIDE, MENU_PHOTO_SIDE), Image.Resampling.LANCZOS)
    output = BytesIO()
    image.save(output, "WEBP", quality=84, method=6)  # no exif or icc arguments, so metadata is not copied
    return ContentFile(output.getvalue(), name=f"{product_id}-{uuid.uuid4().hex[:8]}.webp")
