"""Unit tests for LibraryThumbnailCacheService."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from src.services.library_catalog_service import LibraryEntry
from src.services.library_thumbnail_cache_service import LibraryThumbnailCacheService


def _entry_for(path: Path) -> LibraryEntry:
    stat = path.stat()
    return LibraryEntry(
        path=str(path),
        filename=path.name,
        added_at="2026-05-07T00:00:00+00:00",
        last_seen_mtime_ns=int(stat.st_mtime_ns),
        last_seen_size=int(stat.st_size),
        status="available",
    )


class TestLibraryThumbnailCacheService:
    def test_cache_hit_from_stored_thumbnail(self, thumbnail_cache_dir, tmp_path):
        service = LibraryThumbnailCacheService(cache_dir=thumbnail_cache_dir)
        image_path = tmp_path / "photo.jpg"
        Image.new("RGB", (10, 10), color="blue").save(image_path)
        entry = _entry_for(image_path)
        cache_key = service.entry_cache_key(entry)
        assert cache_key is not None

        thumb = np.zeros((12, 12, 3), dtype=np.float32)
        service.write_thumbnail(cache_key, thumb)
        loaded = service.load_qimage(cache_key)

        assert loaded is not None
        assert loaded.width() == 12
        assert loaded.height() == 12

    def test_stale_cache_invalidates_when_source_metadata_changes(
        self,
        thumbnail_cache_dir,
        tmp_path,
    ):
        service = LibraryThumbnailCacheService(cache_dir=thumbnail_cache_dir)
        image_path = tmp_path / "photo.jpg"
        Image.new("RGB", (10, 10), color="blue").save(image_path)
        first = _entry_for(image_path)
        first_key = service.entry_cache_key(first)
        assert first_key is not None
        service.write_thumbnail(first_key, np.zeros((8, 8, 3), dtype=np.float32))

        Image.new("RGB", (20, 20), color="red").save(image_path)
        second = _entry_for(image_path)
        second_key = service.entry_cache_key(second)

        assert second_key is not None
        assert second_key != first_key
        assert service.load_qimage(second_key) is None

    def test_cache_miss_returns_none(self, thumbnail_cache_service, sample_image_path):
        path = Path(sample_image_path)
        entry = _entry_for(path)

        assert thumbnail_cache_service.has_valid_cache(entry) is False
        assert thumbnail_cache_service.load_qimage("does-not-exist") is None

    def test_missing_file_skip_behavior(self, thumbnail_cache_service, tmp_path):
        missing = tmp_path / "gone.jpg"
        entry = LibraryEntry(
            path=str(missing),
            filename=missing.name,
            added_at="2026-05-07T00:00:00+00:00",
            last_seen_mtime_ns=None,
            last_seen_size=None,
            status="missing",
        )

        assert thumbnail_cache_service.entry_cache_key(entry) is None
        assert thumbnail_cache_service.has_valid_cache(entry) is False
