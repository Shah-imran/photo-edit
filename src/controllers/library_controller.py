"""Controller for persistent library and thumbnail orchestration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtGui import QImage

from src.services.image_service import ImageService
from src.services.library_catalog_service import (
    LibraryCatalogService,
    LibraryEntry,
)
from src.services.library_thumbnail_cache_service import (
    LibraryThumbnailCacheService,
)


logger = logging.getLogger(__name__)


@dataclass
class _ThumbnailTask:
    library_id: str
    file_path: str
    cache_key: str
    #: True if a valid cached PNG already exists on disk for this entry --
    #: the worker skips regenerating it and just lets the existing
    #: ``thumbnail_ready`` -> UI-thread-decode path load it, instead of the
    #: rebuild loop decoding it synchronously up front (see
    #: docs/planning/implementation-notes/2026-09-29-library-rebuild-responsiveness.md).
    cached: bool = False


class _ThumbnailBatchWorker(QObject):
    """Generate thumbnails in a background thread and populate disk cache."""

    thumbnail_ready = pyqtSignal(str, str, object, str)
    progress = pyqtSignal(int, int)
    finished = pyqtSignal()
    failed = pyqtSignal(str, str)

    def __init__(
        self,
        tasks: list[_ThumbnailTask],
        size: int,
        cache_service: LibraryThumbnailCacheService,
    ):
        super().__init__()
        self._tasks = list(tasks)
        self._size = int(size)
        self._cache_service = cache_service
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        service = ImageService()
        total = len(self._tasks)
        for idx, task in enumerate(self._tasks, start=1):
            if self._cancelled:
                break
            try:
                if not task.cached:
                    thumbnail = service.load_preview_thumbnail(
                        task.file_path,
                        (self._size, self._size),
                    )
                    self._cache_service.write_thumbnail(task.cache_key, thumbnail)
                # The cached case has nothing left to do here -- the PNG
                # already exists on disk. Either way, the UI-thread slot on
                # thumbnail_ready re-reads it as a QImage (one decode per
                # queued signal, naturally interleaved with the Qt event
                # loop -- unlike a tight synchronous loop).
                self.thumbnail_ready.emit(
                    task.library_id, task.file_path, None, task.cache_key
                )
            except Exception as exc:
                self.failed.emit(task.file_path, str(exc))
            self.progress.emit(idx, total)
        self.finished.emit()


class _OrphanCacheCleanupWorker(QObject):
    """Remove orphaned thumbnail cache files in a background thread.

    ``LibraryThumbnailCacheService.remove_orphaned_cache`` walks the
    entire thumbnail cache directory (``rglob``) and unlinks anything not
    referenced by any library -- a single long synchronous call with
    nothing to yield mid-way through, which used to run on the UI thread
    on every library rebuild. See
    docs/planning/implementation-notes/2026-09-29-library-rebuild-responsiveness.md.
    """

    finished = pyqtSignal()

    def __init__(
        self,
        cache_service: LibraryThumbnailCacheService,
        valid_keys: set[str],
    ):
        super().__init__()
        self._cache_service = cache_service
        self._valid_keys = valid_keys

    def run(self) -> None:
        try:
            self._cache_service.remove_orphaned_cache(self._valid_keys)
        except Exception:
            logger.exception("Orphaned thumbnail cache cleanup failed")
        self.finished.emit()


class LibraryController(QObject):
    """Thin controller between library view and storage/cache services."""

    libraries_changed = pyqtSignal(object, str)
    entries_rebuilt = pyqtSignal(str, object)
    entry_thumbnail_updated = pyqtSignal(str, object)
    thumbnail_batch_started = pyqtSignal(int)
    thumbnail_batch_progress = pyqtSignal(int, int)
    thumbnail_batch_finished = pyqtSignal()

    THUMBNAIL_SIZE = 80

    def __init__(
        self,
        catalog_service: Optional[LibraryCatalogService] = None,
        thumbnail_cache_service: Optional[LibraryThumbnailCacheService] = None,
    ) -> None:
        super().__init__()
        self._catalog_service = (
            catalog_service if catalog_service is not None else LibraryCatalogService()
        )
        self._thumbnail_cache_service = (
            thumbnail_cache_service
            if thumbnail_cache_service is not None
            else LibraryThumbnailCacheService()
        )
        self._thumbnail_thread: Optional[QThread] = None
        self._thumbnail_worker: Optional[_ThumbnailBatchWorker] = None
        self._orphan_cleanup_threads: list[QThread] = []
        # Keeps each worker alive until its thread finishes -- unlike
        # _thumbnail_worker (a single named slot), several cleanup passes
        # can be in flight at once (e.g. initialize() then an immediate
        # import_images()), so this is a list indexed by nothing but
        # membership; without it the worker is garbage-collected before
        # the queued started->run connection ever delivers, and run()
        # silently never executes.
        self._orphan_cleanup_workers: list[_OrphanCacheCleanupWorker] = []
        self._current_library_id = ""

    @property
    def current_library_id(self) -> str:
        return self._current_library_id

    def initialize(self) -> None:
        self._current_library_id = self._catalog_service.get_current_library_id()
        self._emit_libraries()
        self._rebuild_entries_for_current_library()

    def select_library(self, library_id: str) -> None:
        if not library_id or library_id == self._current_library_id:
            return
        self._catalog_service.set_current_library(library_id)
        self._current_library_id = library_id
        self._emit_libraries()
        self._rebuild_entries_for_current_library()

    def create_library(self, name: str) -> None:
        library = self._catalog_service.create_library(name)
        self._current_library_id = library.id
        self._emit_libraries()
        self._rebuild_entries_for_current_library()

    def remove_library(self, library_id: str) -> None:
        self._catalog_service.remove_library(library_id)
        self._cleanup_orphaned_cache_async(self._catalog_service.referenced_cache_keys())
        self._current_library_id = self._catalog_service.get_current_library_id()
        self._emit_libraries()
        self._rebuild_entries_for_current_library()

    def import_images(self, file_paths: list[str]) -> None:
        if not self._current_library_id or not file_paths:
            return
        self._catalog_service.add_entries(self._current_library_id, file_paths)
        self._rebuild_entries_for_current_library()

    def add_image(self, file_path: str) -> None:
        self.import_images([file_path])

    def clear_current_library(self) -> None:
        if not self._current_library_id:
            return
        self.cancel_thumbnail_batch()
        self._catalog_service.clear_library_entries(self._current_library_id)
        # _rebuild_entries_for_current_library() below already dispatches an
        # orphan-cache cleanup pass against the post-clear reference set;
        # an explicit call here would just be a redundant duplicate pass.
        self._rebuild_entries_for_current_library()

    def cleanup(self) -> None:
        self.cancel_thumbnail_batch()
        thread = self._thumbnail_thread
        if thread is not None:
            thread.quit()
            thread.wait(3000)
        for orphan_thread in list(self._orphan_cleanup_threads):
            orphan_thread.quit()
            orphan_thread.wait(3000)

    def get_library_name(self, library_id: str) -> str:
        library = self._catalog_service.get_library(library_id)
        return library.name if library is not None else "Library"

    def get_entry(self, library_id: str, file_path: str) -> Optional[LibraryEntry]:
        if not library_id or not file_path:
            return None
        try:
            return self._catalog_service.get_entry(library_id, file_path)
        except KeyError:
            return None

    def get_entry_adjustment_state(
        self, library_id: str, file_path: str
    ) -> Optional[dict]:
        if not library_id or not file_path:
            return None
        try:
            return self._catalog_service.get_entry_adjustment_state(
                library_id,
                file_path,
            )
        except KeyError:
            return None

    def set_entry_adjustment_state(
        self,
        library_id: str,
        file_path: str,
        adjustment_state: Optional[dict],
    ) -> None:
        if not library_id or not file_path:
            return
        try:
            self._catalog_service.set_entry_adjustment_state(
                library_id,
                file_path,
                adjustment_state,
            )
        except KeyError:
            logger.debug(
                "Skipping adjustment persistence for non-library image %s in %s",
                file_path,
                library_id,
            )

    def set_entry_favorite(self, file_path: str, favorite: bool) -> None:
        """Update favorite state for the current library and refresh its views."""
        if not self._current_library_id or not file_path:
            return
        self._catalog_service.set_entry_favorite(
            self._current_library_id, file_path, favorite
        )
        self._emit_libraries()
        self._rebuild_entries_for_current_library()

    def referenced_adjustment_preview_cache_keys(self) -> set[str]:
        return self._catalog_service.referenced_adjustment_preview_cache_keys()

    def cancel_thumbnail_batch(self) -> None:
        if self._thumbnail_worker is not None:
            self._thumbnail_worker.cancel()

    def _emit_libraries(self) -> None:
        libraries = [
            {
                "id": library.id,
                "name": library.name,
                "count": len(library.entries),
                "favorite_count": sum(1 for entry in library.entries if entry.favorite),
            }
            for library in self._catalog_service.list_libraries()
        ]
        self.libraries_changed.emit(libraries, self._current_library_id)

    def _rebuild_entries_for_current_library(self) -> None:
        self.cancel_thumbnail_batch()
        if not self._current_library_id:
            self.entries_rebuilt.emit("", [])
            return

        entries = self._catalog_service.list_entries(self._current_library_id)
        payloads: list[dict] = []
        tasks: list[_ThumbnailTask] = []
        for entry in entries:
            payload, task = self._entry_payload(entry)
            payloads.append(payload)
            if task is not None:
                tasks.append(task)

        self.entries_rebuilt.emit(self._current_library_id, payloads)
        self._cleanup_orphaned_cache_async(self._catalog_service.referenced_cache_keys())
        if tasks:
            self._start_thumbnail_batch(tasks)

    def _entry_payload(self, entry: LibraryEntry) -> tuple[dict, Optional[_ThumbnailTask]]:
        task: Optional[_ThumbnailTask] = None
        payload = {
            "path": entry.path,
            "filename": entry.filename,
            "status": entry.status,
            "text": entry.filename if entry.status == "available" else f"{entry.filename}\nMissing",
            "tooltip": entry.filename if entry.status == "available" else f"{entry.path}\nMissing",
            "thumbnail": None,
            "placeholder": "missing" if entry.status != "available" else "loading",
            "added_at": entry.added_at,
            "favorite": entry.favorite,
        }

        if entry.status != "available":
            return payload, None

        cache_key = self._thumbnail_cache_service.entry_cache_key(entry)
        if entry.thumbnail_cache_key != cache_key:
            self._catalog_service.set_entry_thumbnail_cache_key(
                self._current_library_id,
                entry.path,
                cache_key,
            )
            entry.thumbnail_cache_key = cache_key

        if cache_key:
            # Whether a cached PNG already exists or still needs to be
            # generated, defer the actual decode/generation to the
            # background thumbnail worker rather than decoding it here --
            # doing this synchronously for every entry is what caused the
            # "Not Responding" freeze this avoids (see
            # docs/planning/implementation-notes/2026-09-29-library-rebuild-responsiveness.md).
            # A plain existence check is a cheap stat(), not a decode.
            already_cached = self._thumbnail_cache_service.path_for_key(cache_key).exists()
            task = _ThumbnailTask(
                library_id=self._current_library_id,
                file_path=entry.path,
                cache_key=cache_key,
                cached=already_cached,
            )
        return payload, task

    def _start_thumbnail_batch(self, tasks: list[_ThumbnailTask]) -> None:
        if not tasks:
            return

        self.thumbnail_batch_started.emit(len(tasks))
        thread = QThread(self)
        worker = _ThumbnailBatchWorker(
            tasks,
            self.THUMBNAIL_SIZE,
            self._thumbnail_cache_service,
        )
        self._thumbnail_thread = thread
        self._thumbnail_worker = worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.thumbnail_ready.connect(self._on_thumbnail_ready)
        worker.progress.connect(self._on_thumbnail_progress)
        worker.failed.connect(self._on_thumbnail_failed)
        worker.finished.connect(self.thumbnail_batch_finished)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda t=thread, w=worker: self._clear_thumbnail_loader(t, w)
        )
        thread.start()

    def _on_thumbnail_ready(
        self,
        library_id: str,
        file_path: str,
        thumbnail,
        cache_key: str,
    ) -> None:
        self._catalog_service.set_entry_thumbnail_cache_key(
            library_id,
            file_path,
            cache_key,
        )
        entry = self._catalog_service.refresh_entry_status(library_id, file_path)
        payload = {
            "path": entry.path,
            "filename": entry.filename,
            "status": entry.status,
            "text": entry.filename,
            "tooltip": entry.filename,
            "thumbnail": QImage(str(self._thumbnail_cache_service.path_for_key(cache_key))),
            "placeholder": None,
            "added_at": entry.added_at,
            "favorite": entry.favorite,
        }
        if library_id == self._current_library_id:
            self.entry_thumbnail_updated.emit(file_path, payload)

    def _on_thumbnail_failed(self, file_path: str, error: str) -> None:
        logger.warning("Failed to load thumbnail for %s: %s", file_path, error)

    def _on_thumbnail_progress(self, current: int, total: int) -> None:
        self.thumbnail_batch_progress.emit(current, total)

    def _clear_thumbnail_loader(
        self,
        thread: QThread,
        worker: _ThumbnailBatchWorker,
    ) -> None:
        if self._thumbnail_thread is thread:
            self._thumbnail_thread = None
        if self._thumbnail_worker is worker:
            self._thumbnail_worker = None

    def _cleanup_orphaned_cache_async(self, valid_keys: set[str]) -> None:
        """Dispatch orphaned thumbnail-cache removal to a background thread.

        Fire-and-forget from the caller's perspective: touches only
        ``LibraryThumbnailCacheService`` (a cache directory on disk), never
        ``LibraryCatalogService``, so it needs no synchronization with the
        UI thread's own catalog access.
        """
        thread = QThread(self)
        worker = _OrphanCacheCleanupWorker(self._thumbnail_cache_service, valid_keys)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda t=thread, w=worker: self._clear_orphan_cleanup_thread(t, w)
        )
        self._orphan_cleanup_threads.append(thread)
        self._orphan_cleanup_workers.append(worker)
        thread.start()

    def _clear_orphan_cleanup_thread(
        self, thread: QThread, worker: "_OrphanCacheCleanupWorker"
    ) -> None:
        if thread in self._orphan_cleanup_threads:
            self._orphan_cleanup_threads.remove(thread)
        if worker in self._orphan_cleanup_workers:
            self._orphan_cleanup_workers.remove(worker)
