"""Disk-backed edited preview cache for persistent libraries."""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

from PIL import Image
from PyQt6.QtGui import QImage

from src.services.storage_path_utils import (
    ensure_writable_directory,
    resolve_app_cache_root,
)
from src.utils.color_pipeline import LinearImage, linear_to_pil


logger = logging.getLogger(__name__)


def _normalize_path(path: str) -> str:
    raw = os.path.normpath(str(Path(path).expanduser()))
    return os.path.normcase(raw)


def _resolve_cache_root() -> Path:
    return resolve_app_cache_root()


class LibraryImagePreviewCacheService:
    """Read/write edited image previews keyed by source metadata + adjustments."""

    def __init__(self, cache_dir: Optional[Path] = None) -> None:
        root = cache_dir if cache_dir is not None else _resolve_cache_root()
        root = Path(root)
        desired_dir = (
            root / "library-image-previews"
            if not root.name.endswith("library-image-previews")
            else root
        )
        self._cache_dir = ensure_writable_directory(
            desired_dir,
            Path("cache") / "library-image-previews",
        )

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    def build_cache_key(
        self,
        path: str,
        last_seen_mtime_ns: Optional[int],
        last_seen_size: Optional[int],
        adjustment_values: dict[str, float],
    ) -> Optional[str]:
        if last_seen_mtime_ns is None or last_seen_size is None:
            return None
        signature = ",".join(
            f"{key}={float(adjustment_values.get(key, 0.0)):.4f}"
            for key in sorted(adjustment_values.keys())
        )
        digest = hashlib.sha1(
            f"{_normalize_path(path)}|{last_seen_mtime_ns}|{last_seen_size}|{signature}".encode(
                "utf-8"
            )
        ).hexdigest()
        return digest

    def path_for_key(self, cache_key: str) -> Path:
        prefix = cache_key[:2]
        return self._cache_dir / prefix / f"{cache_key}.png"

    def write_preview(
        self,
        cache_key: str,
        image: LinearImage,
        max_size: tuple[int, int] = (1800, 1800),
    ) -> Path:
        target = self.path_for_key(cache_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        pil = linear_to_pil(image)
        pil.thumbnail(max_size, resample=Image.Resampling.LANCZOS)
        pil.save(target, format="PNG")
        return target

    def load_qimage(self, cache_key: Optional[str]) -> Optional[QImage]:
        if not cache_key:
            return None
        path = self.path_for_key(cache_key)
        if not path.exists():
            return None
        image = QImage(str(path))
        if image.isNull():
            try:
                path.unlink()
            except OSError:
                logger.warning("Could not remove unreadable preview cache: %s", path)
            return None
        return image

    def remove_orphaned_cache(self, valid_keys: set[str]) -> int:
        removed = 0
        if not self._cache_dir.exists():
            return removed
        for path in self._cache_dir.rglob("*.png"):
            if path.stem in valid_keys:
                continue
            try:
                path.unlink()
                removed += 1
            except OSError:
                logger.warning("Could not remove orphaned preview cache: %s", path)
        return removed
