"""Persistent named-library catalog storage."""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.services.storage_path_utils import (
    ensure_writable_directory,
    resolve_app_data_root,
)


logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1
_CATALOG_FILENAME = "library_catalog.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_path(path: str) -> str:
    raw = os.path.normpath(str(Path(path).expanduser()))
    return os.path.normcase(raw)


def _resolve_catalog_root() -> Path:
    return resolve_app_data_root()


@dataclass
class LibraryEntry:
    """One source file tracked inside a named library."""

    path: str
    filename: str
    added_at: str
    last_seen_mtime_ns: Optional[int]
    last_seen_size: Optional[int]
    status: str
    thumbnail_cache_key: Optional[str] = None
    adjustment_state: Optional[dict] = None
    favorite: bool = False
    rating: int = 0
    flag: str = "none"
    keywords: list[str] = field(default_factory=list)
    collection_ids: list[str] = field(default_factory=list)

    @property
    def normalized_path(self) -> str:
        return _normalize_path(self.path)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "filename": self.filename,
            "added_at": self.added_at,
            "last_seen_mtime_ns": self.last_seen_mtime_ns,
            "last_seen_size": self.last_seen_size,
            "status": self.status,
            "thumbnail_cache_key": self.thumbnail_cache_key,
            "adjustment_state": self.adjustment_state,
            "favorite": self.favorite,
            "rating": self.rating,
            "flag": self.flag,
            "keywords": self.keywords,
            "collection_ids": self.collection_ids,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "LibraryEntry":
        return cls(
            path=str(payload.get("path", "")),
            filename=str(payload.get("filename", "")),
            added_at=str(payload.get("added_at", _utc_now_iso())),
            last_seen_mtime_ns=_optional_int(payload.get("last_seen_mtime_ns")),
            last_seen_size=_optional_int(payload.get("last_seen_size")),
            status=str(payload.get("status", "missing")),
            thumbnail_cache_key=_optional_str(payload.get("thumbnail_cache_key")),
            adjustment_state=_optional_dict(payload.get("adjustment_state")),
            favorite=bool(payload.get("favorite", False)),
            rating=_clamp_rating(payload.get("rating", 0)),
            flag=_normalize_flag(payload.get("flag", "none")),
            keywords=_normalize_keywords(payload.get("keywords", [])),
            collection_ids=_normalize_collection_ids(payload.get("collection_ids", [])),
        )


@dataclass
class CollectionRecord:
    """A user-created, flat (non-nested) collection scoped to one library.

    See docs/planning/implementation-notes/2026-10-13-collections.md --
    collections are a new top-level entity, not a per-entry scalar field,
    and deliberately do not cross library boundaries (no "id" is ever
    looked up outside the library that owns it).
    """

    id: str
    name: str

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name}

    @classmethod
    def from_dict(cls, payload: dict) -> "CollectionRecord":
        return cls(
            id=str(payload.get("id", uuid.uuid4().hex)),
            name=str(payload.get("name", "Collection")),
        )


@dataclass
class LibraryRecord:
    """Persistent named library."""

    id: str
    name: str
    created_at: str
    updated_at: str
    entries: list[LibraryEntry] = field(default_factory=list)
    collections: list[CollectionRecord] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "entries": [entry.to_dict() for entry in self.entries],
            "collections": [collection.to_dict() for collection in self.collections],
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "LibraryRecord":
        return cls(
            id=str(payload.get("id", uuid.uuid4().hex)),
            name=str(payload.get("name", "Library")),
            created_at=str(payload.get("created_at", _utc_now_iso())),
            updated_at=str(payload.get("updated_at", _utc_now_iso())),
            entries=[
                LibraryEntry.from_dict(entry)
                for entry in payload.get("entries", [])
                if isinstance(entry, dict)
            ],
            collections=[
                CollectionRecord.from_dict(item)
                for item in payload.get("collections", [])
                if isinstance(item, dict)
            ],
        )


