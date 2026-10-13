"""Unit tests for the MaskToolbar widget."""

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from src.views.widgets.mask_toolbar import MaskToolbar


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestSliderRangesMatchMaskProcessor:
    """Ranges confirmed directly from ImageController._MASK_ADJUSTMENT_RANGES
    (== ExposureProcessor/ColorProcessor/ClarityProcessor's own documented
    real valid ranges), not guessed.
    """

    def test_exposure_range(self, qapp):
        toolbar = MaskToolbar()
        assert toolbar._exposure_slider._min_value == pytest.approx(-5.0)
        assert toolbar._exposure_slider._max_value == pytest.approx(5.0)

    def test_contrast_range(self, qapp):
        toolbar = MaskToolbar()
        assert toolbar._contrast_slider._min_value == pytest.approx(-100.0)
        assert toolbar._contrast_slider._max_value == pytest.approx(100.0)

    def test_saturation_range(self, qapp):
        toolbar = MaskToolbar()
        assert toolbar._saturation_slider._min_value == pytest.approx(-100.0)
        assert toolbar._saturation_slider._max_value == pytest.approx(100.0)

    def test_clarity_range(self, qapp):
        toolbar = MaskToolbar()
        assert toolbar._clarity_slider._min_value == pytest.approx(-100.0)
        assert toolbar._clarity_slider._max_value == pytest.approx(100.0)


class TestSetValuesRoundTrip:
    def test_round_trip_without_emitting(self, qapp):
        toolbar = MaskToolbar()
        received_type = []
        received_invert = []
        received_adjustments = []
        toolbar.mask_type_changed.connect(received_type.append)
        toolbar.invert_changed.connect(received_invert.append)
        toolbar.adjustments_changed.connect(received_adjustments.append)

        toolbar.set_values("radial", True, 1.5, -20.0, 30.0, -10.0)

        assert toolbar.get_mask_type() == "radial"
        assert toolbar.get_invert() is True
        assert toolbar.get_adjustments() == {
            "exposure": pytest.approx(1.5),
            "contrast": pytest.approx(-20.0),
            "saturation": pytest.approx(30.0),
            "clarity": pytest.approx(-10.0),
        }
        assert received_type == []
        assert received_invert == []
        assert received_adjustments == []

    def test_set_values_linear(self, qapp):
        toolbar = MaskToolbar()
        toolbar.set_values("linear", False, 0.0, 0.0, 0.0, 0.0)
        assert toolbar.get_mask_type() == "linear"
        assert toolbar.get_invert() is False


class TestSignalsEmitOnControlChange:
    def test_type_combo_emits(self, qapp):
        toolbar = MaskToolbar()
        received = []
        toolbar.mask_type_changed.connect(received.append)
        toolbar._type_combo.setCurrentText("Radial")
        assert received == ["radial"]

    def test_invert_checkbox_emits(self, qapp):
        toolbar = MaskToolbar()
        received = []
        toolbar.invert_changed.connect(received.append)
        toolbar._invert_checkbox.setChecked(True)
        assert received == [True]

    def test_exposure_slider_emits_full_adjustments_dict(self, qapp):
        toolbar = MaskToolbar()
        received = []
        toolbar.adjustments_changed.connect(received.append)
        toolbar._exposure_slider.set_value(2.0)
        assert len(received) >= 1
        assert received[-1]["exposure"] == pytest.approx(2.0)
        assert "contrast" in received[-1]
        assert "saturation" in received[-1]
        assert "clarity" in received[-1]

    def test_contrast_slider_emits(self, qapp):
        toolbar = MaskToolbar()
        received = []
        toolbar.adjustments_changed.connect(received.append)
        toolbar._contrast_slider.set_value(50.0)
        assert received[-1]["contrast"] == pytest.approx(50.0)

    def test_saturation_slider_emits(self, qapp):
        toolbar = MaskToolbar()
        received = []
        toolbar.adjustments_changed.connect(received.append)
        toolbar._saturation_slider.set_value(-50.0)
        assert received[-1]["saturation"] == pytest.approx(-50.0)

    def test_clarity_slider_emits(self, qapp):
        toolbar = MaskToolbar()
        received = []
        toolbar.adjustments_changed.connect(received.append)
        toolbar._clarity_slider.set_value(25.0)
        assert received[-1]["clarity"] == pytest.approx(25.0)


class TestButtons:
    def test_apply_emits(self, qapp):
        toolbar = MaskToolbar()
        received = []
        toolbar.apply_requested.connect(lambda: received.append(True))
        QTest.mouseClick(toolbar._apply_button, Qt.MouseButton.LeftButton)
        assert received == [True]

    def test_cancel_emits(self, qapp):
        toolbar = MaskToolbar()
        received = []
        toolbar.cancel_requested.connect(lambda: received.append(True))
        QTest.mouseClick(toolbar._cancel_button, Qt.MouseButton.LeftButton)
        assert received == [True]

    def test_remove_emits(self, qapp):
        toolbar = MaskToolbar()
        received = []
        toolbar.remove_requested.connect(lambda: received.append(True))
        QTest.mouseClick(toolbar._remove_button, Qt.MouseButton.LeftButton)
        assert received == [True]
