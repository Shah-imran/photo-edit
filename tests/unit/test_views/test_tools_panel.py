"""Unit tests for ToolsPanel, focused on the Highlights/Shadows/Whites/
Blacks sliders added alongside TonalProcessor."""

import pytest
from PyQt6.QtWidgets import QApplication

from src.views.tools_panel import ToolsPanel


@pytest.fixture(scope="module")
def qapp():
    """Create QApplication for Qt tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestToolsPanelTonalSliders:
    """Tests for the new Highlights/Shadows/Whites/Blacks controls."""

    def test_tonal_sliders_default_to_zero(self, qapp):
        panel = ToolsPanel()
        adjustments = panel.get_adjustments()
        assert adjustments['highlights'] == 0.0
        assert adjustments['shadows'] == 0.0
        assert adjustments['whites'] == 0.0
        assert adjustments['blacks'] == 0.0

    def test_get_tonal_params_returns_only_tonal_keys(self, qapp):
        panel = ToolsPanel()
        params = panel.get_tonal_params()
        assert set(params.keys()) == {'highlights', 'shadows', 'whites', 'blacks'}

    def test_moving_highlights_slider_updates_adjustments(self, qapp):
        panel = ToolsPanel()
        panel._highlights_slider.set_value(40.0)
        assert panel.get_adjustments()['highlights'] == 40.0
        assert panel.get_tonal_params()['highlights'] == 40.0

    def test_moving_shadows_slider_emits_full_adjustments_dict(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.adjustments_changed.connect(received.append)
        panel._shadows_slider.set_value(25.0)
        assert len(received) >= 1
        assert received[-1]['shadows'] == 25.0
        # The signal must carry the whole adjustment set, not just the
        # slider that moved - callers key off specific fields (e.g. the
        # controller building exposure/tonal/color sub-dicts from it).
        assert 'exposure' in received[-1]
        assert 'saturation' in received[-1]

    def test_whites_and_blacks_are_independent(self, qapp):
        panel = ToolsPanel()
        panel._whites_slider.set_value(30.0)
        panel._blacks_slider.set_value(-15.0)
        params = panel.get_tonal_params()
        assert params['whites'] == 30.0
        assert params['blacks'] == -15.0
        assert params['highlights'] == 0.0
        assert params['shadows'] == 0.0

    def test_reset_all_resets_tonal_sliders(self, qapp):
        panel = ToolsPanel()
        panel._highlights_slider.set_value(50.0)
        panel._shadows_slider.set_value(-50.0)
        panel._whites_slider.set_value(20.0)
        panel._blacks_slider.set_value(-20.0)

        panel.reset_all()

        params = panel.get_tonal_params()
        assert params == {'highlights': 0.0, 'shadows': 0.0, 'whites': 0.0, 'blacks': 0.0}

    def test_set_enabled_false_disables_tonal_sliders(self, qapp):
        panel = ToolsPanel()
        panel.set_enabled(False)
        assert panel._highlights_slider.isEnabled() is False
        assert panel._shadows_slider.isEnabled() is False
        assert panel._whites_slider.isEnabled() is False
        assert panel._blacks_slider.isEnabled() is False

    def test_set_enabled_true_enables_tonal_sliders(self, qapp):
        panel = ToolsPanel()
        panel.set_enabled(False)
        panel.set_enabled(True)
        assert panel._highlights_slider.isEnabled() is True
        assert panel._shadows_slider.isEnabled() is True
        assert panel._whites_slider.isEnabled() is True
        assert panel._blacks_slider.isEnabled() is True

    def test_exposure_and_color_params_unaffected_by_tonal_sliders(self, qapp):
        panel = ToolsPanel()
        panel._highlights_slider.set_value(60.0)
        assert panel.get_exposure_params() == {
            'exposure': 0.0, 'contrast': 0.0, 'brightness': 0.0
        }
        assert panel.get_color_params() == {'saturation': 0.0, 'vibrance': 0.0}


class TestToolsPanelToneCurve:
    """Tests for the Tone Curve section."""

    def test_curve_defaults_to_identity(self, qapp):
        panel = ToolsPanel()
        assert panel.get_curve_params() == {'points': [[0.0, 0.0], [1.0, 1.0]]}

    def test_curve_editor_change_updates_params_and_emits(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.curve_changed.connect(received.append)

        panel._curve_editor.set_points([(0.0, 0.0), (0.5, 0.7), (1.0, 1.0)])
        # set_points() alone (programmatic) must not emit; only a genuine
        # widget-driven change should.
        assert received == []

        panel._on_curve_editor_changed([[0.0, 0.0], [0.5, 0.7], [1.0, 1.0]])
        assert panel.get_curve_params() == {
            'points': [[0.0, 0.0], [0.5, 0.7], [1.0, 1.0]]
        }
        assert received[-1] == [[0.0, 0.0], [0.5, 0.7], [1.0, 1.0]]

    def test_curve_release_emits_slider_released(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.slider_released.connect(lambda: received.append(True))
        panel._curve_editor.curve_released.emit()
        assert received == [True]

    def test_reset_all_resets_curve(self, qapp):
        panel = ToolsPanel()
        panel._on_curve_editor_changed([[0.0, 0.0], [0.5, 0.7], [1.0, 1.0]])

        panel.reset_all()

        assert panel.get_curve_params() == {'points': [[0.0, 0.0], [1.0, 1.0]]}

    def test_set_adjustments_restores_curve_without_emitting(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.curve_changed.connect(received.append)

        panel.set_adjustments(
            {'tone_curve': [[0.0, 0.0], [0.4, 0.6], [1.0, 1.0]]}, emit_signal=False
        )

        assert panel.get_curve_params() == {
            'points': [[0.0, 0.0], [0.4, 0.6], [1.0, 1.0]]
        }
        assert received == []

    def test_set_adjustments_with_missing_curve_defaults_to_identity(self, qapp):
        panel = ToolsPanel()
        panel._on_curve_editor_changed([[0.0, 0.0], [0.5, 0.7], [1.0, 1.0]])

        panel.set_adjustments({'exposure': 1.0}, emit_signal=False)

        assert panel.get_curve_params() == {'points': [[0.0, 0.0], [1.0, 1.0]]}

    def test_set_enabled_false_disables_curve_editor(self, qapp):
        panel = ToolsPanel()
        panel.set_enabled(False)
        assert panel._curve_editor.isEnabled() is False

    def test_curve_change_does_not_affect_other_params(self, qapp):
        panel = ToolsPanel()
        panel._on_curve_editor_changed([[0.0, 0.0], [0.5, 0.7], [1.0, 1.0]])
        assert panel.get_exposure_params() == {
            'exposure': 0.0, 'contrast': 0.0, 'brightness': 0.0
        }
        assert panel.get_tonal_params() == {
            'highlights': 0.0, 'shadows': 0.0, 'whites': 0.0, 'blacks': 0.0
        }
        assert panel.get_color_params() == {'saturation': 0.0, 'vibrance': 0.0}


class TestToolsPanelWhiteBalance:
    """Tests for the Temperature/Tint controls."""

    def test_wb_sliders_default_to_zero(self, qapp):
        panel = ToolsPanel()
        adjustments = panel.get_adjustments()
        assert adjustments['temperature'] == 0.0
        assert adjustments['tint'] == 0.0

    def test_get_wb_params_returns_only_wb_keys(self, qapp):
        panel = ToolsPanel()
        params = panel.get_wb_params()
        assert set(params.keys()) == {'temperature', 'tint'}

    def test_moving_temperature_slider_updates_adjustments(self, qapp):
        panel = ToolsPanel()
        panel._temperature_slider.set_value(40.0)
        assert panel.get_adjustments()['temperature'] == 40.0
        assert panel.get_wb_params()['temperature'] == 40.0

    def test_moving_tint_slider_emits_full_adjustments_dict(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.adjustments_changed.connect(received.append)
        panel._tint_slider.set_value(-25.0)
        assert len(received) >= 1
        assert received[-1]['tint'] == -25.0
        assert 'exposure' in received[-1]
        assert 'temperature' in received[-1]

    def test_temperature_and_tint_are_independent(self, qapp):
        panel = ToolsPanel()
        panel._temperature_slider.set_value(30.0)
        panel._tint_slider.set_value(-15.0)
        params = panel.get_wb_params()
        assert params['temperature'] == 30.0
        assert params['tint'] == -15.0

    def test_reset_all_resets_wb_sliders(self, qapp):
        panel = ToolsPanel()
        panel._temperature_slider.set_value(50.0)
        panel._tint_slider.set_value(-50.0)

        panel.reset_all()

        assert panel.get_wb_params() == {'temperature': 0.0, 'tint': 0.0}

    def test_set_enabled_false_disables_wb_sliders(self, qapp):
        panel = ToolsPanel()
        panel.set_enabled(False)
        assert panel._temperature_slider.isEnabled() is False
        assert panel._tint_slider.isEnabled() is False

    def test_set_enabled_true_enables_wb_sliders(self, qapp):
        panel = ToolsPanel()
        panel.set_enabled(False)
        panel.set_enabled(True)
        assert panel._temperature_slider.isEnabled() is True
        assert panel._tint_slider.isEnabled() is True

    def test_wb_change_does_not_affect_other_params(self, qapp):
        panel = ToolsPanel()
        panel._temperature_slider.set_value(60.0)
        assert panel.get_exposure_params() == {
            'exposure': 0.0, 'contrast': 0.0, 'brightness': 0.0
        }
        assert panel.get_tonal_params() == {
            'highlights': 0.0, 'shadows': 0.0, 'whites': 0.0, 'blacks': 0.0
        }
        assert panel.get_color_params() == {'saturation': 0.0, 'vibrance': 0.0}

    def test_set_adjustments_restores_wb_values(self, qapp):
        panel = ToolsPanel()
        panel.set_adjustments(
            {'temperature': 25.0, 'tint': -10.0}, emit_signal=False
        )
        assert panel.get_wb_params() == {'temperature': 25.0, 'tint': -10.0}
