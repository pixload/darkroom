# Pixload Darkroom

High-performance image processing microservice powered by [libvips](https://www.libvips.org/).

Built for [Pixload](https://pixload.app/) — processing thousands of high-resolution event photos where color accuracy, speed, and reliability matter.

## Features

- **Fast.** libvips processes images 3–10x faster than ImageMagick with a fraction of the memory (streaming pipeline, no full-image decompression).
- **Color-accurate.** Automatic AdobeRGB/P3 → sRGB conversion. No more washed-out colors on web displays.
- **HEIC native.** Ingests Apple/iOS photos directly via libheif.
- **Smart watermarking.** Overlay logos with configurable scale, opacity, and "Safe Zone" positioning for vertical social formats (TikTok, Reels).
- **Sharp output.** Lanczos resampling + subtle sharpening for crisp, gallery-ready results.
- **Secure.** SSRF protection on all remote URLs, enforced upload size limits, token authentication.

## Quick Start

```bash
git clone https://github.com/pixload/darkroom.git
cd darkroom
cp .env.example .env   # edit with your values
docker-compose up -d --build
```

The service runs on port `41870` by default (configurable via `PIXLOAD_PORT`).

Health check:

```bash
curl http://localhost:41870/ping
```

## API

### `POST /convert`

Accepts multipart form data. All requests require a valid `token`.

#### Input

| Parameter | Type | Description |
|-----------|------|-------------|
| `token` | string | **Required.** API authentication token. |
| `file` | file | Image file upload (multipart). |
| `src_url` | string | Or fetch image from a remote URL. Provide `file` or `src_url`. |

#### Transform

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `format` | string | `jpg` | Output format: `jpg`, `png`, `webp`, `avif`, `heic`. |
| `q` | int | `80` | Quality (1–100). For AVIF, 60–65 is a good starting point. |
| `size` | int | — | Resize to fit within `size`x`size` pixels (long edge, shrink only). |
| `square` | bool | `false` | Center-crop to exact `size`x`size` square. |
| `strip_exif` | bool | `false` | Remove all metadata (EXIF, IPTC, XMP). |

#### Overlay / Watermark

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `overlay_url` | string | — | URL of a PNG logo to composite onto the image. |
| `overlay_scale` | int | `15` | Logo width as percentage of image width. |
| `overlay_opacity` | int | `100` | Opacity (0–100). 30–50 works well for watermarks. |
| `overlay_safe_zone` | bool | `true` | Position logo centered, 250px from bottom (avoids TikTok/Reels UI). When `false`, places bottom-right +50px. |

#### Output

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `upload_s3` | bool | `false` | Upload result to configured S3/R2 bucket. |
| `key_name` | string | — | Force a specific S3 key. Auto-generated from content hash if omitted. |
| `key_prefix` | string | — | S3 folder prefix (e.g. `events/123`). |
| `return_binary` | bool | `false` | Return the processed image as the HTTP response body. |

#### Advanced

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `avif_speed` | int | `6` | libheif encoder speed (0 = slowest/best, 9 = fastest). |

### Examples

**Convert HEIC to AVIF, upload to S3:**

```bash
curl -X POST http://localhost:41870/convert \
  -F "token=your_token" \
  -F "file=@photo.heic" \
  -F "format=avif" \
  -F "q=65" \
  -F "upload_s3=true"
```

**Resize + watermark from URL:**

```bash
curl -X POST http://localhost:41870/convert \
  -F "token=your_token" \
  -F "src_url=https://example.com/photo.jpg" \
  -F "size=1920" \
  -F "overlay_url=https://example.com/logo.png" \
  -F "overlay_scale=15" \
  -F "overlay_safe_zone=true" \
  -F "upload_s3=true"
```

**Get binary response (e.g. for proxying):**

```bash
curl -X POST http://localhost:41870/convert \
  -F "token=your_token" \
  -F "file=@photo.jpg" \
  -F "format=webp" \
  -F "size=800" \
  -F "return_binary=true" \
  -o output.webp
```

## Configuration

Copy `.env.example` to `.env` and adjust:

| Variable | Default | Description |
|----------|---------|-------------|
| `PIXLOAD_IMAGE_TOKEN` | — | API token. |
| `S3_ENDPOINT_URL` | — | S3-compatible endpoint (R2, MinIO, AWS). |
| `S3_BUCKET` | `pixload` | Target bucket. |
| `S3_REGION` | `auto` | Bucket region. |
| `S3_ACCESS_KEY_ID` | — | Storage credentials. |
| `S3_SECRET_ACCESS_KEY` | — | Storage credentials. |
| `PUBLIC_BASE_URL` | — | CDN base URL for generated links. |
| `MAX_UPLOAD_SIZE_MB` | `100` | Maximum upload size. |
| `RATE_LIMIT` | `30/minute` | Rate limit per client IP. |
| `PIXLOAD_CPU_LIMIT` | `2` | Docker CPU quota. |
| `PIXLOAD_MEMORY_LIMIT` | `2G` | Docker memory limit. |
| `PIXLOAD_TMPFS_SIZE` | `2g` | tmpfs size for temp processing files. |

## Development

```bash
# Install deps
pip install -r requirements.txt

# Run locally (requires libvips on your system)
uvicorn main:app --reload --port 8080

# Run tests
pytest

# Lint
ruff check .
ruff format --check .
```

## License

MIT — see [LICENCE](LICENCE) for details.

Built by the [Pixload](https://pixload.app/) engineering team.
