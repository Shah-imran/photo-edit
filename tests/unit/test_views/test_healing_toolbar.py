"""Unit tests for the HealingToolbar widget."""

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from src.views.widgets.healing_toolbar import HealingToolbar


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestSliderRanges:
    """Feather/opacity are both 0..1 fractions per HealingProcessor's own
    state contract (docs/planning/implementation-notes/
    2026-10-13-healing-processor.md section 4), confirmed, not guessed."""

    def test_feather_range(self, qapp):
        toolbar = HealingToolbar()
        assert toolbar._feather_slider._min_value == pytest.approx(0.0)
        assert toolbar._feather_slider._max_value == pytest.approx(1.0)

    def test_opacity_range(self, qapp):
        toolbar = HealingToolbar()
        assert toolbar._opacity_slider._min_value == pytest.approx(0.0)
        assert toolbar._opacity_slider._max_value == pytest.approx(1.0)


class TestSetValuesRoundTrip:
    def test_round_trip_without_emitting(self, qapp):
        toolbar = HealingToolbar()
        received_mode = []
        received_feather = []
        received_opacity = []
        toolbar.mode_changed.connect(received_mode.append)
        toolbar.feather_changed.connect(received_feather.append)
        toolbar.opacity_changed.connect(received_opacity.append)

        toolbar.set_values("clone", 0.6, 0.4)

        assert toolbar.get_mode() == "clone"
        assert toolbar.get_feather() == pytest.approx(0.6)
        assert toolbar.get_opacity() == pytest.approx(0.4)
        assert received_mode == []
        assert received_feather == []
        assert received_opacity == []

    def test_set_values_heal(self, qapp):
        toolbar = HealingToolbar()
        toolbar.set_values("heal", 0.3, 1.0)
        assert toolbar.get_mode() == "heal"
        assert toolbar.get_feather() == pytest.approx(0.3)
        assert toolbar.get_opacity() == pytest.approx(1.0)


class TestSignalsEmitOnControlChange:
    def test_mode_combo_emits(self, qapp):
        toolbar = HealingToolbar()
        received = []
        toolbar.mode_changed.connect(received.append)
        toolbar._mode_combo.setCurrentText("Clone")
        assert received == ["clone"]

    def test_feather_slider_emits(self, qapp):
        toolbar = HealingToolbar()
        received = []
        toolbar.feather_changed.connect(received.append)
        toolbar._feather_slider.set_value(0.75)
        assert received[-1] == pytest.approx(0.75)

    def test_opacity_slider_emits(self, qapp):
        toolbar = HealingToolbar()
        received = []
        toolbar.opacity_changed.connect(received.append)
        toolbar._opacity_slider.set_value(0.25)
        assert received[-1] == pytest.approx(0.25)


class TestButtons:
    def test_apply_emits(self, qapp):
        toolbar = HealingToolbar()
        received = []
        toolbar.apply_requested.connect(lambda: received.append(True))
        QTest.mouseClick(toolbar._apply_button, Qt.MouseButton.LeftButton)
        assert received == [True]

    def test_cancel_emits(self, qapp):
        toolbar = HealingToolbar()
        received = []
        toolbar.cancel_requested.connect(lambda: received.append(True))
        QTest.mouseClick(toolbar._cancel_button, Qt.MouseButton.LeftButton)
        assert received == [True]

    def test_remove_last_emits(self, qapp):
        toolbar = HealingToolbar()
        received = []
        toolbar.remove_last_requested.connect(lambda: received.append(True))
        QTest.mouseClick(toolbar._remove_last_button, Qt.MouseButton.LeftButton)
        assert received == [True]

    def test_clear_all_emits(self, qapp):
        toolbar = HealingToolbar()
        received = []
        toolbar.clear_all_requested.connect(lambda: received.append(True))
        QTest.mouseClick(toolbar._clear_all_button, Qt.MouseButton.LeftButton)
        assert received == [True]
