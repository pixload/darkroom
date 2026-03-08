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


def make_png(width: int = 2, height: int = 2, color: tuple = (255, 0, 0)) -> bytes:
    """Generate a minimal valid PNG in memory."""

    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    header = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr = chunk(b"IHDR", ihdr_data)

    raw_data = b""
    for _ in range(height):
        raw_data += b"\x00"  # filter byte
        for _ in range(width):
            raw_data += bytes(color)

    idat = chunk(b"IDAT", zlib.compress(raw_data))
    iend = chunk(b"IEND", b"")

    return header + ihdr + idat + iend
