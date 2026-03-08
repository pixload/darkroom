"""Tests for helper functions: hashing, cleanup, S3 upload."""

from unittest.mock import MagicMock, patch

from main import calculate_sha256, cleanup_temp_dir, upload_to_s3


class TestSha256:
    def test_consistent_hash(self, tmp_path):
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello world")
        h1 = calculate_sha256(f)
        h2 = calculate_sha256(f)
        assert h1 == h2

    def test_different_content_different_hash(self, tmp_path):
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(b"aaa")
        f2.write_bytes(b"bbb")
        assert calculate_sha256(f1) != calculate_sha256(f2)

    def test_known_hash(self, tmp_path):
        f = tmp_path / "known.bin"
        f.write_bytes(b"")
        # SHA256 of empty string
        assert calculate_sha256(f) == (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )


class TestCleanup:
    def test_cleanup_removes_dir(self, tmp_path):
        d = tmp_path / "workdir"
        d.mkdir()
        (d / "file.txt").write_text("data")
        cleanup_temp_dir(d)
        assert not d.exists()

    def test_cleanup_nonexistent_dir_no_error(self, tmp_path):
        d = tmp_path / "ghost"
        cleanup_temp_dir(d)  # should not raise


class TestUploadToS3:
    @patch("main.get_s3_client")
    def test_upload_returns_public_url(self, mock_get_client, tmp_path):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        f = tmp_path / "image.jpg"
        f.write_bytes(b"\xff\xd8fake")

        url = upload_to_s3(str(f), "photos/test.jpg", "image/jpeg")

        mock_client.upload_file.assert_called_once_with(
            str(f),
            "pixload",
            "photos/test.jpg",
            ExtraArgs={"ContentType": "image/jpeg"},
        )
        assert url == "https://cdn.pixload.events/photos/test.jpg"

    @patch("main.get_s3_client")
    def test_upload_strips_slashes_from_url(self, mock_get_client, tmp_path):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        f = tmp_path / "image.jpg"
        f.write_bytes(b"\xff\xd8fake")

        url = upload_to_s3(str(f), "/leading/slash.jpg", "image/jpeg")
        assert url == "https://cdn.pixload.events/leading/slash.jpg"

    @patch("main.get_s3_client")
    def test_upload_failure_returns_none(self, mock_get_client, tmp_path):
        mock_client = MagicMock()
        mock_client.upload_file.side_effect = Exception("connection refused")
        mock_get_client.return_value = mock_client

        f = tmp_path / "image.jpg"
        f.write_bytes(b"\xff\xd8fake")

        result = upload_to_s3(str(f), "test.jpg", "image/jpeg")
        assert result is None
