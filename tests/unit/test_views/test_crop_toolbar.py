"""Unit tests for the CropToolbar widget."""

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from src.views.widgets.crop_toolbar import CropToolbar


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestComboPopulation:
    def test_items_in_order(self, qapp):
        toolbar = CropToolbar()
        items = [toolbar._aspect_combo.itemText(i) for i in range(toolbar._aspect_combo.count())]
        assert items == [
            "Free", "Original", "1:1", "16:9", "9:16", "4:3", "3:4", "5:4", "4:5",
        ]

    def test_free_is_default(self, qapp):
        toolbar = CropToolbar()
        assert toolbar._aspect_combo.currentText() == "Free"


class TestAspectRatioSignal:
    @pytest.mark.parametrize(
        "label,expected",
        [
            ("1:1", 1.0),
            ("16:9", 16.0 / 9.0),
            ("9:16", 9.0 / 16.0),
            ("4:3", 4.0 / 3.0),
            ("3:4", 3.0 / 4.0),
            ("5:4", 5.0 / 4.0),
            ("4:5", 4.0 / 5.0),
        ],
    )
    def test_named_ratio_emits_correct_value(self, qapp, label, expected):
        toolbar = CropToolbar()
        received = []
        toolbar.aspect_ratio_changed.connect(received.append)
        toolbar._aspect_combo.setCurrentText(label)
        assert received == [pytest.approx(expected)]

    def test_free_emits_none(self, qapp):
        toolbar = CropToolbar()
        toolbar._aspect_combo.setCurrentText("1:1")
        received = []
        toolbar.aspect_ratio_changed.connect(received.append)
        toolbar._aspect_combo.setCurrentText("Free")
        assert received == [None]

    def test_set_original_ratio_then_select_original_emits_it(self, qapp):
        toolbar = CropToolbar()
        toolbar.set_original_ratio(1.5)
        received = []
        toolbar.aspect_ratio_changed.connect(received.append)
        toolbar._aspect_combo.setCurrentText("Original")
        assert received == [1.5]

    def test_set_original_ratio_while_already_selected_emits_immediately(self, qapp):
        toolbar = CropToolbar()
        toolbar._aspect_combo.setCurrentText("Original")
        received = []
        toolbar.aspect_ratio_changed.connect(received.append)
        toolbar.set_original_ratio(2.0)
        assert received == [2.0]


class TestButtons:
    def test_apply_emits_signal(self, qapp):
        toolbar = CropToolbar()
        received = []
        toolbar.apply_requested.connect(lambda: received.append(True))
        QTest.mouseClick(toolbar._apply_button, Qt.MouseButton.LeftButton)
        assert received == [True]

    def test_cancel_emits_signal(self, qapp):
        toolbar = CropToolbar()
        received = []
        toolbar.cancel_requested.connect(lambda: received.append(True))
        QTest.mouseClick(toolbar._cancel_button, Qt.MouseButton.LeftButton)
        assert received == [True]
