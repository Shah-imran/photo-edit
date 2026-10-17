# Export dialog dimension crash fix

## 1. Problem

Exporting an image crashed every time, reported directly from a live run:

```
File "...\src\views\main_window.py", line 771, in _export_image
    dialog = ExportDialog(...)
File "...\src\views\export_dialog.py", line 110, in __init__
    self._setup_ui()
File "...\src\views\export_dialog.py", line 172, in _setup_ui
    self._width_spin.setValue(self._image.width)
AttributeError: 'numpy.ndarray' object has no attribute 'width'
```

`ExportDialog` was written against a `PIL.Image` (`.width`/`.height`
attributes), but every real caller --
`ImageController.get_export_image()`, and therefore
`MainWindow._export_image()`/`_export_with_previous()` -- has long
passed a raw `LinearImage` (a `(H, W, 3)` float32 numpy array), which
has no such attributes. This was not a regression from this session's
work: the mismatch dates to `export_dialog.py`'s original
implementation, predating every slice in this session. It went
uncaught because `tests/unit/test_views/test_export_dialog.py`'s
`sample_image` fixture used a real `PIL.Image.new(...)`, which matched
the (wrong) code but not production reality, so the test suite passed
while the real app crashed on every export.

## 2. Fix

`ExportDialog.__init__` now reads `self._image_width = image.shape[1]`
and `self._image_height = image.shape[0]` once, and every former
`self._image.width`/`.height` reference (six call sites, across
`_setup_ui`, `_on_resize_preset_changed`, and `_do_export`) uses those
instead. The constructor's docstring and type hint were corrected to
describe a `LinearImage`, not a PIL Image; the now-unused `from PIL
import Image` was removed.

## 3. Test fixtures corrected

`tests/unit/test_views/test_export_dialog.py`'s `sample_image` fixture
and `tests/unit/test_views/test_main_window_export_with_previous.py`'s
equivalent fixture both now return a real `np.full((10, 10, 3), 0.5,
dtype=np.float32)` LinearImage instead of a PIL Image, matching what
every real caller actually passes. This is what should have caught
the bug originally; it's why fixing only the fixture, without the
production code change, would not have been enough on its own, and
why fixing only the production code without the fixture would have
left this exact class of regression able to recur silently again.

Verified directly: constructing `ExportDialog` with a real
`(600, 400, 3)` float32 array (matching the crash report's own
`shape=(600, 400, 3)` log line) no longer raises, and the width/height
spin boxes report the correct values (400/600).

## 4. Scope

This was a pure bug fix, not a new feature -- no behavior changes
beyond "export no longer crashes." `MainWindow._export_with_previous`
and `ExportService.export_image`/`ImageService.save_image` were
already correctly numpy-based throughout; only `ExportDialog`'s own
dimension reads were wrong.

## 5. Test results

Full suite: 1024 passed, 1 skipped, 1 deselected (same count as
before this fix -- it's a pure bug fix, not new coverage, though the
corrected fixtures now exercise the real code path instead of masking
it).
