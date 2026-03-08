import struct
import zlib

import pytest
from httpx import ASGITransport, AsyncClient

from main import app

AUTH_TOKEN = "changeme"


@pytest.fixture
def client():
    """Async HTTP client wired to the FastAPI app."""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    c = chunk_type + data
    return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)


def _build_png(width: int, height: int, color: tuple, color_type: int) -> bytes:
    header = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    ihdr = _png_chunk(b"IHDR", ihdr_data)

    raw_data = b""
    for _ in range(height):
        raw_data += b"\x00"
        for _ in range(width):
            raw_data += bytes(color)

    idat = _png_chunk(b"IDAT", zlib.compress(raw_data))
    iend = _png_chunk(b"IEND", b"")

    return header + ihdr + idat + iend


def make_png(width: int = 2, height: int = 2, color: tuple = (255, 0, 0)) -> bytes:
    """Generate a minimal valid RGB PNG in memory."""
    return _build_png(width, height, color, color_type=2)


def make_rgba_png(width: int = 2, height: int = 2, color: tuple = (255, 0, 0, 128)) -> bytes:
    """Generate a minimal valid RGBA PNG in memory (for overlay tests)."""
    return _build_png(width, height, color, color_type=6)
