FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive

# libvips + codec plugins for AVIF/HEIC encode and decode
RUN apt-get update && apt-get install -y --no-install-recommends \
    libvips42 \
    libheif1 \
    libheif-plugin-aomdec \
    libheif-plugin-aomenc \
    libheif-plugin-libde265 \
    libheif-plugin-x265 \
    ca-certificates \
    curl \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/pixload-engine

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# Verify libvips and AVIF support
RUN python -c "\
import pyvips; \
v = f'{pyvips.version(0)}.{pyvips.version(1)}.{pyvips.version(2)}'; \
fmts = [s.lstrip('.') for s in pyvips.get_suffixes()]; \
assert 'avif' in fmts, 'AVIF not supported'; \
assert 'heic' in fmts, 'HEIC not supported'; \
print(f'libvips {v} — AVIF + HEIC OK')"

# Cloud Run injects PORT; default to 8080
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 2
