"""Unit tests for LibraryCatalogService."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from src.services.library_catalog_service import LibraryCatalogService


def _make_image(path: Path, color: str = "blue") -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), color=color).save(path)
    return str(path)


class TestLibraryCatalogService:
    def test_first_run_creates_default_library(self, library_catalog_path):
        service = LibraryCatalogService(catalog_path=library_catalog_path)

        libraries = service.list_libraries()
        assert len(libraries) == 1
        assert libraries[0].name == "Library 1"
        assert service.get_current_library_id() == libraries[0].id
        assert library_catalog_path.exists()

    def test_persist_and_reload_multiple_libraries(self, library_catalog_path):
        first = LibraryCatalogService(catalog_path=library_catalog_path)
        original = first.list_libraries()[0]
        second = first.create_library("Travel")
        first.set_current_library(second.id)

        reloaded = LibraryCatalogService(catalog_path=library_catalog_path)
        libraries = reloaded.list_libraries()

        assert [lib.name for lib in libraries] == [original.name, "Travel"]
        assert reloaded.get_current_library_id() == second.id

    def test_duplicate_import_is_noop_within_one_library(
        self,
        library_catalog_service,
        sample_image_path,
    ):
        library_id = library_catalog_service.get_current_library_id()

        library_catalog_service.add_entries(library_id, [sample_image_path])
        library_catalog_service.add_entries(library_id, [sample_image_path])

        entries = library_catalog_service.list_entries(library_id)
        assert len(entries) == 1

    def test_same_file_can_exist_in_multiple_libraries(
        self,
        library_catalog_service,
        sample_image_path,
    ):
        first_id = library_catalog_service.get_current_library_id()
        second = library_catalog_service.create_library("Other")

        library_catalog_service.add_entries(first_id, [sample_image_path])
        library_catalog_service.add_entries(second.id, [sample_image_path])

        assert len(library_catalog_service.list_entries(first_id)) == 1
        assert len(library_catalog_service.list_entries(second.id)) == 1

    def test_remove_library_does_not_delete_original_file(
        self,
        library_catalog_service,
        sample_image_path,
    ):
        first_id = library_catalog_service.get_current_library_id()
        removable = library_catalog_service.create_library("Delete Me")
        library_catalog_service.add_entries(removable.id, [sample_image_path])

        removed = library_catalog_service.remove_library(removable.id)

        assert removed is not None
        assert Path(sample_image_path).exists()
        assert library_catalog_service.get_current_library_id() == first_id

    def test_missing_file_status_survives_reload(self, library_catalog_path, tmp_path):
        image_path = Path(_make_image(tmp_path / "missing_soon.jpg"))
        first = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = first.get_current_library_id()
        first.add_entries(library_id, [str(image_path)])
        image_path.unlink()
        first.refresh_entry_status(library_id, str(image_path))

        reloaded = LibraryCatalogService(catalog_path=library_catalog_path)
        entry = reloaded.list_entries(library_id)[0]

        assert entry.status == "missing"
        assert entry.path == str(image_path)

    def test_catalog_json_contains_schema_version(self, library_catalog_path):
        LibraryCatalogService(catalog_path=library_catalog_path)
        payload = json.loads(library_catalog_path.read_text(encoding="utf-8"))

        assert payload["schema_version"] == 1
        assert "libraries" in payload

    def test_entry_adjustment_state_survives_reload(
        self,
        library_catalog_path,
        sample_image_path,
    ):
        first = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = first.get_current_library_id()
        first.add_entries(library_id, [sample_image_path])
        first.set_entry_adjustment_state(
            library_id,
            sample_image_path,
            {
                "version": 1,
                "values": {
                    "exposure": 1.0,
                    "contrast": 20.0,
                    "brightness": 0.0,
                    "saturation": 15.0,
                    "vibrance": 5.0,
                },
            },
        )

        reloaded = LibraryCatalogService(catalog_path=library_catalog_path)
        payload = reloaded.get_entry_adjustment_state(library_id, sample_image_path)

        assert payload is not None
        assert payload["version"] == 1
        assert payload["values"]["contrast"] == 20.0
