"""Tests for security: SSRF protection, upload size limits, URL validation."""

import socket
from unittest.mock import patch

import pytest

from main import validate_url
from tests.conftest import AUTH_TOKEN, make_png

# Fake DNS result for example.com (93.184.216.34 — public IP)
_PUBLIC_ADDRINFO = [(2, 1, 6, "", ("93.184.216.34", 0))]


def _mock_resolve_public(hostname, *args, **kwargs):
    """Return a public IP for any hostname (used when DNS is unavailable in CI)."""
    return _PUBLIC_ADDRINFO


def _mock_resolve_loopback(hostname, *args, **kwargs):
    return [(2, 1, 6, "", ("127.0.0.1", 0))]


def _mock_resolve_private(hostname, *args, **kwargs):
    return [(2, 1, 6, "", ("10.0.0.1", 0))]


def _mock_resolve_fail(hostname, *args, **kwargs):
    raise socket.gaierror("Fake DNS failure")


# --- SSRF Protection ---


class TestValidateUrl:
    @patch("main.socket.getaddrinfo", side_effect=_mock_resolve_public)
    def test_valid_https_url(self, _mock):
        validate_url("https://example.com/image.png")

    @patch("main.socket.getaddrinfo", side_effect=_mock_resolve_public)
    def test_valid_http_url(self, _mock):
        validate_url("http://example.com/image.png")

    def test_reject_ftp_scheme(self):
        with pytest.raises(ValueError, match="HTTP/HTTPS"):
            validate_url("ftp://example.com/file")

    def test_reject_file_scheme(self):
        with pytest.raises(ValueError, match="HTTP/HTTPS"):
            validate_url("file:///etc/passwd")

    def test_reject_no_scheme(self):
        with pytest.raises(ValueError, match="HTTP/HTTPS"):
            validate_url("example.com/image.png")

    @patch("main.socket.getaddrinfo", side_effect=_mock_resolve_loopback)
    def test_reject_localhost(self, _mock):
        with pytest.raises(ValueError, match="internal"):
            validate_url("http://127.0.0.1/secret")

    @patch("main.socket.getaddrinfo", side_effect=_mock_resolve_loopback)
    def test_reject_localhost_name(self, _mock):
        with pytest.raises(ValueError, match="internal"):
            validate_url("http://localhost/secret")

    @patch("main.socket.getaddrinfo", side_effect=_mock_resolve_private)
    def test_reject_private_10(self, _mock):
        with pytest.raises(ValueError, match="internal"):
            validate_url("http://10.0.0.1/secret")

    @patch(
        "main.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("172.16.0.1", 0))],
    )
    def test_reject_private_172(self, _mock):
        with pytest.raises(ValueError, match="internal"):
            validate_url("http://172.16.0.1/secret")

    @patch(
        "main.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("192.168.1.1", 0))],
    )
    def test_reject_private_192(self, _mock):
        with pytest.raises(ValueError, match="internal"):
            validate_url("http://192.168.1.1/secret")

    @patch(
        "main.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("169.254.169.254", 0))],
    )
    def test_reject_link_local(self, _mock):
        with pytest.raises(ValueError, match="internal"):
            validate_url("http://169.254.169.254/latest/meta-data/")

    @patch(
        "main.socket.getaddrinfo",
        return_value=[(10, 1, 6, "", ("::1", 0, 0, 0))],
    )
    def test_reject_ipv6_loopback(self, _mock):
        with pytest.raises(ValueError, match="internal"):
            validate_url("http://[::1]/secret")

    def test_reject_missing_hostname(self):
        with pytest.raises(ValueError, match="hostname"):
            validate_url("http://")

    @patch("main.socket.getaddrinfo", side_effect=_mock_resolve_fail)
    def test_reject_unresolvable(self, _mock):
        with pytest.raises(ValueError, match="resolve"):
            validate_url("http://this-domain-does-not-exist.invalid/img.png")


# --- Upload Size Limits ---


@pytest.mark.anyio
async def test_upload_size_limit(client, monkeypatch):
    """Uploading a file larger than MAX_UPLOAD_BYTES should return 413."""
    monkeypatch.setattr("main.MAX_UPLOAD_BYTES", 100)

    big_png = make_png(width=50, height=50)
    assert len(big_png) > 100

    resp = await client.post(
        "/convert",
        data={"token": AUTH_TOKEN, "format": "png", "return_binary": "true"},
        files={"file": ("big.png", big_png, "image/png")},
    )
    assert resp.status_code == 413


@pytest.mark.anyio
async def test_src_url_ssrf_blocked(client):
    """src_url pointing to localhost should be rejected."""
    resp = await client.post(
        "/convert",
        data={
            "token": AUTH_TOKEN,
            "src_url": "http://127.0.0.1:8080/internal",
        },
    )
    assert resp.status_code == 400
    assert "internal" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_src_url_metadata_endpoint_blocked(client):
    """Cloud metadata endpoint should be blocked."""
    resp = await client.post(
        "/convert",
        data={
            "token": AUTH_TOKEN,
            "src_url": "http://169.254.169.254/latest/meta-data/",
        },
    )
    assert resp.status_code == 400
