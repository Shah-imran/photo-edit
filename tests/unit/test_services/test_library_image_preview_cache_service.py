"""Unit tests for LibraryImagePreviewCacheService.build_cache_key.

Focused on the fix that lets a "tone_curve" list value coexist with the
float-only adjustment values the signature builder previously assumed --
see docs/planning/implementation-notes/2026-09-29-tone-curve.md section 3.
"""

from src.services.library_image_preview_cache_service import (
    LibraryImagePreviewCacheService,
)


def _service(tmp_path):
    return LibraryImagePreviewCacheService(cache_dir=tmp_path / "cache")


class TestBuildCacheKey:
    def test_float_only_values_still_work(self, tmp_path):
        service = _service(tmp_path)
        key = service.build_cache_key(
            "/tmp/image.jpg", 123, 456, {"exposure": 1.0, "contrast": 10.0}
        )
        assert key is not None

    def test_tone_curve_list_value_does_not_raise(self, tmp_path):
        service = _service(tmp_path)
        key = service.build_cache_key(
            "/tmp/image.jpg",
            123,
            456,
            {
                "exposure": 1.0,
                "tone_curve": [[0.0, 0.0], [0.5, 0.7], [1.0, 1.0]],
            },
        )
        assert key is not None

    def test_missing_mtime_or_size_returns_none(self, tmp_path):
        service = _service(tmp_path)
        assert service.build_cache_key("/tmp/image.jpg", None, 456, {}) is None
        assert service.build_cache_key("/tmp/image.jpg", 123, None, {}) is None

    def test_different_curve_values_produce_different_keys(self, tmp_path):
        service = _service(tmp_path)
        key_a = service.build_cache_key(
            "/tmp/image.jpg", 123, 456, {"tone_curve": [[0.0, 0.0], [1.0, 1.0]]}
        )
        key_b = service.build_cache_key(
            "/tmp/image.jpg",
            123,
            456,
            {"tone_curve": [[0.0, 0.0], [0.5, 0.7], [1.0, 1.0]]},
        )
        assert key_a != key_b

    def test_pre_existing_float_only_signature_is_unchanged(self, tmp_path):
        """Byte-identical to the pre-fix formatting for plain floats, so
        existing on-disk preview caches are not invalidated by this
        change alone."""
        service = _service(tmp_path)
        adjustment_values = {"exposure": 1.0, "saturation": 20.0}
        expected_signature = ",".join(
            f"{key}={float(adjustment_values[key]):.4f}"
            for key in sorted(adjustment_values.keys())
        )
        import hashlib

        from src.services.library_image_preview_cache_service import _normalize_path

        key = service.build_cache_key("/tmp/image.jpg", 123, 456, adjustment_values)
        digest = hashlib.sha1(
            f"{_normalize_path('/tmp/image.jpg')}|123|456|{expected_signature}".encode(
                "utf-8"
            )
        ).hexdigest()
        assert key == digest
