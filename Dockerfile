FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive

# 1. Install system dependencies
# - libgomp1: Multi-threading (OpenMP)
# - libfontconfig1, libx11-6, libharfbuzz0b, libfribidi0: 
#   Required by ImageMagick AppImage for font rendering and text support.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    libgomp1 \
    libfontconfig1 \
    libx11-6 \
    libharfbuzz0b \
    libfribidi0 \
  && rm -rf /var/lib/apt/lists/*

# 2. SURGICAL INSTALLATION: ImageMagick 7 (AppImage Extraction)
# Download -> Extract -> Symlink.
WORKDIR /opt/imagemagick-build
RUN curl -L -o magick https://imagemagick.org/archive/binaries/magick \
    && chmod +x magick \
    && ./magick --appimage-extract \
    && mv squashfs-root /opt/imagemagick \
    && ln -s /opt/imagemagick/AppRun /usr/local/bin/magick \
    && rm magick \
    && rm -rf /opt/imagemagick-build

# Verify installation and AVIF support immediately
RUN magick -version && magick -list format | grep -i "AVIF"

WORKDIR /opt/pixload-engine

COPY main.py /opt/pixload-engine/main.py
COPY requirements.txt /opt/pixload-engine/requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Cloud Run injects the PORT environment variable
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 2
