"""Tests for API endpoints — validation, auth, error handling."""

import pytest

from tests.conftest import AUTH_TOKEN, make_png

# --- /ping ---


@pytest.mark.anyio
async def test_ping(client):
    resp = await client.get("/ping")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "engine" in data
    assert "libvips" in data
    assert "formats" in data


# --- /convert: Auth ---


@pytest.mark.anyio
async def test_convert_missing_token(client):
    resp = await client.post("/convert", data={})
    assert resp.status_code == 422  # FastAPI validation (token is required)


@pytest.mark.anyio
async def test_convert_bad_token(client):
    resp = await client.post("/convert", data={"token": "wrong"})
    assert resp.status_code == 401


# --- /convert: Input validation ---


@pytest.mark.anyio
async def test_convert_no_input(client):
    resp = await client.post("/convert", data={"token": AUTH_TOKEN})
    assert resp.status_code == 400
    assert "file" in resp.json()["detail"].lower() or "src_url" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_convert_unsupported_format(client):
    png = make_png()
    resp = await client.post(
        "/convert",
        data={"token": AUTH_TOKEN, "format": "bmp"},
        files={"file": ("test.png", png, "image/png")},
    )
    assert resp.status_code == 400
    assert "format" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_convert_quality_out_of_range(client):
    png = make_png()
    resp = await client.post(
        "/convert",
        data={"token": AUTH_TOKEN, "q": "0"},
        files={"file": ("test.png", png, "image/png")},
    )
    assert resp.status_code == 400
    assert "quality" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_convert_avif_speed_out_of_range(client):
    png = make_png()
    resp = await client.post(
        "/convert",
        data={"token": AUTH_TOKEN, "format": "avif", "avif_speed": "15"},
        files={"file": ("test.png", png, "image/png")},
    )
    assert resp.status_code == 400
    assert "avif_speed" in resp.json()["detail"].lower()


# --- /convert: Successful processing ---


@pytest.mark.anyio
async def test_convert_png_to_jpg(client):
    png = make_png(width=10, height=10)
    resp = await client.post(
        "/convert",
        data={"token": AUTH_TOKEN, "format": "jpg", "return_binary": "true"},
        files={"file": ("test.png", png, "image/png")},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.content[:2] == b"\xff\xd8"


@pytest.mark.anyio
async def test_convert_with_resize(client):
    png = make_png(width=100, height=200)
    resp = await client.post(
        "/convert",
        data={
            "token": AUTH_TOKEN,
            "format": "png",
            "size": "50",
            "return_binary": "true",
        },
        files={"file": ("test.png", png, "image/png")},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"


@pytest.mark.anyio
async def test_convert_with_square_crop(client):
    png = make_png(width=100, height=200)
    resp = await client.post(
        "/convert",
        data={
            "token": AUTH_TOKEN,
            "format": "png",
            "size": "50",
            "square": "true",
            "return_binary": "true",
        },
        files={"file": ("test.png", png, "image/png")},
    )
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_convert_json_response_without_s3(client):
    """When return_binary=false and upload_s3=false, get a JSON response."""
    png = make_png(width=10, height=10)
    resp = await client.post(
        "/convert",
        data={"token": AUTH_TOKEN, "format": "jpg"},
        files={"file": ("test.png", png, "image/png")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["format"] == "jpg"


@pytest.mark.anyio
async def test_convert_to_webp(client):
    png = make_png(width=10, height=10)
    resp = await client.post(
        "/convert",
        data={"token": AUTH_TOKEN, "format": "webp", "return_binary": "true"},
        files={"file": ("test.png", png, "image/png")},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/webp"
    assert resp.content[:4] == b"RIFF"
    assert resp.content[8:12] == b"WEBP"


@pytest.mark.anyio
async def test_convert_strip_exif(client):
    png = make_png(width=10, height=10)
    resp = await client.post(
        "/convert",
        data={
            "token": AUTH_TOKEN,
            "format": "jpg",
            "strip_exif": "true",
            "return_binary": "true",
        },
        files={"file": ("test.png", png, "image/png")},
    )
    assert resp.status_code == 200
    assert resp.content[:2] == b"\xff\xd8"


@pytest.mark.anyio
async def test_convert_corrupted_file(client):
    """Sending garbage data should return 500, not crash."""
    resp = await client.post(
        "/convert",
        data={"token": AUTH_TOKEN, "format": "jpg", "return_binary": "true"},
        files={"file": ("bad.png", b"not an image at all", "image/png")},
    )
    assert resp.status_code == 500


@pytest.mark.anyio
async def test_convert_tiny_image(client):
    """1x1 pixel image should process without error."""
    png = make_png(width=1, height=1)
    resp = await client.post(
        "/convert",
        data={"token": AUTH_TOKEN, "format": "jpg", "return_binary": "true"},
        files={"file": ("tiny.png", png, "image/png")},
    )
    assert resp.status_code == 200
    assert resp.content[:2] == b"\xff\xd8"


@pytest.mark.anyio
async def test_convert_resize_smaller_than_target_is_noop(client):
    """Image smaller than target size should not be upscaled."""
    png = make_png(width=10, height=10)
    resp = await client.post(
        "/convert",
        data={
            "token": AUTH_TOKEN,
            "format": "png",
            "size": "1000",
            "return_binary": "true",
        },
        files={"file": ("small.png", png, "image/png")},
    )
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_convert_quality_boundaries(client):
    """Quality 1 and 100 should both work."""
    png = make_png(width=10, height=10)
    for q in (1, 100):
        resp = await client.post(
            "/convert",
            data={"token": AUTH_TOKEN, "format": "jpg", "q": str(q), "return_binary": "true"},
            files={"file": ("test.png", png, "image/png")},
        )
        assert resp.status_code == 200


@pytest.mark.anyio
async def test_convert_size_too_large(client):
    """Size exceeding 16384 should be rejected."""
    png = make_png(width=10, height=10)
    resp = await client.post(
        "/convert",
        data={"token": AUTH_TOKEN, "format": "jpg", "size": "20000"},
        files={"file": ("test.png", png, "image/png")},
    )
    assert resp.status_code == 400
    assert "size" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_convert_overlay_scale_out_of_range(client):
    """overlay_scale outside 1-100 should be rejected."""
    png = make_png(width=10, height=10)
    resp = await client.post(
        "/convert",
        data={"token": AUTH_TOKEN, "format": "jpg", "overlay_scale": "0"},
        files={"file": ("test.png", png, "image/png")},
    )
    assert resp.status_code == 400
    assert "overlay_scale" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_convert_overlay_opacity_out_of_range(client):
    """overlay_opacity outside 0-100 should be rejected."""
    png = make_png(width=10, height=10)
    resp = await client.post(
        "/convert",
        data={"token": AUTH_TOKEN, "format": "jpg", "overlay_opacity": "150"},
        files={"file": ("test.png", png, "image/png")},
    )
    assert resp.status_code == 400
    assert "overlay_opacity" in resp.json()["detail"].lower()
