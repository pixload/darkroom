import os
import shutil
import subprocess
import uuid
import logging
import hashlib
from typing import Optional
from pathlib import Path

import boto3
import requests
from botocore.exceptions import NoCredentialsError
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse

# --- Configuration & Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pixload-darkroom")

app = FastAPI(title="Pixload Darkroom", version="1.3 (Surgical)")

# --- Environment Variables ---
AUTH_TOKEN = os.getenv("PIXLOAD_IMAGE_TOKEN", "changeme")
STORAGE_PROVIDER = os.getenv("STORAGE_PROVIDER", "r2")
S3_ENDPOINT = os.getenv("S3_ENDPOINT_URL")
S3_BUCKET = os.getenv("S3_BUCKET", "pixload")
S3_REGION = os.getenv("S3_REGION", "auto")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY_ID")
S3_SECRET_KEY = os.getenv("S3_SECRET_ACCESS_KEY")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://cdn.pixload.events")
MAGICK_THREAD_LIMIT = os.getenv("MAGICK_THREAD_LIMIT", "1")

# Strict MIME Type Mapping
MIME_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "avif": "image/avif",
    "heic": "image/heic"
}

# --- Helpers ---

def get_s3_client():
    return boto3.client(
        's3',
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name=S3_REGION
    )

def upload_to_s3(file_path: str, key_name: str, content_type: str):
    s3 = get_s3_client()
    try:
        s3.upload_file(
            file_path, 
            S3_BUCKET, 
            key_name, 
            ExtraArgs={'ContentType': content_type}
        )
        # Clean URL to avoid double slashes
        base = PUBLIC_BASE_URL.rstrip("/")
        key = key_name.lstrip("/")
        return f"{base}/{key}"
    except Exception as e:
        logger.error(f"S3 Upload Error: {e}")
        return None

