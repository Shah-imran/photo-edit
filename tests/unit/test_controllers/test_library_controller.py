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
