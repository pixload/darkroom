"""Tests for helper functions: hashing, cleanup, S3 key generation."""

from main import calculate_sha256, cleanup_temp_dir


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
