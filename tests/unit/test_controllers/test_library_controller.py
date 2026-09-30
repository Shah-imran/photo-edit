"""Unit tests for LibraryController."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image
from PyQt6.QtWidgets import QApplication

from src.controllers.library_controller import LibraryController
from src.services.image_service import ImageService
from src.services.library_catalog_service import LibraryCatalogService
from src.services.library_thumbnail_cache_service import LibraryThumbnailCacheService


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def controller(library_catalog_path, thumbnail_cache_dir):
    ctl = LibraryController(
        catalog_service=LibraryCatalogService(catalog_path=library_catalog_path),
        thumbnail_cache_service=LibraryThumbnailCacheService(
            cache_dir=thumbnail_cache_dir
        ),
    )
    yield ctl
    ctl.cleanup()


class TestLibraryController:
    def test_initialize_emits_default_library(self, controller, qtbot):
        with qtbot.waitSignal(controller.libraries_changed, timeout=1000) as libs:
            with qtbot.waitSignal(controller.entries_rebuilt, timeout=1000) as entries:
                controller.initialize()

        libraries, current_id = libs.args
        rebuilt_library_id, entry_list = entries.args
        assert len(libraries) == 1
        assert current_id == rebuilt_library_id
        assert entry_list == []

    def test_create_and_select_library_flow(self, controller, qtbot):
        controller.initialize()
        with qtbot.waitSignal(controller.libraries_changed, timeout=1000) as created:
            controller.create_library("Travel")

        libraries, current_id = created.args
        assert [item["name"] for item in libraries] == ["Library 1", "Travel"]
        assert controller.get_library_name(current_id) == "Travel"

        first_id = libraries[0]["id"]
        with qtbot.waitSignal(controller.entries_rebuilt, timeout=1000) as rebuilt:
            controller.select_library(first_id)

        assert rebuilt.args[0] == first_id
        assert controller.current_library_id == first_id

    def test_import_images_updates_catalog_and_entries(
        self,
        controller,
        sample_image_path,
        qtbot,
    ):
        controller.initialize()

        with qtbot.waitSignal(controller.entries_rebuilt, timeout=3000) as rebuilt:
            controller.import_images([sample_image_path])

        _, entries = rebuilt.args
        assert len(entries) == 1
        assert entries[0]["path"] == sample_image_path

    def test_libraries_changed_includes_entry_counts(
        self, controller, sample_image_path, qtbot
    ):
        controller.initialize()
        controller.import_images([sample_image_path])

        with qtbot.waitSignal(controller.libraries_changed, timeout=1000) as changed:
            controller.create_library("Empty")

        libraries, _current_id = changed.args
        populated = next(item for item in libraries if item["name"] == "Library 1")
        assert populated["count"] == 1

    def test_remove_library_restores_remaining_library(
        self,
        controller,
        qtbot,
    ):
        controller.initialize()
        controller.create_library("Travel")
        current_id = controller.current_library_id

        with qtbot.waitSignal(controller.libraries_changed, timeout=1000) as libs:
            controller.remove_library(current_id)

        libraries, new_current_id = libs.args
        assert len(libraries) == 1
        assert libraries[0]["name"] == "Library 1"
        assert new_current_id == libraries[0]["id"]

    def test_cleanup_stops_thumbnail_worker(
        self,
        qapp,
        tmp_path,
        qtbot,
    ):
        image_path = tmp_path / "photo.jpg"
        Image.new("RGB", (50, 50), color="blue").save(image_path)

        ctl = LibraryController(
            catalog_service=LibraryCatalogService(catalog_path=tmp_path / "catalog.json"),
            thumbnail_cache_service=LibraryThumbnailCacheService(
                cache_dir=tmp_path / "cache"
            ),
        )
        ctl.initialize()

        real_thumb = ImageService.load_preview_thumbnail

        def slow_thumb(self, file_path, size):
            time.sleep(0.05)
            return real_thumb(self, file_path, size)

        with patch.object(ImageService, "load_preview_thumbnail", slow_thumb):
            ctl.import_images([str(image_path)])
            ctl.cleanup()

        thread = ctl._thumbnail_thread
        assert thread is None or thread.isRunning() is False


class TestLibraryRebuildResponsiveness:
    """Regression coverage for the "Not Responding" freeze fix -- see
    docs/planning/implementation-notes/2026-09-29-library-rebuild-responsiveness.md.

    A rebuild must never synchronously decode a cached thumbnail PNG or
    synchronously walk the thumbnail cache directory on the calling
    (UI) thread.
    """

    def test_cached_thumbnail_is_not_decoded_synchronously_during_rebuild(
        self, controller, sample_image_path, qtbot
    ):
        controller.initialize()

        # First import: generates and caches the thumbnail via the
        # background worker.
        with qtbot.waitSignal(controller.entries_rebuilt, timeout=3000):
            controller.import_images([sample_image_path])
        qtbot.waitUntil(lambda: controller._thumbnail_thread is None, timeout=3000)

        # Second rebuild: the thumbnail is now already cached on disk.
        # entries_rebuilt must fire with a "loading" placeholder -- not an
        # already-decoded image -- because decoding it here (in the
        # rebuild loop) is exactly the synchronous work that froze the UI.
        with qtbot.waitSignal(controller.entries_rebuilt, timeout=3000) as rebuilt:
            controller._rebuild_entries_for_current_library()

        _, payloads = rebuilt.args
        assert len(payloads) == 1
        assert payloads[0]["thumbnail"] is None
        assert payloads[0]["placeholder"] == "loading"

    def test_cached_thumbnail_is_delivered_without_regenerating(
        self, controller, sample_image_path, qtbot
    ):
        controller.initialize()
        with qtbot.waitSignal(controller.entries_rebuilt, timeout=3000):
            controller.import_images([sample_image_path])
        qtbot.waitUntil(lambda: controller._thumbnail_thread is None, timeout=3000)

        generate_calls = []
        real_load = ImageService.load_preview_thumbnail

        def spy_load(self, file_path, size):
            generate_calls.append(file_path)
            return real_load(self, file_path, size)

        updates = []
        controller.entry_thumbnail_updated.connect(
            lambda path, payload: updates.append((path, payload))
        )

        with patch.object(ImageService, "load_preview_thumbnail", spy_load):
            controller._rebuild_entries_for_current_library()
            qtbot.waitUntil(lambda: len(updates) == 1, timeout=3000)

        path, payload = updates[0]
        assert path == sample_image_path
        assert payload["thumbnail"] is not None
        assert payload["placeholder"] is None
        # The cached PNG must be reused, never regenerated from the
        # source image.
        assert generate_calls == []

    def test_orphan_cache_cleanup_does_not_block_the_calling_thread(
        self, controller, sample_image_path, qtbot
    ):
        controller.initialize()

        real_remove = LibraryThumbnailCacheService.remove_orphaned_cache

        def slow_remove(self, valid_keys):
            time.sleep(0.5)
            return real_remove(self, valid_keys)

        with patch.object(
            LibraryThumbnailCacheService, "remove_orphaned_cache", slow_remove
        ):
            start = time.perf_counter()
            controller.import_images([sample_image_path])
            elapsed = time.perf_counter() - start

        # import_images() must return promptly even though the (patched,
        # deliberately slow) cleanup call takes 500ms -- proving it runs on
        # a background thread rather than synchronously inline on the
        # calling thread.
        assert elapsed < 0.3

    def test_cleanup_waits_for_orphan_cleanup_thread(
        self, qapp, tmp_path, qtbot
    ):
        ctl = LibraryController(
            catalog_service=LibraryCatalogService(catalog_path=tmp_path / "catalog.json"),
            thumbnail_cache_service=LibraryThumbnailCacheService(
                cache_dir=tmp_path / "cache"
            ),
        )
        ctl.initialize()
        ctl._cleanup_orphaned_cache_async(set())
        thread = ctl._orphan_cleanup_threads[-1]

        ctl.cleanup()

        assert thread.isRunning() is False

    def test_rebuild_with_many_cached_entries_returns_quickly(
        self, controller, tmp_path, qtbot
    ):
        """Bounds the fix at scale, not just the single-entry mechanism.

        Before this fix, rebuilding with N already-cached thumbnails
        synchronously decoded N PNGs and walked the whole cache directory
        on the calling thread -- exactly what produced the "Not
        Responding" warning for a real-sized library.
        """
        controller.initialize()

        count = 200
        paths = []
        for i in range(count):
            path = tmp_path / f"photo_{i:03d}.jpg"
            Image.new("RGB", (20, 20), color=(i % 255, 0, 0)).save(path)
            paths.append(str(path))

        with qtbot.waitSignal(controller.entries_rebuilt, timeout=10000):
            controller.import_images(paths)
        qtbot.waitUntil(lambda: controller._thumbnail_thread is None, timeout=15000)

        # All thumbnails are now cached on disk. A fresh rebuild must not
        # decode them synchronously.
        start = time.perf_counter()
        with qtbot.waitSignal(controller.entries_rebuilt, timeout=10000) as rebuilt:
            controller._rebuild_entries_for_current_library()
        elapsed = time.perf_counter() - start

        _, payloads = rebuilt.args
        assert len(payloads) == count
        assert elapsed < 1.0
