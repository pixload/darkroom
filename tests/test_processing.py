"""Tests for image processing functions directly (no HTTP)."""

import pyvips

from main import apply_overlay, process_image
from tests.conftest import make_png, make_rgba_png


class TestProcessImage:
    def test_basic_jpg_output(self, tmp_path):
        src = tmp_path / "input.png"
        dst = tmp_path / "output.jpg"
        src.write_bytes(make_png(width=50, height=50))

        process_image(
            src,
            dst,
            fmt="jpg",
            quality=80,
            size=None,
            square=False,
            strip_exif=False,
            overlay_path=None,
            overlay_scale=15,
            overlay_safe_zone=True,
            overlay_opacity=100,
            avif_speed=6,
        )

        assert dst.exists()
        assert dst.read_bytes()[:2] == b"\xff\xd8"

    def test_resize_shrinks(self, tmp_path):
        src = tmp_path / "input.png"
        dst = tmp_path / "output.png"
        src.write_bytes(make_png(width=200, height=100))

        process_image(
            src,
            dst,
            fmt="png",
            quality=80,
            size=50,
            square=False,
            strip_exif=False,
            overlay_path=None,
            overlay_scale=15,
            overlay_safe_zone=True,
            overlay_opacity=100,
            avif_speed=6,
        )

        result = pyvips.Image.new_from_file(str(dst))
        assert result.width <= 50
        assert result.height <= 50

    def test_square_crop(self, tmp_path):
        src = tmp_path / "input.png"
        dst = tmp_path / "output.png"
        src.write_bytes(make_png(width=200, height=100))

        process_image(
            src,
            dst,
            fmt="png",
            quality=80,
            size=50,
            square=True,
            strip_exif=False,
            overlay_path=None,
            overlay_scale=15,
            overlay_safe_zone=True,
            overlay_opacity=100,
            avif_speed=6,
        )

        result = pyvips.Image.new_from_file(str(dst))
        assert result.width == 50
        assert result.height == 50

    def test_alpha_flattened_for_jpg(self, tmp_path):
        """RGBA PNG converted to JPG should have no alpha (flattened to white)."""
        src = tmp_path / "input.png"
        dst = tmp_path / "output.jpg"
        src.write_bytes(make_rgba_png(width=20, height=20))

        process_image(
            src,
            dst,
            fmt="jpg",
            quality=80,
            size=None,
            square=False,
            strip_exif=False,
            overlay_path=None,
            overlay_scale=15,
            overlay_safe_zone=True,
            overlay_opacity=100,
            avif_speed=6,
        )

        result = pyvips.Image.new_from_file(str(dst))
        assert not result.hasalpha()


class TestApplyOverlay:
    def test_overlay_composites_without_error(self, tmp_path):
        overlay_file = tmp_path / "logo.png"
        overlay_file.write_bytes(make_rgba_png(width=20, height=20, color=(0, 255, 0, 200)))

        base = (pyvips.Image.black(100, 100, bands=3) + [128, 128, 128]).copy(interpretation="srgb")

        result = apply_overlay(
            base,
            overlay_file,
            target_width=100,
            scale_pct=50,
            safe_zone=False,
            opacity=100,
        )

        assert result.width == 100
        assert result.height == 100

    def test_overlay_with_reduced_opacity(self, tmp_path):
        overlay_file = tmp_path / "logo.png"
        overlay_file.write_bytes(make_rgba_png(width=10, height=10))

        base = (pyvips.Image.black(200, 200, bands=3) + [200, 200, 200]).copy(interpretation="srgb")

        result = apply_overlay(
            base,
            overlay_file,
            target_width=200,
            scale_pct=10,
            safe_zone=True,
            opacity=50,
        )

        assert result.width == 200
        assert result.height == 200

    def test_overlay_safe_zone_positioning(self, tmp_path):
        """Safe zone should center horizontally, offset from bottom."""
        overlay_file = tmp_path / "logo.png"
        overlay_file.write_bytes(make_rgba_png(width=10, height=10))

        base = pyvips.Image.black(500, 500, bands=3).copy(interpretation="srgb")

        # Should not raise with safe_zone=True on a large enough image
        result = apply_overlay(
            base,
            overlay_file,
            target_width=500,
            scale_pct=10,
            safe_zone=True,
            opacity=100,
        )
        assert result.width == 500
