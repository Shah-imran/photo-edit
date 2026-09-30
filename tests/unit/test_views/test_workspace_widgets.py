"""Tests for the polished workspace shell widgets."""

import numpy as np

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage
from PyQt6.QtTest import QTest

from src.views.theme import APP_STYLESHEET, apply_theme
from src.views.widgets.filmstrip_view import FilmstripView
from src.views.widgets.image_toolbar import ImageToolBar
from src.views.widgets.histogram_widget import HistogramWidget
from src.views.widgets.workspace_header import WorkspaceHeader


def _entry(path: str, *, status: str = "available") -> dict:
    return {
        "path": path,
        "status": status,
        "text": path.rsplit("/", 1)[-1],
        "tooltip": path,
        "placeholder": "loading",
    }


def test_apply_theme_installs_shared_stylesheet(qapp):
    apply_theme(qapp)
    assert qapp.styleSheet() == APP_STYLESHEET


def test_image_toolbar_emits_intents_and_tracks_zoom(qapp, qtbot):
    toolbar = ImageToolBar()
    qtbot.addWidget(toolbar)

    with qtbot.waitSignal(toolbar.fit_requested):
        QTest.mouseClick(toolbar._fit_button, Qt.MouseButton.LeftButton)
    with qtbot.waitSignal(toolbar.actual_size_requested):
        QTest.mouseClick(toolbar._actual_size_button, Qt.MouseButton.LeftButton)
    with qtbot.waitSignal(toolbar.zoom_in_requested):
        QTest.mouseClick(toolbar._zoom_in_button, Qt.MouseButton.LeftButton)
    with qtbot.waitSignal(toolbar.zoom_out_requested):
        QTest.mouseClick(toolbar._zoom_out_button, Qt.MouseButton.LeftButton)

    toolbar.set_zoom_factor(0.421)
    assert toolbar._zoom_label.text() == "42%"


def test_filmstrip_populates_selects_and_emits(qapp, qtbot):
    strip = FilmstripView()
    qtbot.addWidget(strip)
    strip.set_context("Landscapes")
    strip.set_entries([_entry("C:/photos/one.jpg"), _entry("C:/photos/two.jpg")])

    assert strip.count() == 2
    assert strip._source_label.text() == "Landscapes"
    assert strip._count_label.text() == "2 photos"
    strip.set_current_path("C:/photos/one.jpg")
    assert strip.current_path() == "C:/photos/one.jpg"

    with qtbot.waitSignal(strip.image_selected) as blocker:
        strip._list.setCurrentRow(1)
    assert blocker.args == ["C:/photos/two.jpg"]


def test_filmstrip_ignores_missing_selection_and_accepts_late_thumbnail(qapp, qtbot):
    strip = FilmstripView()
    qtbot.addWidget(strip)
    strip.set_entries([_entry("C:/photos/missing.jpg", status="missing")])
    received = []
    strip.image_selected.connect(received.append)

    strip._list.setCurrentRow(0)
    assert received == []

    image = QImage(24, 16, QImage.Format.Format_RGB888)
    image.fill(Qt.GlobalColor.red)
    payload = _entry("C:/photos/missing.jpg")
    payload["thumbnail"] = image
    strip.update_entry_thumbnail(payload["path"], payload)
    item = strip._item_by_path[payload["path"]]
    assert item.icon().isNull() is False


def test_filmstrip_filters_favorites_and_sorts_by_name(qapp, qtbot):
    strip = FilmstripView()
    qtbot.addWidget(strip)
    favorite = _entry("C:/photos/zebra.jpg")
    favorite["favorite"] = True
    strip.set_entries([favorite, _entry("C:/photos/alpha.jpg")])

    strip.set_sort("name")
    assert strip._list.item(0).data(Qt.ItemDataRole.UserRole).endswith("alpha.jpg")
    strip.set_filter("favorites")
    assert strip.count() == 1
    assert strip._list.item(0).data(Qt.ItemDataRole.UserRole).endswith("zebra.jpg")


def test_workspace_header_emits_primary_actions(qapp, qtbot):
    header = WorkspaceHeader()
    qtbot.addWidget(header)
    with qtbot.waitSignal(header.undo_requested):
        header._undo_button.click()
    with qtbot.waitSignal(header.redo_requested):
        header._redo_button.click()
    with qtbot.waitSignal(header.export_requested):
        header._export_button.click()
    assert header._compare_button.isEnabled() is False
    with qtbot.waitSignal(header.workspace_changed) as changed:
        header._library_tab.click()
    assert changed.args == ["library"]
    assert header._library_tab.isChecked() is True
    assert header._develop_tab.isChecked() is False


def test_histogram_accepts_rgb_image(qapp, qtbot):
    histogram = HistogramWidget()
    qtbot.addWidget(histogram)
    histogram.set_image(np.full((40, 60, 3), 0.5, dtype=np.float32))
    assert len(histogram._channels) == 3
    assert all(channel.sum() > 0 for channel in histogram._channels)