@dataclass
class LibraryCatalog:
    """Top-level persisted catalog."""

    schema_version: int
    current_library_id: str
    libraries: list[LibraryRecord] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "current_library_id": self.current_library_id,
            "libraries": [library.to_dict() for library in self.libraries],
        }


def _optional_int(value) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value) -> Optional[str]:
    if value is None or value == "":
        return None
    return str(value)


def _optional_dict(value) -> Optional[dict]:
    if not isinstance(value, dict):
        return None
    return dict(value)


def _clamp_rating(value) -> int:
    """Coerce a persisted/incoming rating to an integer in 0..5.

    Defensive against corrupt or out-of-range catalog data (and against
    older catalog files that predate this field entirely, which already
    default to 0 via ``payload.get("rating", 0)`` at the call site).
    """
    try:
        rating = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(5, rating))


def _normalize_flag(value) -> str:
    """Coerce a persisted/incoming pick/reject flag to "none"/"pick"/"reject".

    Defensive against corrupt or old-format catalog data (a missing key,
    ``None``, or any other garbage value, all coerce to "none") the same
    way ``_clamp_rating`` defends against out-of-range/non-numeric rating
    values -- never raises.
    """
    if value in ("pick", "reject"):
        return value
    return "none"


def _normalize_keywords(value) -> list[str]:
    """Coerce a persisted/incoming keyword list to a clean ``list[str]``.

    Defensive against corrupt or old-format catalog data the same way
    ``_optional_dict``/``_clamp_rating``/``_normalize_flag`` defend their
    own fields -- never raises. A non-list ``value`` (missing key, ``None``,
    a stray string/int/dict) normalizes to ``[]``. Otherwise, each item is
    coerced to ``str``, stripped of surrounding whitespace, and empty
    strings are dropped. Duplicates are removed case-insensitively (so
    "Sunset" and "sunset" collapse to one entry) while preserving the
    first-seen casing/spelling and insertion order.
    """
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned


def _normalize_collection_ids(value) -> list[str]:
    """Coerce a persisted/incoming ``collection_ids`` list to a clean
    ``list[str]``.

    Mirrors ``_normalize_keywords``'s defensive "coerce, never raise"
    style: a non-list ``value`` normalizes to ``[]``, each item is
    coerced to ``str`` and stripped, empty strings are dropped, and
    duplicates are removed while preserving insertion order. Unlike
    keywords, dedup here is a plain exact-string dedup (ids are opaque
    tokens, not user-facing text), not case-insensitive.

    This does *not* check that each id names a collection that still
    exists in the library -- that cross-check (and the pruning of
    dangling references when a collection is deleted) is
    ``LibraryCatalogService.delete_collection``'s job, not this
    load-time coercion's.
    """
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


