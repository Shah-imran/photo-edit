"""Central lists of file extensions and the Qt open-dialog filter string.

Having one module avoids drift between Open, Import, and folder scanning.
"""

from __future__ import annotations

from pathlib import Path


STANDARD_IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp"}
)

# Common RAW extensions LibRaw / rawpy typically accept (not exhaustive).
RAW_IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".cr2",
        ".cr3",
        ".crw",
        ".nef",
        ".nrw",
        ".arw",
        ".srw",
        ".raf",
        ".rw2",
        ".orf",
        ".dng",
        ".pef",
        ".iiq",
        ".3fr",
        ".erf",
        ".mos",
        ".mef",
        ".mrw",
        ".x3f",
        ".rwl",
    }
)

ALL_IMAGE_EXTENSIONS: frozenset[str] = STANDARD_IMAGE_EXTENSIONS | RAW_IMAGE_EXTENSIONS


def is_raw_path(path: str | Path) -> bool:
    """Return True if the path suffix is treated as a camera RAW file."""
    return Path(path).suffix.lower() in RAW_IMAGE_EXTENSIONS


def open_image_file_dialog_filter() -> str:
    """Filter string for ``QFileDialog.getOpenFileName`` (images + RAW)."""
    exts = sorted(ALL_IMAGE_EXTENSIONS)
    pattern = " ".join(f"*{e}" for e in exts)
    return f"Image & RAW files ({pattern});;All Files (*)"
