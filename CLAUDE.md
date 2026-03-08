# CLAUDE.md — Pixload Darkroom

## Project Overview

Pixload Darkroom is a high-performance, color-managed image processing microservice built with **Python 3.12** and **FastAPI**. It wraps **ImageMagick 7** to handle image transformations (format conversion, resizing, cropping, watermarking) and uploads results to S3-compatible storage (Cloudflare R2, AWS S3, MinIO).

**Version:** 1.3 (Surgical)
**License:** MIT

## Repository Structure

```
darkroom/
├── main.py              # Entire application — FastAPI routes, helpers, config
├── requirements.txt     # Python dependencies (fastapi, uvicorn, boto3, requests)
├── Dockerfile           # Production container (python:3.12-slim + ImageMagick 7)
├── docker-compose.yml   # Orchestration with resource limits and tmpfs
├── .env.example         # Environment variable template
├── README.md            # User-facing documentation
└── CLAUDE.md            # This file
```

This is a **single-file application** — all business logic lives in `main.py` (~270 lines).

## Architecture

- **Framework:** FastAPI with Uvicorn (2 workers by default)
- **Image engine:** ImageMagick 7 installed via AppImage extraction in Docker
- **Storage:** S3-compatible via boto3 (Cloudflare R2 default)
- **Deployment:** Docker / Docker Compose, Cloud Run compatible

### API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/ping` | GET | Health check |
| `/convert` | POST | Image processing (multipart form) |

### Request Flow (`/convert`)

1. Auth check via `token` form field
2. Accept input as file upload or remote URL (`src_url`)
3. Build and run ImageMagick command with requested transformations
4. Optionally upload result to S3 and/or return binary response
5. Cleanup temp directory via FastAPI `BackgroundTasks`

## Development

### Prerequisites

- Python 3.12
- ImageMagick 7 (`magick` binary on PATH) for local dev
- Docker + Docker Compose for containerized runs

### Running Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server (requires ImageMagick 7 installed locally)
uvicorn main:app --host 0.0.0.0 --port 8080
```

### Running with Docker

```bash
cp .env.example .env   # Edit with real values
docker-compose up -d --build
# Service available at localhost:${PIXLOAD_PORT}
```

### Testing

There is **no test suite** currently. When adding tests:
- Use `pytest` with `httpx.AsyncClient` for FastAPI endpoint testing
- Mock S3 uploads with `moto` or similar
- Provide sample images in a `tests/fixtures/` directory

### Linting / Formatting

No linting or formatting tools are configured. If adding them, prefer:
- `ruff` for linting and formatting (fast, covers flake8 + black + isort)

## Key Conventions

### Code Style
- **snake_case** for all functions and variables
- **UPPER_CASE** for environment variable names and module-level constants
- Standard library imports first, then third-party, then local
- All env vars read at module level via `os.getenv()` with sensible defaults

### Error Handling
- Raise `HTTPException` for client/server errors in routes
- Catch and re-raise `HTTPException` to avoid masking it in the outer `except`
- Log errors with `logger.error()` including `exc_info=True` for stack traces

### File Naming
- Output files use SHA256-based naming: `{input_hash[:32]}_{size}_{output_hash[:8]}.{ext}`
- S3 keys support optional `key_prefix` for folder organization

### Security
- API protected by `PIXLOAD_IMAGE_TOKEN` — never commit real tokens
- Never commit `.env` files (already in `.gitignore`)
- ImageMagick thread limit set to 1 by default to prevent CPU saturation

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PIXLOAD_IMAGE_TOKEN` | `changeme` | API authentication token |
| `STORAGE_PROVIDER` | `r2` | S3-compatible provider |
| `S3_ENDPOINT_URL` | — | Storage endpoint URL |
| `S3_BUCKET` | `pixload` | Target bucket |
| `S3_REGION` | `auto` | Bucket region |
| `S3_ACCESS_KEY_ID` | — | Storage credentials |
| `S3_SECRET_ACCESS_KEY` | — | Storage credentials |
| `PUBLIC_BASE_URL` | `https://cdn.pixload.events` | CDN base for public URLs |
| `MAGICK_THREAD_LIMIT` | `1` | ImageMagick thread cap |
| `PIXLOAD_CPU_LIMIT` | `2` | Docker CPU quota |
| `PIXLOAD_MEMORY_LIMIT` | `2G` | Docker memory limit |
| `PIXLOAD_TMPFS_SIZE` | `2g` | Temp filesystem size |
| `MAX_UPLOAD_SIZE_MB` | `100` | Upload size cap |
| `PROCESS_TIMEOUT_SEC` | `60` | Processing timeout |

## Guidelines for AI Assistants

- This is a **monolith single-file service** — resist splitting into multiple modules unless the file grows significantly (500+ lines)
- Image processing relies on **shelling out to `magick`** via `subprocess.run` — keep this pattern, do not switch to Python imaging libraries
- The Dockerfile uses a specific ImageMagick AppImage extraction technique — do not change the installation method without good reason
- Temp files go in `/tmp/{uuid}` and are cleaned up via `BackgroundTasks` — maintain this pattern
- S3 upload is optional per-request — the service can return binary responses directly
- When modifying the `/convert` endpoint, preserve backward compatibility of existing form parameters
- Do not add heavyweight dependencies; the Docker image is intentionally slim