class LibraryCatalogService:
    """Single business-logic entry point for libraries and their entries."""

    def __init__(self, catalog_path: Optional[Path] = None) -> None:
        root = catalog_path if catalog_path is not None else _resolve_catalog_root()
        root = Path(root)
        desired_path = root if root.suffix else root / _CATALOG_FILENAME
        catalog_parent = ensure_writable_directory(
            desired_path.parent,
            Path("appdata"),
        )
        self._catalog_path = catalog_parent / desired_path.name
        self._catalog = self._load_catalog()

    @property
    def catalog_path(self) -> Path:
        return self._catalog_path

    def list_libraries(self) -> list[LibraryRecord]:
        return list(self._catalog.libraries)

    def create_library(self, name: str) -> LibraryRecord:
        clean_name = name.strip()
        if not clean_name:
            clean_name = self.next_default_library_name()
        now = _utc_now_iso()
        record = LibraryRecord(
            id=uuid.uuid4().hex,
            name=clean_name,
            created_at=now,
            updated_at=now,
        )
        self._catalog.libraries.append(record)
        self._catalog.current_library_id = record.id
        self._save_catalog()
        logger.info("Created library '%s' (%s)", record.name, record.id)
        return record

    def remove_library(self, library_id: str) -> Optional[LibraryRecord]:
        library = self.get_library(library_id)
        if library is None:
            return None
        self._catalog.libraries = [
            existing for existing in self._catalog.libraries if existing.id != library_id
        ]
        if not self._catalog.libraries:
            replacement = self._build_default_library()
            self._catalog.libraries = [replacement]
            self._catalog.current_library_id = replacement.id
        elif self._catalog.current_library_id == library_id:
            self._catalog.current_library_id = self._catalog.libraries[0].id
        self._save_catalog()
        logger.info("Removed library '%s' (%s)", library.name, library.id)
        return library

    def get_current_library_id(self) -> str:
        return self._catalog.current_library_id

    def set_current_library(self, library_id: str) -> None:
        if self.get_library(library_id) is None:
            raise KeyError(f"Unknown library id: {library_id}")
        if self._catalog.current_library_id == library_id:
            return
        self._catalog.current_library_id = library_id
        self._save_catalog()

    def get_library(self, library_id: str) -> Optional[LibraryRecord]:
        for library in self._catalog.libraries:
            if library.id == library_id:
                return library
        return None

    def list_entries(self, library_id: str) -> list[LibraryEntry]:
        library = self._require_library(library_id)
        changed = False
        for entry in library.entries:
            changed = self._refresh_entry(entry) or changed
        if changed:
            library.updated_at = _utc_now_iso()
            self._save_catalog()
        return list(library.entries)

    def get_entry(self, library_id: str, path: str) -> LibraryEntry:
        library = self._require_library(library_id)
        return self._require_entry(library, path)

    def add_entries(self, library_id: str, paths: list[str]) -> list[LibraryEntry]:
        library = self._require_library(library_id)
        existing = {entry.normalized_path for entry in library.entries}
        changed = False
        for raw_path in paths:
            path = Path(raw_path).expanduser()
            normalized = _normalize_path(str(path))
            if normalized in existing:
                continue
            entry = self._build_entry(str(path))
            library.entries.append(entry)
            existing.add(normalized)
            changed = True
        if changed:
            library.updated_at = _utc_now_iso()
            self._save_catalog()
        return list(library.entries)

    def clear_library_entries(self, library_id: str) -> None:
        library = self._require_library(library_id)
        if not library.entries:
            return
        library.entries.clear()
        library.updated_at = _utc_now_iso()
        self._save_catalog()

    def refresh_entry_status(self, library_id: str, path: str) -> LibraryEntry:
        library = self._require_library(library_id)
        entry = self._require_entry(library, path)
        changed = self._refresh_entry(entry)
        if changed:
            library.updated_at = _utc_now_iso()
            self._save_catalog()
        return entry

    def mark_entry_missing(self, library_id: str, path: str) -> LibraryEntry:
        library = self._require_library(library_id)
        entry = self._require_entry(library, path)
        entry.status = "missing"
        entry.last_seen_mtime_ns = None
        entry.last_seen_size = None
        library.updated_at = _utc_now_iso()
        self._save_catalog()
        return entry

    def set_entry_thumbnail_cache_key(
        self, library_id: str, path: str, cache_key: Optional[str]
    ) -> LibraryEntry:
        library = self._require_library(library_id)
        entry = self._require_entry(library, path)
        if entry.thumbnail_cache_key == cache_key:
            return entry
        entry.thumbnail_cache_key = cache_key
        library.updated_at = _utc_now_iso()
        self._save_catalog()
        return entry

    def get_entry_adjustment_state(self, library_id: str, path: str) -> Optional[dict]:
        library = self._require_library(library_id)
        entry = self._require_entry(library, path)
        if entry.adjustment_state is None:
            return None
        return dict(entry.adjustment_state)

    def set_entry_adjustment_state(
        self,
        library_id: str,
        path: str,
        adjustment_state: Optional[dict],
    ) -> LibraryEntry:
        library = self._require_library(library_id)
        entry = self._require_entry(library, path)
        normalized = _optional_dict(adjustment_state)
        if entry.adjustment_state == normalized:
            return entry
        entry.adjustment_state = normalized
        library.updated_at = _utc_now_iso()
        self._save_catalog()
        return entry

    def set_entry_favorite(
        self, library_id: str, path: str, favorite: bool
    ) -> LibraryEntry:
        """Persist whether an entry belongs to the Favorites smart collection."""
        library = self._require_library(library_id)
        entry = self._require_entry(library, path)
        favorite = bool(favorite)
        if entry.favorite == favorite:
            return entry
        entry.favorite = favorite
        library.updated_at = _utc_now_iso()
        self._save_catalog()
        return entry

    def set_entry_rating(
        self, library_id: str, path: str, rating: int
    ) -> LibraryEntry:
        """Persist a 0-5 star rating for an entry.

        Out-of-range values are clamped rather than rejected -- friendlier
        for a library-metadata setter than raising, and consistent with how
        a corrupt/out-of-range persisted value is handled on read (see
        ``_clamp_rating``).
        """
        library = self._require_library(library_id)
        entry = self._require_entry(library, path)
        rating = _clamp_rating(rating)
        if entry.rating == rating:
            return entry
        entry.rating = rating
        library.updated_at = _utc_now_iso()
        self._save_catalog()
        return entry

    def set_entry_flag(
        self, library_id: str, path: str, flag: str
    ) -> LibraryEntry:
        """Persist a pick/reject flag ("none"/"pick"/"reject") for an entry.

        Anything other than exactly "pick" or "reject" normalizes to
        "none" rather than raising -- mirrors ``set_entry_rating``'s clamp
        style for the same reasons (see ``_normalize_flag``).
        """
        library = self._require_library(library_id)
        entry = self._require_entry(library, path)
        flag = _normalize_flag(flag)
        if entry.flag == flag:
            return entry
        entry.flag = flag
        library.updated_at = _utc_now_iso()
        self._save_catalog()
        return entry

    def set_entry_keywords(
        self, library_id: str, path: str, keywords: list[str]
    ) -> LibraryEntry:
        """Persist a list of free-text keywords for an entry.

        Normalizes (strips/drops empties/case-insensitively dedupes while
        preserving first-seen casing and order) rather than raising on
        malformed input -- mirrors ``set_entry_rating``/``set_entry_flag``'s
        clamp/normalize style for the same reasons (see
        ``_normalize_keywords``).
        """
        library = self._require_library(library_id)
        entry = self._require_entry(library, path)
        keywords = _normalize_keywords(keywords)
        if entry.keywords == keywords:
            return entry
        entry.keywords = keywords
        library.updated_at = _utc_now_iso()
        self._save_catalog()
        return entry

    def list_collections(self, library_id: str) -> list[CollectionRecord]:
        """Return the flat list of collections for one library.

        Never raises on an unknown ``library_id`` -- returns ``[]``
        instead, matching the "defensive setter" style the rest of this
        service already uses for bad input (unlike ``_require_library``'s
        internal callers, which legitimately want a ``KeyError``).
        """
        library = self.get_library(library_id)
        if library is None:
            return []
        return list(library.collections)

    def create_collection(self, library_id: str, name: str) -> Optional[CollectionRecord]:
        """Create a new, empty collection in one library.

        An empty/whitespace-only ``name`` is defensively rejected (returns
        ``None``, no catalog mutation) rather than silently creating an
        unnamed collection -- there is no sensible auto-generated default
        the way there is for a new library's name. Duplicate names ARE
        allowed (no uniqueness check): two collections can share a
        display name, distinguished only by id, the same way nothing in
        this codebase stops two libraries from sharing a name either.
        """
        library = self.get_library(library_id)
        if library is None:
            return None
        clean_name = name.strip() if isinstance(name, str) else ""
        if not clean_name:
            return None
        record = CollectionRecord(id=uuid.uuid4().hex, name=clean_name)
        library.collections.append(record)
        library.updated_at = _utc_now_iso()
        self._save_catalog()
        return record

    def rename_collection(
        self, library_id: str, collection_id: str, new_name: str
    ) -> Optional[CollectionRecord]:
        """Rename an existing collection. No-op (returns ``None``) on an
        unknown library/collection id or an empty/whitespace-only name."""
        library = self.get_library(library_id)
        if library is None:
            return None
        collection = self._find_collection(library, collection_id)
        if collection is None:
            return None
        clean_name = new_name.strip() if isinstance(new_name, str) else ""
        if not clean_name or collection.name == clean_name:
            return collection
        collection.name = clean_name
        library.updated_at = _utc_now_iso()
        self._save_catalog()
        return collection

    def delete_collection(self, library_id: str, collection_id: str) -> bool:
        """Delete a collection and strip its id out of every entry's
        ``collection_ids`` so no dangling reference survives the delete.

        Returns ``True`` if a collection was actually removed, ``False``
        on an unknown library/collection id (never raises).
        """
        library = self.get_library(library_id)
        if library is None:
            return False
        collection = self._find_collection(library, collection_id)
        if collection is None:
            return False
        library.collections = [
            existing for existing in library.collections if existing.id != collection_id
        ]
        for entry in library.entries:
            if collection_id in entry.collection_ids:
                entry.collection_ids = [
                    cid for cid in entry.collection_ids if cid != collection_id
                ]
        library.updated_at = _utc_now_iso()
        self._save_catalog()
        return True

    def add_entry_to_collection(
        self, library_id: str, path: str, collection_id: str
    ) -> Optional[LibraryEntry]:
        """Add one entry to one collection. No-op on an unknown library,
        collection, or path (returns ``None``, never raises); also a no-op
        (no save) if the entry already belongs to that collection."""
        library = self.get_library(library_id)
        if library is None:
            return None
        if self._find_collection(library, collection_id) is None:
            return None
        try:
            entry = self._require_entry(library, path)
        except KeyError:
            return None
        if collection_id in entry.collection_ids:
            return entry
        entry.collection_ids = [*entry.collection_ids, collection_id]
        library.updated_at = _utc_now_iso()
        self._save_catalog()
        return entry

    def remove_entry_from_collection(
        self, library_id: str, path: str, collection_id: str
    ) -> Optional[LibraryEntry]:
        """Remove one entry from one collection. No-op on an unknown
        library or path (returns ``None``, never raises); also a no-op (no
        save) if the entry was not in that collection to begin with."""
        library = self.get_library(library_id)
        if library is None:
            return None
        try:
            entry = self._require_entry(library, path)
        except KeyError:
            return None
        if collection_id not in entry.collection_ids:
            return entry
        entry.collection_ids = [
            cid for cid in entry.collection_ids if cid != collection_id
        ]
        library.updated_at = _utc_now_iso()
        self._save_catalog()
        return entry

    def _find_collection(
        self, library: LibraryRecord, collection_id: str
    ) -> Optional[CollectionRecord]:
        for collection in library.collections:
            if collection.id == collection_id:
                return collection
        return None

    def referenced_cache_keys(self) -> set[str]:
        keys: set[str] = set()
        for library in self._catalog.libraries:
            for entry in library.entries:
                if entry.thumbnail_cache_key:
                    keys.add(entry.thumbnail_cache_key)
        return keys

    def referenced_adjustment_preview_cache_keys(self) -> set[str]:
        keys: set[str] = set()
        for library in self._catalog.libraries:
            for entry in library.entries:
                payload = entry.adjustment_state
                if not isinstance(payload, dict):
                    continue
                preview_cache_key = payload.get("preview_cache_key")
                if isinstance(preview_cache_key, str) and preview_cache_key:
                    keys.add(preview_cache_key)
        return keys

    def next_default_library_name(self) -> str:
        existing = {library.name for library in self._catalog.libraries}
        index = 1
        while True:
            candidate = f"Library {index}"
            if candidate not in existing:
                return candidate
            index += 1

    def _load_catalog(self) -> LibraryCatalog:
        if not self._catalog_path.exists():
            catalog = self._create_default_catalog()
            self._write_catalog(catalog)
            return catalog
        try:
            payload = json.loads(self._catalog_path.read_text(encoding="utf-8"))
            libraries = [
                LibraryRecord.from_dict(item)
                for item in payload.get("libraries", [])
                if isinstance(item, dict)
            ]
            if not libraries:
                raise ValueError("Catalog contained no libraries")
            current_library_id = str(payload.get("current_library_id", ""))
            if not any(library.id == current_library_id for library in libraries):
                current_library_id = libraries[0].id
            catalog = LibraryCatalog(
                schema_version=int(payload.get("schema_version", _SCHEMA_VERSION)),
                current_library_id=current_library_id,
                libraries=libraries,
            )
            return catalog
        except Exception:
            logger.exception(
                "Failed to load library catalog from %s; recreating default catalog",
                self._catalog_path,
            )
            catalog = self._create_default_catalog()
            self._write_catalog(catalog)
            return catalog

    def _create_default_catalog(self) -> LibraryCatalog:
        library = self._build_default_library()
        return LibraryCatalog(
            schema_version=_SCHEMA_VERSION,
            current_library_id=library.id,
            libraries=[library],
        )

    def _build_default_library(self) -> LibraryRecord:
        now = _utc_now_iso()
        return LibraryRecord(
            id=uuid.uuid4().hex,
            name="Library 1",
            created_at=now,
            updated_at=now,
        )

    def _build_entry(self, raw_path: str) -> LibraryEntry:
        path = Path(raw_path).expanduser().absolute()
        added_at = _utc_now_iso()
        try:
            stat = path.stat()
            status = "available"
            mtime_ns = int(stat.st_mtime_ns)
            size = int(stat.st_size)
        except OSError:
            status = "missing"
            mtime_ns = None
            size = None
        return LibraryEntry(
            path=str(path),
            filename=path.name,
            added_at=added_at,
            last_seen_mtime_ns=mtime_ns,
            last_seen_size=size,
            status=status,
        )

    def _refresh_entry(self, entry: LibraryEntry) -> bool:
        path = Path(entry.path)
        try:
            stat = path.stat()
        except OSError:
            changed = entry.status != "missing"
            changed = (entry.last_seen_mtime_ns is not None) or changed
            changed = (entry.last_seen_size is not None) or changed
            entry.status = "missing"
            entry.last_seen_mtime_ns = None
            entry.last_seen_size = None
            return changed

        changed = False
        mtime_ns = int(stat.st_mtime_ns)
        size = int(stat.st_size)
        if entry.status != "available":
            changed = True
        if entry.last_seen_mtime_ns != mtime_ns:
            changed = True
        if entry.last_seen_size != size:
            changed = True
        if entry.filename != path.name:
            changed = True
        entry.status = "available"
        entry.filename = path.name
        entry.last_seen_mtime_ns = mtime_ns
        entry.last_seen_size = size
        return changed

    def _save_catalog(self) -> None:
        self._catalog.schema_version = _SCHEMA_VERSION
        self._write_catalog(self._catalog)

    def _write_catalog(self, catalog: LibraryCatalog) -> None:
        payload = json.dumps(catalog.to_dict(), indent=2, sort_keys=True)
        temp_path = self._catalog_path.with_suffix(self._catalog_path.suffix + ".tmp")
        temp_path.write_text(payload, encoding="utf-8")
        temp_path.replace(self._catalog_path)

    def _require_library(self, library_id: str) -> LibraryRecord:
        library = self.get_library(library_id)
        if library is None:
            raise KeyError(f"Unknown library id: {library_id}")
        return library

    def _require_entry(self, library: LibraryRecord, path: str) -> LibraryEntry:
        normalized = _normalize_path(path)
        for entry in library.entries:
            if entry.normalized_path == normalized:
                return entry
        raise KeyError(f"Unknown library entry path: {path}")
