"""Pixload Darkroom — High-performance image processing microservice."""

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import shutil
import socket
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import boto3
import pyvips
import requests
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# --- Configuration & Logging ---


class JsonFormatter(logging.Formatter):
    """Structured JSON log formatter for production observability."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "msg": record.getMessage(),
            "logger": record.name,
        }
        if hasattr(record, "request_id"):
            entry["request_id"] = record.request_id
        if hasattr(record, "duration_ms"):
            entry["duration_ms"] = record.duration_ms
        if hasattr(record, "image_format"):
            entry["format"] = record.image_format
        if hasattr(record, "size"):
            entry["size"] = record.size
        if record.exc_info and record.exc_info[0]:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger = logging.getLogger("pixload-darkroom")
logger.setLevel(logging.INFO)
logger.addHandler(handler)
logger.propagate = False


# --- App & Rate Limiting ---

RATE_LIMIT = os.getenv("RATE_LIMIT", "30/minute")

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Pixload Darkroom", version="2.0")
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"ok": False, "detail": "Rate limit exceeded. Slow down."},
    )


# --- Environment ---

AUTH_TOKEN = os.getenv("PIXLOAD_IMAGE_TOKEN", "changeme")

S3_ENDPOINT = os.getenv("S3_ENDPOINT_URL")
S3_BUCKET = os.getenv("S3_BUCKET", "pixload")
S3_REGION = os.getenv("S3_REGION", "auto")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY_ID")
S3_SECRET_KEY = os.getenv("S3_SECRET_ACCESS_KEY")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://cdn.pixload.events")

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_SIZE_MB", "100")) * 1024 * 1024

MIME_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "avif": "image/avif",
    "heic": "image/heic",
}


# --- Helpers ---


def validate_url(url: str) -> str:
    """Block SSRF attempts by rejecting URLs that resolve to internal networks."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only HTTP/HTTPS URLs are allowed")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Invalid URL: missing hostname")

    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except socket.gaierror as err:
        raise ValueError(f"Cannot resolve hostname: {hostname}") from err

    for _, _, _, _, sockaddr in addrinfo:
        ip = ipaddress.ip_address(sockaddr[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError("URLs pointing to internal networks are not allowed")

    return url


def download_file(url: str, dest: Path, timeout: int = 15) -> None:
    """Download a remote file with SSRF protection and size limit."""
    validate_url(url)
    with requests.get(url, stream=True, timeout=timeout, allow_redirects=False) as r:
        if r.is_redirect or r.is_permanent_redirect:
            raise ValueError("Redirects are not allowed for security reasons")
        r.raise_for_status()

        content_length = r.headers.get("Content-Length")
        if content_length and content_length.isdigit() and int(content_length) > MAX_UPLOAD_BYTES:
            raise ValueError(f"Remote file too large ({int(content_length)} bytes)")

        downloaded = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                downloaded += len(chunk)
                if downloaded > MAX_UPLOAD_BYTES:
                    max_mb = MAX_UPLOAD_BYTES // 1024 // 1024
                    raise ValueError(f"Download exceeded {max_mb}MB limit")
                f.write(chunk)


def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name=S3_REGION,
    )


def upload_to_s3(file_path: str, key_name: str, content_type: str) -> str | None:
    s3 = get_s3_client()
    try:
        s3.upload_file(
            file_path,
            S3_BUCKET,
            key_name,
            ExtraArgs={"ContentType": content_type},
        )
        base = PUBLIC_BASE_URL.rstrip("/")
        key = key_name.lstrip("/")
        return f"{base}/{key}"
    except Exception as e:
        logger.error("S3 upload failed: %s", e)
        return None


def calculate_sha256(file_path: Path) -> str:
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def cleanup_temp_dir(path: Path):
    shutil.rmtree(path, ignore_errors=True)


# --- Image Processing (libvips) ---


def apply_overlay(
    image: pyvips.Image,
    overlay_path: Path,
    target_width: int,
    scale_pct: int,
    safe_zone: bool,
    opacity: int,
) -> pyvips.Image:
    """Composite a watermark overlay onto the image."""
    overlay = pyvips.Image.new_from_file(str(overlay_path), access="sequential")

    # Scale overlay relative to target width
    logo_width = max(int(target_width * scale_pct / 100), 10)
    overlay = overlay.resize(logo_width / overlay.width)

    # Ensure overlay has alpha
    if not overlay.hasalpha():
        overlay = overlay.addalpha()

    # Apply opacity
    if opacity < 100:
        alpha = overlay.extract_band(overlay.bands - 1) * (opacity / 100.0)
        overlay = overlay.extract_band(0, n=overlay.bands - 1).bandjoin(alpha)

    # Ensure main image has alpha for compositing
    if not image.hasalpha():
        image = image.addalpha()

    # Position: safe_zone = centered 250px from bottom, otherwise bottom-right +50px
    if safe_zone:
        x = (image.width - overlay.width) // 2
        y = image.height - overlay.height - 250
    else:
        x = image.width - overlay.width - 50
        y = image.height - overlay.height - 50

    x = max(0, int(x))
    y = max(0, int(y))

    return image.composite2(overlay, "over", x=x, y=y)


def process_image(
    input_path: Path,
    output_path: Path,
    *,
    fmt: str,
    quality: int,
    size: int | None,
    square: bool,
    strip_exif: bool,
    overlay_path: Path | None,
    overlay_scale: int,
    overlay_safe_zone: bool,
    overlay_opacity: int,
    avif_speed: int,
) -> None:
    """Load, transform, and encode an image using libvips."""
    image = pyvips.Image.new_from_file(str(input_path), access="sequential")
    image = image.autorot()

    if image.interpretation != "srgb":
        image = image.colourspace("srgb")

    # Resize
    if size:
        if square:
            # Cover then center-crop
            scale = max(size / image.width, size / image.height)
            image = image.resize(scale, kernel="lanczos3")
            left = (image.width - size) // 2
            top = (image.height - size) // 2
            image = image.crop(left, top, size, size)
        else:
            # Fit within bounding box (shrink only)
            if image.width > size or image.height > size:
                scale = min(size / image.width, size / image.height)
                image = image.resize(scale, kernel="lanczos3")

    # Watermark
    if overlay_path and overlay_path.exists():
        image = apply_overlay(
            image,
            overlay_path,
            target_width=size or 1920,
            scale_pct=overlay_scale,
            safe_zone=overlay_safe_zone,
            opacity=overlay_opacity,
        )

    # Subtle sharpening for web display
    image = image.sharpen(sigma=0.75)

    # Flatten alpha for formats that don't support transparency
    if fmt in ("jpg", "jpeg") and image.hasalpha():
        image = image.flatten(background=[255, 255, 255])

    # Encode
    save_opts = {"strip": strip_exif}

    if fmt in ("jpg", "jpeg"):
        save_opts.update(Q=quality, interlace=True, optimize_coding=True)
    elif fmt == "png":
        save_opts.update(compression=6)
    elif fmt == "webp":
        save_opts.update(Q=quality, effort=6)
    elif fmt == "avif":
        save_opts.update(Q=quality, speed=avif_speed)
    elif fmt == "heic":
        save_opts.update(Q=quality)

    image.write_to_file(str(output_path), **save_opts)


# --- Routes ---


@app.get("/ping")
def ping():
    vips_ver = f"{pyvips.version(0)}.{pyvips.version(1)}.{pyvips.version(2)}"
    all_formats = pyvips.get_suffixes()
    supported = [s.lstrip(".") for s in all_formats if s.lstrip(".") in MIME_TYPES]
    return {
        "ok": True,
        "engine": "Pixload Darkroom v2.0",
        "libvips": vips_ver,
        "formats": sorted(set(supported)),
    }


@app.post("/convert")
@limiter.limit(RATE_LIMIT)
async def convert(
    request: Request,
    background_tasks: BackgroundTasks,
    # Input
    file: UploadFile = File(None),
    src_url: str = Form(None),
    token: str = Form(...),
    # Transform
    format: str = Form("jpg"),
    q: int = Form(80),
    size: int = Form(None),
    square: bool = Form(False),
    strip_exif: bool = Form(False),
    # Overlay
    overlay_url: str = Form(None),
    overlay_scale: int = Form(15),
    overlay_safe_zone: bool = Form(True),
    overlay_opacity: int = Form(100),
    # Output
    upload_s3: bool = Form(False),
    key_name: str = Form(None),
    key_prefix: str = Form(None),
    return_binary: bool = Form(False),
    # Advanced
    avif_speed: int = Form(6),
):
    t0 = time.monotonic()

    # --- Validation ---
    if not hmac.compare_digest(token, AUTH_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized")

    if not file and not src_url:
        raise HTTPException(status_code=400, detail="Provide 'file' or 'src_url'")

    if format not in MIME_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")

    if not 1 <= q <= 100:
        raise HTTPException(status_code=400, detail="Quality must be between 1 and 100")

    if not 0 <= avif_speed <= 9:
        raise HTTPException(status_code=400, detail="avif_speed must be between 0 and 9")

    if size is not None and (size < 1 or size > 16384):
        raise HTTPException(status_code=400, detail="size must be between 1 and 16384")

    if not 1 <= overlay_scale <= 100:
        raise HTTPException(status_code=400, detail="overlay_scale must be between 1 and 100")

    if not 0 <= overlay_opacity <= 100:
        raise HTTPException(status_code=400, detail="overlay_opacity must be between 0 and 100")

    # --- Workspace ---
    request_id = str(uuid.uuid4())
    tmpdir = Path(f"/tmp/{request_id}")
    tmpdir.mkdir(parents=True, exist_ok=True)
    background_tasks.add_task(cleanup_temp_dir, tmpdir)

    input_path = tmpdir / "source"
    overlay_local = tmpdir / "overlay"
    output_path = tmpdir / f"output.{format}"

    try:
        # --- Acquire source image ---
        if file:
            written = 0
            with open(input_path, "wb") as buf:
                while True:
                    chunk = await file.read(8192)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_UPLOAD_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail=f"File exceeds {MAX_UPLOAD_BYTES // 1024 // 1024}MB limit",
                        )
                    buf.write(chunk)
        else:
            try:
                download_file(src_url, input_path)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e

        # --- Acquire overlay ---
        has_overlay = False
        if overlay_url:
            try:
                download_file(overlay_url, overlay_local, timeout=10)
                has_overlay = True
            except Exception as e:
                logger.warning("Overlay download failed: %s", e)

        # --- Process ---
        process_image(
            input_path,
            output_path,
            fmt=format,
            quality=q,
            size=size,
            square=square,
            strip_exif=strip_exif,
            overlay_path=overlay_local if has_overlay else None,
            overlay_scale=overlay_scale,
            overlay_safe_zone=overlay_safe_zone,
            overlay_opacity=overlay_opacity,
            avif_speed=avif_speed,
        )

        # --- Response ---
        duration_ms = round((time.monotonic() - t0) * 1000)
        content_type = MIME_TYPES[format]
        response_data = {"ok": True, "format": format}

        if upload_s3:
            if not key_name:
                in_hash = calculate_sha256(input_path)
                out_hash = calculate_sha256(output_path)
                size_tag = str(size) if size else "orig"
                ext = format.replace("jpeg", "jpg")
                generated_name = f"{in_hash[:32]}_{size_tag}_{out_hash[:8]}.{ext}"

                if key_prefix:
                    key_name = f"{key_prefix.strip('/')}/{generated_name}"
                else:
                    key_name = generated_name

            logger.info(
                "Uploading to S3: %s",
                key_name,
                extra={
                    "request_id": request_id,
                    "duration_ms": duration_ms,
                    "image_format": format,
                },
            )
            public_url = upload_to_s3(str(output_path), key_name, content_type)
            if public_url:
                response_data["url"] = public_url
                response_data["key"] = key_name
            else:
                response_data["error"] = "S3 upload failed"

        logger.info(
            "Processed %s in %dms",
            format,
            duration_ms,
            extra={
                "request_id": request_id,
                "duration_ms": duration_ms,
                "image_format": format,
                "size": size,
            },
        )

        if return_binary:
            filename = key_name.split("/")[-1] if key_name else f"output.{format}"
            return FileResponse(
                path=str(output_path),
                media_type=content_type,
                filename=filename,
                background=background_tasks,
            )

        return JSONResponse(content=response_data)

    except HTTPException:
        raise
    except pyvips.Error as e:
        logger.error("Image processing failed: %s", e, extra={"request_id": request_id})
        raise HTTPException(status_code=500, detail="Image processing failed") from e
    except Exception as e:
        logger.error("Unexpected error: %s", e, exc_info=True, extra={"request_id": request_id})
        raise HTTPException(status_code=500, detail=str(e)) from e
