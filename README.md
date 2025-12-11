# Pixload Darkroom

A high-performance, color-managed image processing microservice built for production.

**Pixload Darkroom** is a standalone microservice designed to handle heavy image transformations with surgical precision. Unlike standard resizing scripts that just "squash pixels", Darkroom treats image processing like a digital development lab: preserving color integrity, sharpness, and metadata logic.

## Why "Darkroom"?

At [Pixload](https://pixload.app/), we process thousands of high-resolution event photos. We needed a pipeline that was fast enough for live events but sharp enough for professional photographers. We couldn't find a tool that handled **ICC Color Profiles** and **HEIC ingestion** correctly out of the box, so we built Darkroom.

## Key Features

- **Native HEIC Support:** Seamlessly ingests Apple/iOS photos via `libheif` without quality loss.
    
- **Professional Color Management:** Automatically converts AdobeRGB/P3 to **sRGB** using internal color management to prevent "washed out" colors on web displays.
    
- **Smart Watermarking:** Built-in engine to overlay logos with intelligent "Safe Zone" positioning for vertical social media (TikTok/Instagram Reels).
    
- **Surgical Resizing:** Uses **Lanczos** resampling (not Bicubic) paired with adaptive Unsharp Masking for crisp, gallery-ready thumbnails.
    
- **Hardware Accelerated:**
    - **AVIF:** Uses `SVT-AV1` optimized for multi-core CPUs.
    - **JPEG:** Uses `libjpeg-turbo` for SIMD-accelerated compression.
    
- **Hybrid Response Mode:** Can return the binary file for immediate processing AND upload to S3 simultaneously (returning the URL in headers), reducing latency.
    
- **Resource Safety:** Built-in thread limiting for ImageMagick to prevent CPU context-switching saturation under heavy concurrent loads.
    

## Architecture

The service wraps **ImageMagick 7** and **avifenc** inside a **FastAPI** shell, running in a highly optimized Docker container.

1. **Input:** JPG, PNG, WEBP, HEIC (Streamed).
    
2. **Processing pipeline:**
    - Auto-orientation (EXIF).
    - Color Space Conversion (to sRGB).
    - Lanczos Resampling.
    - **Smart Overlay/Composite** (Optional).
    - Output Sharpening (Web-optimized).
    
3. **Encoding:** SVT-AV1 or TurboJPEG.
    
4. **Output:** JPG, PNG, WEBP, AVIF.
    

## Quick Start

### Prerequisites

- Docker & Docker Compose.
    

### Installation

1. **Clone the repository:**
    
    Bash
    
    ```
    git clone https://github.com/pixload/darkroom.git
    cd darkroom
    ```
    
2. Configure Environment:
    
    Create a .env file based on your needs (DO NOT commit this file):
    
    Ini, TOML
    
    ```
    # Secrets
    PIXLOAD_IMAGE_TOKEN=your_super_secret_token
    
    # S3 / R2 Configuration
    STORAGE_PROVIDER=r2
    S3_ENDPOINT_URL=https://your-id.r2.cloudflarestorage.com
    S3_BUCKET=pixload
    S3_ACCESS_KEY_ID=your_key
    S3_SECRET_ACCESS_KEY=your_secret
    PUBLIC_BASE_URL=https://cdn.pixload.events
    ```
    
3. **Build & Run:**
    
    Bash
    
    ```
    docker-compose up -d --build
    ```
    
    The service is now running on port `41870` (default).
    

## Performance Tuning

For high-concurrency environments (e.g., 50+ simultaneous uploads), we use a specific strategy to balance FastAPI workers and ImageMagick threads to avoid locking the CPU.

Recommended `.env` settings for a 12-core CPU environment:

Ini, TOML

```
# Force ImageMagick to use a single thread per process.
# We rely on FastAPI workers (Uvicorn) for parallelism.
MAGICK_THREAD_LIMIT=1
OMP_NUM_THREADS=1

# Hardware limits for the container
PIXLOAD_CPU_LIMIT=12
PIXLOAD_MEMORY_LIMIT=16G
```

## API Usage

**Endpoint:** `POST /convert`

### Example 1: Hybrid Mode (Upload + Download)

Uploads the result to S3 AND returns the binary file immediately.

Bash

```
curl -X POST "http://localhost:41870/convert" \
  -F "token=your_secure_token" \
  -F "file=@photo.heic" \
  -F "format=avif" \
  -F "upload_s3=true" \
  -F "return_binary=true" \
  -v
```

### Example 2: Watermarking with "Safe Zone"

Downloads source from URL, applies a logo (15% width), and positions it to avoid TikTok/Instagram UI.

Bash

```
curl -X POST "http://localhost:41870/convert" \
  -F "token=your_secure_token" \
  -F "src_url=https://example.com/photo.jpg" \
  -F "overlay_url=https://example.com/logo.png" \
  -F "overlay_scale=15" \
  -F "overlay_safe_zone=true" \
  -F "upload_s3=true"
```

### General Parameters

|**Parameter**|**Type**|**Default**|**Description**|
|---|---|---|---|
|`file`|File|-|Binary file upload (Multipart).|
|`src_url`|String|-|Or download source image from a remote URL.|
|`format`|String|`jpg`|Output format: `jpg`, `webp`, `avif`, `png`.|
|`q`|Int|`80`|Quality (0-100). For AVIF, 60-65 is recommended.|
|`size`|Int|`None`|Resize (long edge) in pixels. Maintains aspect ratio.|
|`square`|Bool|`0`|If 1, center-crops to a square (useful for thumbnails).|
|`strip_exif`|Bool|`False`|If True, removes all metadata (EXIF/IPTC/XMP).|
|`upload_s3`|Bool|`False`|If True, uploads the result to the configured S3 bucket.|
|`return_binary`|Bool|`False`|If True, returns content in body even if `upload_s3` is enabled.|

### Overlay & Watermarking Parameters

| Parameter           | Type   | Default | Description                                                                   |
| :------------------ | :----- | :------ | :---------------------------------------------------------------------------- |
| `overlay_url`       | String | `None`  | URL of the PNG logo/watermark to superimpose.                                 |
| `overlay_scale`     | Int    | `15`    | Size of the overlay relative to the image width (in %).                       |
| `overlay_opacity`   | Int    | `100`   | Opacity of the overlay (0-100). Use 30-50 for watermarks.                     |
| `overlay_safe_zone` | Bool   | `True`  | If True, positions logo higher to avoid UI on vertical videos (TikTok/Reels). |
### Advanced Parameters (Surgical Control)

| **Parameter** | **Default** | **Description**                                                 |
| ------------- | ----------- | --------------------------------------------------------------- |
| `avif_speed`  | `6`         | SVT-AV1 preset (0-10). 6 is the best speed/compression balance. |
| `avif_depth`  | `8`         | Bit depth (8 or 10). 10-bit prevents banding in gradients.      |
| `avif_yuv`    | `420`       | Chroma subsampling. 444 is sharper for graphics.                |

## License

This project is licensed under the MIT License - see the LICENSE file for details.

<p align="center">

Built with ❤️ by the <a href="https://pixload.app">Pixload</a> Engineering Team.

</p> 
