"""Unit tests for the HslMixerPanel widget."""

import pytest
from PyQt6.QtWidgets import QApplication

from src.processors.hsl_mixer_processor import default_hsl_params
from src.views.widgets.hsl_mixer_panel import HslMixerPanel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestDefaults:
    def test_defaults_to_identity(self, qapp):
        panel = HslMixerPanel()
        assert panel.get_values() == default_hsl_params()


class TestSliderInteraction:
    def test_moving_one_slider_updates_only_that_key(self, qapp):
        panel = HslMixerPanel()
        panel._sliders["red_hue"].set_value(30.0)

        values = panel.get_values()
        assert values["red_hue"] == 30.0
        others = {k: v for k, v in values.items() if k != "red_hue"}
        assert others == {
            k: v for k, v in default_hsl_params().items() if k != "red_hue"
        }

    def test_moving_slider_emits_full_dict(self, qapp):
        panel = HslMixerPanel()
        received = []
        panel.values_changed.connect(received.append)

        panel._sliders["orange_sat"].set_value(-40.0)

        assert len(received) >= 1
        assert received[-1]["orange_sat"] == -40.0
        assert set(received[-1].keys()) == set(default_hsl_params().keys())

    def test_tabs_preserve_values_across_channels(self, qapp):
        panel = HslMixerPanel()
        panel._sliders["red_hue"].set_value(20.0)
        panel._sliders["red_sat"].set_value(30.0)
        panel._sliders["red_lum"].set_value(-10.0)

        values = panel.get_values()
        assert values["red_hue"] == 20.0
        assert values["red_sat"] == 30.0
        assert values["red_lum"] == -10.0


class TestSetValues:
    def test_set_values_does_not_emit(self, qapp):
        panel = HslMixerPanel()
        received = []
        panel.values_changed.connect(received.append)

        panel.set_values({"red_hue": 15.0})

        assert received == []
        assert panel.get_values()["red_hue"] == 15.0

    def test_set_values_defaults_missing_keys(self, qapp):
        panel = HslMixerPanel()
        panel._sliders["red_hue"].set_value(15.0)

        panel.set_values({"orange_sat": 25.0})

        values = panel.get_values()
        assert values["orange_sat"] == 25.0
        assert values["red_hue"] == 0.0

    def test_set_values_tolerates_none(self, qapp):
        panel = HslMixerPanel()
        panel._sliders["red_hue"].set_value(15.0)

        panel.set_values(None)

        assert panel.get_values() == default_hsl_params()

    def test_set_values_tolerates_malformed_entries(self, qapp):
        panel = HslMixerPanel()

        panel.set_values({"red_hue": "not a number"})

        assert panel.get_values()["red_hue"] == 0.0


class TestSliderReleased:
    def test_released_fires_on_any_band_release(self, qapp):
        panel = HslMixerPanel()
        received = []
        panel.slider_released.connect(lambda: received.append(True))

        panel._sliders["magenta_lum"].slider_released.emit(5.0)

        assert received == [True]
