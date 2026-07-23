import io
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError


@dataclass(frozen=True)
class ProcessedPhoto:
    display_bytes: bytes
    thumbnail_bytes: bytes
    width: int
    height: int
    content_type: str = "image/jpeg"
    extension: str = ".jpg"

    @property
    def size_bytes(self) -> int:
        return len(self.display_bytes)

    @property
    def thumbnail_size_bytes(self) -> int:
        return len(self.thumbnail_bytes)

    @property
    def total_size_bytes(self) -> int:
        return self.size_bytes + self.thumbnail_size_bytes


def photo_storage_usage_bytes(upload_dir: Path) -> int:
    if not upload_dir.exists():
        return 0
    return sum(path.stat().st_size for path in upload_dir.rglob("*") if path.is_file())


def ensure_photo_storage_capacity(upload_dir: Path, incoming_bytes: int, max_bytes: int):
    current_bytes = photo_storage_usage_bytes(upload_dir)
    if current_bytes + incoming_bytes > max_bytes:
        raise HTTPException(status_code=400, detail="Photo storage is full")


def process_photo_upload(
    content: bytes,
    *,
    display_max_width: int,
    thumbnail_max_width: int,
    jpeg_quality: int,
) -> ProcessedPhoto:
    try:
        with Image.open(io.BytesIO(content)) as image:
            if getattr(image, "is_animated", False):
                raise HTTPException(status_code=400, detail="Animated images are not supported")
            image.verify()

        with Image.open(io.BytesIO(content)) as image:
            display_image = ImageOps.exif_transpose(image)
            display_image = _flatten_to_rgb(display_image)
            display_image.thumbnail(
                (display_max_width, display_max_width),
                Image.Resampling.LANCZOS,
            )

            thumbnail_image = display_image.copy()
            thumbnail_image.thumbnail(
                (thumbnail_max_width, thumbnail_max_width),
                Image.Resampling.LANCZOS,
            )

            display_bytes = _encode_jpeg(display_image, jpeg_quality)
            thumbnail_bytes = _encode_jpeg(thumbnail_image, jpeg_quality)

            return ProcessedPhoto(
                display_bytes=display_bytes,
                thumbnail_bytes=thumbnail_bytes,
                width=display_image.width,
                height=display_image.height,
            )
    except HTTPException:
        raise
    except (OSError, SyntaxError, UnidentifiedImageError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid image data") from exc


def _flatten_to_rgb(image: Image.Image) -> Image.Image:
    if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        background.alpha_composite(rgba)
        return background.convert("RGB")
    if image.mode != "RGB":
        return image.convert("RGB")
    return image.copy()


def _encode_jpeg(image: Image.Image, quality: int) -> bytes:
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=quality, optimize=True, progressive=True)
    return output.getvalue()