def calculate_sha256(file_path: Path) -> str:
    """Calculates SHA256 hash of a file efficiently using chunks."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def cleanup_temp_dir(path: Path):
    try:
        shutil.rmtree(path, ignore_errors=True)
        logger.debug(f"Cleaned up {path}")
    except Exception as e:
        logger.warning(f"Cleanup failed for {path}: {e}")

# --- Routes ---

@app.get("/ping")
def ping():
    return {"ok": True, "engine": "Pixload Darkroom v1.3"}

@app.post("/convert")
async def convert(
    background_tasks: BackgroundTasks,
    # Inputs
    file: UploadFile = File(None),
    src_url: str = Form(None),
    token: str = Form(...),
    # Transformation
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
    # Output & Storage
    upload_s3: bool = Form(False),
    key_name: str = Form(None),   # Forced name (Optional)
    key_prefix: str = Form(None), # Folder (e.g., events/123)
    return_binary: bool = Form(False),
    # Advanced
    avif_speed: str = Form("6"),
):
    # --- Security Checks ---
    if token != AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if not file and not src_url:
        raise HTTPException(status_code=400, detail="Provide 'file' or 'src_url'")

    if format not in MIME_TYPES:
         raise HTTPException(status_code=400, detail=f"Format unsupported: {format}")

    # --- Setup ---
    request_id = str(uuid.uuid4())
    tmpd = Path(f"/tmp/{request_id}")
    tmpd.mkdir(parents=True, exist_ok=True)
    
    # Register cleanup as a background task for safety
    background_tasks.add_task(cleanup_temp_dir, tmpd)
    
    input_path = tmpd / "source"
    overlay_path = tmpd / "overlay_source"
    output_filename = f"output.{format}"
    output_path = tmpd / output_filename

    try:
        # --- 1. Download Source ---
        if file:
            with open(input_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
        elif src_url:
            with requests.get(src_url, stream=True, timeout=15) as r:
                r.raise_for_status()
                with open(input_path, "wb") as f:
                    shutil.copyfileobj(r.raw, f)

        # --- 2. Processing Setup ---
        has_overlay = False
        if overlay_url:
            try:
                with requests.get(overlay_url, stream=True, timeout=10) as r:
                    r.raise_for_status()
                    with open(overlay_path, "wb") as f:
                        shutil.copyfileobj(r.raw, f)
                has_overlay = True
            except Exception as e:
                logger.warning(f"Overlay download failed: {e}")

        # Construct ImageMagick 7 Command
        cmd = ["magick", str(input_path)]
        cmd.extend(["-limit", "thread", MAGICK_THREAD_LIMIT])
        cmd.append("-auto-orient")
        cmd.extend(["-colorspace", "sRGB"])

        if strip_exif:
            cmd.append("-strip")

        if size:
            cmd.extend(["-filter", "Lanczos"])
            if square:
                cmd.extend(["-resize", f"{size}x{size}^"])
                cmd.extend(["-gravity", "center", "-extent", f"{size}x{size}"])
            else:
                cmd.extend(["-resize", f"{size}x{size}>"])

        # Overlay Logic
        if has_overlay:
            target_width = size if size else 1920
            logo_width = int(target_width * (overlay_scale / 100))
            # Protect against division by zero or extremely small logos
            logo_width = max(logo_width, 10) 
            
            gravity = "South" if overlay_safe_zone else "SouthEast"
            geometry = "+0+250" if overlay_safe_zone else "+50+50"

            cmd.append("(")
            cmd.append(str(overlay_path))
            cmd.extend(["-resize", f"{logo_width}x"])
            if overlay_opacity < 100:
                factor = overlay_opacity / 100.0
                cmd.extend(["-channel", "A", "-evaluate", "multiply", str(factor)])
            cmd.append(")")
            cmd.extend(["-gravity", gravity])
            cmd.extend(["-geometry", geometry])
            cmd.append("-composite")

        # Subtle sharpening for web display
        cmd.extend(["-unsharp", "0x0.75+0.75+0.008"])

        # Encoding Parameters
        if format in ["jpg", "jpeg"]:
            cmd.extend(["-quality", str(q)])
            cmd.extend(["-interlace", "Plane"])
        elif format == "avif":
            # For ImageMagick 7 static binary, heic:speed controls libheif performance
            cmd.extend(["-quality", str(q)])
            cmd.extend(["-define", f"heic:speed={avif_speed}"]) 
        elif format == "webp":
            cmd.extend(["-quality", str(q)])
            cmd.extend(["-define", "webp:method=6"])

        cmd.append(str(output_path))

        logger.info(f"Running: {' '.join(cmd)}")
        
        # --- EXECUTION ---
        # Capture stderr to debug ImageMagick specific errors
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.error(f"ImageMagick Failed: {result.stderr}")
            raise HTTPException(status_code=500, detail=f"Processing Engine Error: {result.stderr}")

        # --- 3. Response Construction ---
        response_data = {"ok": True, "format": format}
        final_content_type = MIME_TYPES[format]

        if upload_s3:
            # Smart naming generation if key_name is missing
            if not key_name:
                in_hash = calculate_sha256(input_path)
                out_hash = calculate_sha256(output_path)
                size_tag = str(size) if size else "orig"
                clean_ext = format.replace("jpeg", "jpg") 
                generated_name = f"{in_hash[:32]}_{size_tag}_{out_hash[:8]}.{clean_ext}"
                
                # Folder/Prefix handling
                if key_prefix:
                    clean_prefix = key_prefix.strip("/")
                    key_name = f"{clean_prefix}/{generated_name}"
                else:
                    key_name = generated_name
            
            logger.info(f"Uploading to S3: {key_name} as {final_content_type}")
            public_url = upload_to_s3(str(output_path), key_name, final_content_type)
            
            if public_url:
                response_data["url"] = public_url
                response_data["key"] = key_name
            else:
                response_data["error"] = "Upload failed"

        if return_binary:
            clean_name = key_name.split("/")[-1] if key_name else output_filename
            return FileResponse(
                path=output_path, 
                media_type=final_content_type,
                filename=clean_name
            )

        return JSONResponse(content=response_data)

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Process Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
