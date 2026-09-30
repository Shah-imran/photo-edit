"""Unit tests for the ColorGradingPanel widget."""

import pytest
from PyQt6.QtWidgets import QApplication

from src.processors.color_grading_processor import default_color_grading_params
from src.views.widgets.color_grading_panel import ColorGradingPanel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestDefaults:
    def test_defaults_to_identity(self, qapp):
        panel = ColorGradingPanel()
        assert panel.get_values() == default_color_grading_params()


class TestSliderInteraction:
    def test_moving_one_slider_updates_only_that_key(self, qapp):
        panel = ColorGradingPanel()
        panel._sliders["shadows_hue"].set_value(30.0)

        values = panel.get_values()
        assert values["shadows_hue"] == 30.0
        others = {k: v for k, v in values.items() if k != "shadows_hue"}
        assert others == {
            k: v for k, v in default_color_grading_params().items() if k != "shadows_hue"
        }

    def test_moving_slider_emits_full_dict(self, qapp):
        panel = ColorGradingPanel()
        received = []
        panel.values_changed.connect(received.append)

        panel._sliders["midtones_sat"].set_value(40.0)

        assert len(received) >= 1
        assert received[-1]["midtones_sat"] == 40.0
        assert set(received[-1].keys()) == set(default_color_grading_params().keys())

    def test_tabs_preserve_values_across_ranges(self, qapp):
        panel = ColorGradingPanel()
        panel._sliders["shadows_hue"].set_value(20.0)
        panel._sliders["midtones_sat"].set_value(30.0)
        panel._sliders["highlights_lum"].set_value(-10.0)

        values = panel.get_values()
        assert values["shadows_hue"] == 20.0
        assert values["midtones_sat"] == 30.0
        assert values["highlights_lum"] == -10.0

    def test_global_sliders_present_and_default(self, qapp):
        panel = ColorGradingPanel()
        assert panel._sliders["blending"].get_value() == 50.0
        assert panel._sliders["balance"].get_value() == 0.0


class TestSetValues:
    def test_set_values_does_not_emit(self, qapp):
        panel = ColorGradingPanel()
        received = []
        panel.values_changed.connect(received.append)

        panel.set_values({"shadows_hue": 15.0})

        assert received == []
        assert panel.get_values()["shadows_hue"] == 15.0

    def test_set_values_defaults_missing_keys(self, qapp):
        panel = ColorGradingPanel()
        panel._sliders["shadows_hue"].set_value(15.0)

        panel.set_values({"midtones_sat": 25.0})

        values = panel.get_values()
        assert values["midtones_sat"] == 25.0
        assert values["shadows_hue"] == 0.0
        assert values["blending"] == 50.0
        assert values["balance"] == 0.0

    def test_set_values_tolerates_none(self, qapp):
        panel = ColorGradingPanel()
        panel._sliders["shadows_hue"].set_value(15.0)

        panel.set_values(None)

        assert panel.get_values() == default_color_grading_params()

    def test_set_values_tolerates_malformed_entries_falling_back_to_default(self, qapp):
        """Unlike a plain-0-default dict, a malformed entry must fall back
        to *that key's own* default (0.0 for most, but 50.0 for blending),
        not an unconditional 0.0."""
        panel = ColorGradingPanel()

        panel.set_values({"shadows_hue": "not a number", "blending": "also bad"})

        values = panel.get_values()
        assert values["shadows_hue"] == 0.0
        assert values["blending"] == 50.0


class TestSliderReleased:
    def test_released_fires_on_any_slider_release(self, qapp):
        panel = ColorGradingPanel()
        received = []
        panel.slider_released.connect(lambda: received.append(True))

        panel._sliders["highlights_lum"].slider_released.emit(5.0)

        assert received == [True]
