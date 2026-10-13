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

    def test_favorite_state_survives_reload(
        self, library_catalog_path, sample_image_path
    ):
        first = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = first.get_current_library_id()
        first.add_entries(library_id, [sample_image_path])
        first.set_entry_favorite(library_id, sample_image_path, True)

        reloaded = LibraryCatalogService(catalog_path=library_catalog_path)
        assert reloaded.get_entry(library_id, sample_image_path).favorite is True

    def test_rating_state_survives_reload(
        self, library_catalog_path, sample_image_path
    ):
        first = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = first.get_current_library_id()
        first.add_entries(library_id, [sample_image_path])
        first.set_entry_rating(library_id, sample_image_path, 4)

        reloaded = LibraryCatalogService(catalog_path=library_catalog_path)
        assert reloaded.get_entry(library_id, sample_image_path).rating == 4

    def test_rating_defaults_to_zero_for_new_entries(
        self, library_catalog_path, sample_image_path
    ):
        service = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = service.get_current_library_id()
        service.add_entries(library_id, [sample_image_path])

        assert service.get_entry(library_id, sample_image_path).rating == 0

    def test_set_entry_rating_is_a_no_op_when_unchanged(
        self, library_catalog_path, sample_image_path
    ):
        service = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = service.get_current_library_id()
        service.add_entries(library_id, [sample_image_path])
        service.set_entry_rating(library_id, sample_image_path, 3)
        library = service.list_libraries()[0]
        updated_at_after_first_set = library.updated_at

        service.set_entry_rating(library_id, sample_image_path, 3)

        assert library.updated_at == updated_at_after_first_set

    def test_set_entry_rating_clamps_out_of_range_values(
        self, library_catalog_path, sample_image_path
    ):
        service = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = service.get_current_library_id()
        service.add_entries(library_id, [sample_image_path])

        service.set_entry_rating(library_id, sample_image_path, -3)
        assert service.get_entry(library_id, sample_image_path).rating == 0

        service.set_entry_rating(library_id, sample_image_path, 99)
        assert service.get_entry(library_id, sample_image_path).rating == 5

    def test_rating_missing_from_old_catalog_payload_defaults_to_zero(self):
        """Catalog files written before this slice lack the "rating" key
        entirely; reading them must default cleanly to 0 rather than error."""
        from src.services.library_catalog_service import LibraryEntry

        entry = LibraryEntry.from_dict(
            {
                "path": "/photos/old.jpg",
                "filename": "old.jpg",
                "added_at": "2024-01-01T00:00:00+00:00",
                "last_seen_mtime_ns": None,
                "last_seen_size": None,
                "status": "available",
                # No "favorite" or "rating" key at all -- pre-dates both.
            }
        )

        assert entry.favorite is False
        assert entry.rating == 0

    def test_rating_from_corrupt_payload_clamps_to_zero(self):
        from src.services.library_catalog_service import LibraryEntry

        entry = LibraryEntry.from_dict(
            {
                "path": "/photos/old.jpg",
                "filename": "old.jpg",
                "added_at": "2024-01-01T00:00:00+00:00",
                "last_seen_mtime_ns": None,
                "last_seen_size": None,
                "status": "available",
                "rating": "not-a-number",
            }
        )

        assert entry.rating == 0

    def test_flag_state_survives_reload(
        self, library_catalog_path, sample_image_path
    ):
        first = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = first.get_current_library_id()
        first.add_entries(library_id, [sample_image_path])
        first.set_entry_flag(library_id, sample_image_path, "pick")

        reloaded = LibraryCatalogService(catalog_path=library_catalog_path)
        assert reloaded.get_entry(library_id, sample_image_path).flag == "pick"

    def test_flag_defaults_to_none_for_new_entries(
        self, library_catalog_path, sample_image_path
    ):
        service = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = service.get_current_library_id()
        service.add_entries(library_id, [sample_image_path])

        assert service.get_entry(library_id, sample_image_path).flag == "none"

    def test_set_entry_flag_is_a_no_op_when_unchanged(
        self, library_catalog_path, sample_image_path
    ):
        service = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = service.get_current_library_id()
        service.add_entries(library_id, [sample_image_path])
        service.set_entry_flag(library_id, sample_image_path, "reject")
        library = service.list_libraries()[0]
        updated_at_after_first_set = library.updated_at

        service.set_entry_flag(library_id, sample_image_path, "reject")

        assert library.updated_at == updated_at_after_first_set

    def test_set_entry_flag_normalizes_garbage_values_to_none(
        self, library_catalog_path, sample_image_path
    ):
        service = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = service.get_current_library_id()
        service.add_entries(library_id, [sample_image_path])
        service.set_entry_flag(library_id, sample_image_path, "pick")

        service.set_entry_flag(library_id, sample_image_path, "not-a-real-flag")
        assert service.get_entry(library_id, sample_image_path).flag == "none"

        service.set_entry_flag(library_id, sample_image_path, "pick")
        service.set_entry_flag(library_id, sample_image_path, None)
        assert service.get_entry(library_id, sample_image_path).flag == "none"

    def test_flag_missing_from_old_catalog_payload_defaults_to_none(self):
        """Catalog files written before this slice lack the "flag" key
        entirely; reading them must default cleanly to "none" rather than error."""
        from src.services.library_catalog_service import LibraryEntry

        entry = LibraryEntry.from_dict(
            {
                "path": "/photos/old.jpg",
                "filename": "old.jpg",
                "added_at": "2024-01-01T00:00:00+00:00",
                "last_seen_mtime_ns": None,
                "last_seen_size": None,
                "status": "available",
                # No "favorite", "rating" or "flag" key at all -- pre-dates all three.
            }
        )

        assert entry.favorite is False
        assert entry.rating == 0
        assert entry.flag == "none"

    def test_flag_from_corrupt_payload_normalizes_to_none(self):
        from src.services.library_catalog_service import LibraryEntry

        entry = LibraryEntry.from_dict(
            {
                "path": "/photos/old.jpg",
                "filename": "old.jpg",
                "added_at": "2024-01-01T00:00:00+00:00",
                "last_seen_mtime_ns": None,
                "last_seen_size": None,
                "status": "available",
                "flag": "corrupt-garbage-value",
            }
        )

        assert entry.flag == "none"

    # -- captured_at ----------------------------------------------------
    # See docs/planning/implementation-notes/2026-10-13-edit-date-time.md.

    def test_captured_at_defaults_to_added_at_for_new_entries(
        self, library_catalog_path, sample_image_path
    ):
        service = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = service.get_current_library_id()
        service.add_entries(library_id, [sample_image_path])

        entry = service.get_entry(library_id, sample_image_path)
        assert entry.captured_at == entry.added_at

    def test_captured_at_state_survives_reload(
        self, library_catalog_path, sample_image_path
    ):
        first = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = first.get_current_library_id()
        first.add_entries(library_id, [sample_image_path])
        first.set_entry_captured_at(
            library_id, sample_image_path, "2020-05-17T10:30:00"
        )

        reloaded = LibraryCatalogService(catalog_path=library_catalog_path)
        assert (
            reloaded.get_entry(library_id, sample_image_path).captured_at
            == "2020-05-17T10:30:00"
        )

    def test_set_entry_captured_at_is_a_no_op_when_unchanged(
        self, library_catalog_path, sample_image_path
    ):
        service = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = service.get_current_library_id()
        service.add_entries(library_id, [sample_image_path])
        service.set_entry_captured_at(library_id, sample_image_path, "2020-05-17T10:30:00")
        library = service.list_libraries()[0]
        updated_at_after_first_set = library.updated_at

        service.set_entry_captured_at(library_id, sample_image_path, "2020-05-17T10:30:00")

        assert library.updated_at == updated_at_after_first_set

    def test_set_entry_captured_at_falls_back_on_malformed_input(
        self, library_catalog_path, sample_image_path
    ):
        service = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = service.get_current_library_id()
        service.add_entries(library_id, [sample_image_path])
        service.set_entry_captured_at(library_id, sample_image_path, "2020-05-17T10:30:00")

        result = service.set_entry_captured_at(
            library_id, sample_image_path, "not-a-real-timestamp"
        )

        assert result.captured_at == "2020-05-17T10:30:00"
        assert (
            service.get_entry(library_id, sample_image_path).captured_at
            == "2020-05-17T10:30:00"
        )

    def test_set_entry_captured_at_returns_none_for_unknown_library_or_path(
        self, library_catalog_path, sample_image_path
    ):
        service = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = service.get_current_library_id()
        service.add_entries(library_id, [sample_image_path])

        assert service.set_entry_captured_at("not-a-library", sample_image_path, "x") is None
        assert service.set_entry_captured_at(library_id, "/no/such/path.jpg", "x") is None

    def test_captured_at_missing_from_old_catalog_payload_defaults_to_added_at(self):
        """Catalog files written before this slice lack the "captured_at"
        key entirely; reading them must default cleanly to added_at
        rather than error."""
        from src.services.library_catalog_service import LibraryEntry

        entry = LibraryEntry.from_dict(
            {
                "path": "/photos/old.jpg",
                "filename": "old.jpg",
                "added_at": "2024-01-01T00:00:00+00:00",
                "last_seen_mtime_ns": None,
                "last_seen_size": None,
                "status": "available",
                # No "captured_at" key at all -- pre-dates this slice.
            }
        )

        assert entry.captured_at == "2024-01-01T00:00:00+00:00"

    def test_captured_at_from_corrupt_payload_falls_back_to_added_at(self):
        from src.services.library_catalog_service import LibraryEntry

        entry = LibraryEntry.from_dict(
            {
                "path": "/photos/old.jpg",
                "filename": "old.jpg",
                "added_at": "2024-01-01T00:00:00+00:00",
                "last_seen_mtime_ns": None,
                "last_seen_size": None,
                "status": "available",
                "captured_at": "definitely-not-a-timestamp",
            }
        )

        assert entry.captured_at == "2024-01-01T00:00:00+00:00"

    def test_keywords_state_survives_reload(
        self, library_catalog_path, sample_image_path
    ):
        first = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = first.get_current_library_id()
        first.add_entries(library_id, [sample_image_path])
        first.set_entry_keywords(library_id, sample_image_path, ["Sunset", "beach"])

        reloaded = LibraryCatalogService(catalog_path=library_catalog_path)
        assert reloaded.get_entry(library_id, sample_image_path).keywords == [
            "Sunset",
            "beach",
        ]

    def test_keywords_default_to_empty_list_for_new_entries(
        self, library_catalog_path, sample_image_path
    ):
        service = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = service.get_current_library_id()
        service.add_entries(library_id, [sample_image_path])

        assert service.get_entry(library_id, sample_image_path).keywords == []

    def test_set_entry_keywords_is_a_no_op_when_unchanged(
        self, library_catalog_path, sample_image_path
    ):
        service = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = service.get_current_library_id()
        service.add_entries(library_id, [sample_image_path])
        service.set_entry_keywords(library_id, sample_image_path, ["sunset"])
        library = service.list_libraries()[0]
        updated_at_after_first_set = library.updated_at

        service.set_entry_keywords(library_id, sample_image_path, ["sunset"])

        assert library.updated_at == updated_at_after_first_set

    def test_set_entry_keywords_normalizes_on_write(
        self, library_catalog_path, sample_image_path
    ):
        service = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = service.get_current_library_id()
        service.add_entries(library_id, [sample_image_path])

        service.set_entry_keywords(
            library_id, sample_image_path, ["Sunset", " sunset ", "", "  ", "Beach"]
        )

        assert service.get_entry(library_id, sample_image_path).keywords == [
            "Sunset",
            "Beach",
        ]

    def test_keywords_missing_from_old_catalog_payload_defaults_to_empty_list(self):
        """Catalog files written before this slice lack the "keywords" key
        entirely; reading them must default cleanly to [] rather than error."""
        from src.services.library_catalog_service import LibraryEntry

        entry = LibraryEntry.from_dict(
            {
                "path": "/photos/old.jpg",
                "filename": "old.jpg",
                "added_at": "2024-01-01T00:00:00+00:00",
                "last_seen_mtime_ns": None,
                "last_seen_size": None,
                "status": "available",
                # No "favorite", "rating", "flag" or "keywords" key at all.
            }
        )

        assert entry.favorite is False
        assert entry.rating == 0
        assert entry.flag == "none"
        assert entry.keywords == []

    def test_fresh_library_entries_do_not_share_a_mutable_keywords_list(self):
        """Regression test for the classic Python mutable-default-argument
        footgun: ``keywords: list[str] = []`` as a plain default would share
        ONE list object across every LibraryEntry instance. Confirm
        ``field(default_factory=list)`` gives each instance its own list."""
        from src.services.library_catalog_service import LibraryEntry

        first = LibraryEntry(
            path="/photos/a.jpg",
            filename="a.jpg",
            added_at="2024-01-01T00:00:00+00:00",
            last_seen_mtime_ns=None,
            last_seen_size=None,
            status="available",
        )
        second = LibraryEntry(
            path="/photos/b.jpg",
            filename="b.jpg",
            added_at="2024-01-01T00:00:00+00:00",
            last_seen_mtime_ns=None,
            last_seen_size=None,
            status="available",
        )

        first.keywords.append("sunset")

        assert first.keywords == ["sunset"]
        assert second.keywords == []

    def test_normalize_keywords_rejects_non_list_input(self):
        from src.services.library_catalog_service import _normalize_keywords

        assert _normalize_keywords(None) == []
        assert _normalize_keywords("sunset") == []
        assert _normalize_keywords(42) == []
        assert _normalize_keywords({"sunset": True}) == []

    def test_normalize_keywords_dedupes_case_insensitively_preserving_first_casing(
        self,
    ):
        from src.services.library_catalog_service import _normalize_keywords

        assert _normalize_keywords(["Sunset", "sunset", "SUNSET", "Beach"]) == [
            "Sunset",
            "Beach",
        ]

    def test_normalize_keywords_drops_whitespace_only_and_empty_entries(self):
        from src.services.library_catalog_service import _normalize_keywords

        assert _normalize_keywords(["sunset", "", "   ", "beach"]) == [
            "sunset",
            "beach",
        ]

    def test_normalize_keywords_preserves_insertion_order(self):
        from src.services.library_catalog_service import _normalize_keywords

        assert _normalize_keywords(["zebra", "alpha", "mango"]) == [
            "zebra",
            "alpha",
            "mango",
        ]

    # -- Collections ---------------------------------------------------
    # See docs/planning/implementation-notes/2026-10-13-collections.md.

    def test_create_collection_returns_record_and_appears_in_list(
        self, library_catalog_path
    ):
        service = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = service.get_current_library_id()

        record = service.create_collection(library_id, "Travel")

        assert record is not None
        assert record.name == "Travel"
        assert [c.id for c in service.list_collections(library_id)] == [record.id]

    def test_create_collection_rejects_empty_or_whitespace_name(
        self, library_catalog_path
    ):
        service = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = service.get_current_library_id()

        assert service.create_collection(library_id, "") is None
        assert service.create_collection(library_id, "   ") is None
        assert service.list_collections(library_id) == []

    def test_create_collection_unknown_library_returns_none(self, library_catalog_path):
        service = LibraryCatalogService(catalog_path=library_catalog_path)

        assert service.create_collection("no-such-library", "Travel") is None

    def test_create_collection_allows_duplicate_names(self, library_catalog_path):
        service = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = service.get_current_library_id()

        first = service.create_collection(library_id, "Travel")
        second = service.create_collection(library_id, "Travel")

        assert first.id != second.id
        assert len(service.list_collections(library_id)) == 2

    def test_rename_collection_updates_name(self, library_catalog_path):
        service = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = service.get_current_library_id()
        record = service.create_collection(library_id, "Travel")

        renamed = service.rename_collection(library_id, record.id, "Vacation")

        assert renamed.name == "Vacation"
        assert service.list_collections(library_id)[0].name == "Vacation"

    def test_rename_collection_unknown_id_is_a_no_op(self, library_catalog_path):
        service = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = service.get_current_library_id()

        assert service.rename_collection(library_id, "no-such-id", "New Name") is None

    def test_rename_collection_rejects_empty_name(self, library_catalog_path):
        service = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = service.get_current_library_id()
        record = service.create_collection(library_id, "Travel")

        result = service.rename_collection(library_id, record.id, "   ")

        assert result.name == "Travel"

    def test_list_collections_unknown_library_returns_empty_list(
        self, library_catalog_path
    ):
        service = LibraryCatalogService(catalog_path=library_catalog_path)

        assert service.list_collections("no-such-library") == []

    def test_add_entry_to_collection_sets_membership(
        self, library_catalog_path, sample_image_path
    ):
        service = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = service.get_current_library_id()
        service.add_entries(library_id, [sample_image_path])
        record = service.create_collection(library_id, "Travel")

        entry = service.add_entry_to_collection(library_id, sample_image_path, record.id)

        assert entry.collection_ids == [record.id]

    def test_add_entry_to_collection_is_a_no_op_when_already_a_member(
        self, library_catalog_path, sample_image_path
    ):
        service = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = service.get_current_library_id()
        service.add_entries(library_id, [sample_image_path])
        record = service.create_collection(library_id, "Travel")
        service.add_entry_to_collection(library_id, sample_image_path, record.id)
        library = service.list_libraries()[0]
        updated_at_after_first_add = library.updated_at

        service.add_entry_to_collection(library_id, sample_image_path, record.id)

        assert library.updated_at == updated_at_after_first_add

    def test_add_entry_to_collection_unknown_collection_or_path_returns_none(
        self, library_catalog_path, sample_image_path
    ):
        service = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = service.get_current_library_id()
        service.add_entries(library_id, [sample_image_path])
        record = service.create_collection(library_id, "Travel")

        assert (
            service.add_entry_to_collection(library_id, sample_image_path, "no-such-id")
            is None
        )
        assert (
            service.add_entry_to_collection(library_id, "/no/such/file.jpg", record.id)
            is None
        )

    def test_remove_entry_from_collection_clears_membership(
        self, library_catalog_path, sample_image_path
    ):
        service = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = service.get_current_library_id()
        service.add_entries(library_id, [sample_image_path])
        record = service.create_collection(library_id, "Travel")
        service.add_entry_to_collection(library_id, sample_image_path, record.id)

        entry = service.remove_entry_from_collection(
            library_id, sample_image_path, record.id
        )

        assert entry.collection_ids == []

    def test_remove_entry_from_collection_is_a_no_op_when_not_a_member(
        self, library_catalog_path, sample_image_path
    ):
        service = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = service.get_current_library_id()
        service.add_entries(library_id, [sample_image_path])
        library = service.list_libraries()[0]
        updated_at_before = library.updated_at

        entry = service.remove_entry_from_collection(
            library_id, sample_image_path, "no-such-id"
        )

        assert entry.collection_ids == []
        assert library.updated_at == updated_at_before

    def test_delete_collection_removes_it_and_strips_dangling_entry_references(
        self, library_catalog_path, sample_image_path
    ):
        """The crux regression test: deleting a collection must not leave
        any entry pointing at an id that no longer exists anywhere."""
        service = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = service.get_current_library_id()
        service.add_entries(library_id, [sample_image_path])
        record = service.create_collection(library_id, "Travel")
        service.add_entry_to_collection(library_id, sample_image_path, record.id)
        entry_before = service.get_entry(library_id, sample_image_path)
        assert entry_before.collection_ids == [record.id]

        deleted = service.delete_collection(library_id, record.id)

        assert deleted is True
        assert service.list_collections(library_id) == []
        entry_after = service.get_entry(library_id, sample_image_path)
        assert entry_after.collection_ids == []
        assert record.id not in entry_after.collection_ids

    def test_delete_collection_unknown_id_returns_false(self, library_catalog_path):
        service = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = service.get_current_library_id()

        assert service.delete_collection(library_id, "no-such-id") is False

    def test_delete_collection_unknown_library_returns_false(self, library_catalog_path):
        service = LibraryCatalogService(catalog_path=library_catalog_path)

        assert service.delete_collection("no-such-library", "any-id") is False

    def test_collections_and_membership_survive_reload(
        self, library_catalog_path, sample_image_path
    ):
        first = LibraryCatalogService(catalog_path=library_catalog_path)
        library_id = first.get_current_library_id()
        first.add_entries(library_id, [sample_image_path])
        record = first.create_collection(library_id, "Travel")
        first.add_entry_to_collection(library_id, sample_image_path, record.id)

        reloaded = LibraryCatalogService(catalog_path=library_catalog_path)
        reloaded_collections = reloaded.list_collections(library_id)
        reloaded_entry = reloaded.get_entry(library_id, sample_image_path)

        assert [c.id for c in reloaded_collections] == [record.id]
        assert reloaded_collections[0].name == "Travel"
        assert reloaded_entry.collection_ids == [record.id]

    def test_collections_missing_from_old_catalog_payload_defaults_to_empty(self):
        """Catalog files written before this slice have no "collections"
        key on the library and no "collection_ids" key on any entry."""
        from src.services.library_catalog_service import LibraryEntry, LibraryRecord

        library = LibraryRecord.from_dict(
            {
                "id": "lib-1",
                "name": "Library 1",
                "created_at": "2024-01-01T00:00:00+00:00",
                "updated_at": "2024-01-01T00:00:00+00:00",
                "entries": [
                    {
                        "path": "/photos/old.jpg",
                        "filename": "old.jpg",
                        "added_at": "2024-01-01T00:00:00+00:00",
                        "last_seen_mtime_ns": None,
                        "last_seen_size": None,
                        "status": "available",
                    }
                ],
                # No "collections" key at all.
            }
        )

        assert library.collections == []
        assert library.entries[0].collection_ids == []

    def test_normalize_collection_ids_rejects_non_list_input(self):
        from src.services.library_catalog_service import _normalize_collection_ids

        assert _normalize_collection_ids(None) == []
        assert _normalize_collection_ids("abc") == []
        assert _normalize_collection_ids(42) == []

    def test_normalize_collection_ids_dedupes_and_drops_empty(self):
        from src.services.library_catalog_service import _normalize_collection_ids

        assert _normalize_collection_ids(["a", "a", "", "   ", "b"]) == ["a", "b"]
