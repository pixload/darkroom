FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive

# System dependencies for libvips with HEIF/AVIF support
RUN apt-get update && apt-get install -y --no-install-recommends \
    libvips42 \
    libheif1 \
    ca-certificates \
    curl \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/pixload-engine

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# Verify libvips is accessible from pyvips
RUN python -c "import pyvips; print(f'libvips {pyvips.version(0)}.{pyvips.version(1)}.{pyvips.version(2)}')"

# Cloud Run injects PORT; default to 8080
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 2
