"""Unit tests for ToolsPanel, focused on the Highlights/Shadows/Whites/
Blacks sliders added alongside TonalProcessor."""

import pytest
from PyQt6.QtWidgets import QApplication

from unittest.mock import MagicMock

from src.models.builtin_profiles import BUILTIN_PROFILES
from src.models.wb_presets import WB_PRESETS
from src.processors.color_grading_processor import default_color_grading_params
from src.processors.hsl_mixer_processor import default_hsl_params
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


class TestToolsPanelHslMixer:
    """Tests for the Color Mixer section."""

    def test_hsl_defaults_to_identity(self, qapp):
        panel = ToolsPanel()
        assert panel.get_hsl_params() == default_hsl_params()

    def test_hsl_mixer_change_updates_params_and_emits(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.hsl_changed.connect(received.append)

        panel._hsl_mixer_panel._sliders["red_sat"].set_value(40.0)

        assert panel.get_hsl_params()["red_sat"] == 40.0
        assert received[-1]["red_sat"] == 40.0

    def test_hsl_release_emits_slider_released(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.slider_released.connect(lambda: received.append(True))
        panel._hsl_mixer_panel.slider_released.emit()
        assert received == [True]

    def test_reset_all_resets_hsl_mixer(self, qapp):
        panel = ToolsPanel()
        panel._hsl_mixer_panel._sliders["red_sat"].set_value(40.0)

        panel.reset_all()

        assert panel.get_hsl_params() == default_hsl_params()

    def test_set_adjustments_restores_hsl_without_emitting(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.hsl_changed.connect(received.append)

        panel.set_adjustments({'hsl': {'green_lum': 20.0}}, emit_signal=False)

        assert panel.get_hsl_params()['green_lum'] == 20.0
        assert received == []

    def test_set_adjustments_missing_hsl_defaults_to_identity(self, qapp):
        panel = ToolsPanel()
        panel._hsl_mixer_panel._sliders["red_sat"].set_value(40.0)

        panel.set_adjustments({'exposure': 1.0}, emit_signal=False)

        assert panel.get_hsl_params() == default_hsl_params()

    def test_set_enabled_false_disables_hsl_mixer(self, qapp):
        panel = ToolsPanel()
        panel.set_enabled(False)
        assert panel._hsl_mixer_panel.isEnabled() is False

    def test_hsl_change_does_not_affect_other_params(self, qapp):
        panel = ToolsPanel()
        panel._hsl_mixer_panel._sliders["red_sat"].set_value(40.0)
        assert panel.get_exposure_params() == {
            'exposure': 0.0, 'contrast': 0.0, 'brightness': 0.0
        }


class TestToolsPanelColorGrading:
    """Tests for the Color Grading section."""

    def test_color_grading_defaults_to_identity(self, qapp):
        panel = ToolsPanel()
        assert panel.get_color_grading_params() == default_color_grading_params()

    def test_color_grading_change_updates_params_and_emits(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.color_grading_changed.connect(received.append)

        panel._color_grading_panel._sliders["shadows_sat"].set_value(40.0)

        assert panel.get_color_grading_params()["shadows_sat"] == 40.0
        assert received[-1]["shadows_sat"] == 40.0

    def test_color_grading_release_emits_slider_released(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.slider_released.connect(lambda: received.append(True))
        panel._color_grading_panel.slider_released.emit()
        assert received == [True]

    def test_reset_all_resets_color_grading(self, qapp):
        panel = ToolsPanel()
        panel._color_grading_panel._sliders["shadows_sat"].set_value(40.0)

        panel.reset_all()

        assert panel.get_color_grading_params() == default_color_grading_params()

    def test_set_adjustments_restores_color_grading_without_emitting(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.color_grading_changed.connect(received.append)

        panel.set_adjustments(
            {'color_grading': {'midtones_lum': 20.0}}, emit_signal=False
        )

        assert panel.get_color_grading_params()['midtones_lum'] == 20.0
        assert received == []

    def test_set_adjustments_missing_color_grading_defaults_to_identity(self, qapp):
        panel = ToolsPanel()
        panel._color_grading_panel._sliders["shadows_sat"].set_value(40.0)

        panel.set_adjustments({'exposure': 1.0}, emit_signal=False)

        assert panel.get_color_grading_params() == default_color_grading_params()

    def test_set_enabled_false_disables_color_grading(self, qapp):
        panel = ToolsPanel()
        panel.set_enabled(False)
        assert panel._color_grading_panel.isEnabled() is False

    def test_color_grading_change_does_not_affect_other_params(self, qapp):
        panel = ToolsPanel()
        panel._color_grading_panel._sliders["shadows_sat"].set_value(40.0)
        assert panel.get_exposure_params() == {
            'exposure': 0.0, 'contrast': 0.0, 'brightness': 0.0
        }
        assert panel.get_hsl_params() == default_hsl_params()
        assert panel.get_wb_params() == {'temperature': 0.0, 'tint': 0.0}
        assert panel.get_color_params() == {'saturation': 0.0, 'vibrance': 0.0}


class TestToolsPanelTexture:
    def test_texture_range_default_and_signal(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.adjustments_changed.connect(received.append)
        assert panel._texture_slider._spin_box.minimum() == -100.0
        assert panel._texture_slider._spin_box.maximum() == 100.0
        assert panel.get_adjustments()["texture"] == 0.0
        panel._texture_slider.set_value(-35.0)
        assert received[-1]["texture"] == -35.0

    def test_texture_restore_without_emitting(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.adjustments_changed.connect(received.append)
        panel.set_adjustments({"texture": 25.0}, emit_signal=False)
        assert panel.get_adjustments()["texture"] == 25.0
        assert received == []


class TestToolsPanelClarity:
    def test_clarity_range_default_and_signal(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.adjustments_changed.connect(received.append)
        assert panel._clarity_slider._spin_box.minimum() == -100.0
        assert panel._clarity_slider._spin_box.maximum() == 100.0
        assert panel.get_adjustments()["clarity"] == 0.0
        panel._clarity_slider.set_value(-35.0)
        assert received[-1]["clarity"] == -35.0

    def test_clarity_restore_without_emitting(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.adjustments_changed.connect(received.append)
        panel.set_adjustments({"clarity": 25.0}, emit_signal=False)
        assert panel.get_adjustments()["clarity"] == 25.0
        assert received == []


class TestToolsPanelDehaze:
    def test_dehaze_range_default_and_signal(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.adjustments_changed.connect(received.append)
        assert panel._dehaze_slider._spin_box.minimum() == -100.0
        assert panel._dehaze_slider._spin_box.maximum() == 100.0
        assert panel.get_adjustments()["dehaze"] == 0.0
        panel._dehaze_slider.set_value(-35.0)
        assert received[-1]["dehaze"] == -35.0

    def test_dehaze_restore_without_emitting(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.adjustments_changed.connect(received.append)
        panel.set_adjustments({"dehaze": 25.0}, emit_signal=False)
        assert panel.get_adjustments()["dehaze"] == 25.0
        assert received == []


class TestToolsPanelVignette:
    def test_vignette_range_default_and_signal(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.adjustments_changed.connect(received.append)
        assert panel._vignette_slider._spin_box.minimum() == -100.0
        assert panel._vignette_slider._spin_box.maximum() == 100.0
        assert panel.get_adjustments()["vignette"] == 0.0
        panel._vignette_slider.set_value(-35.0)
        assert received[-1]["vignette"] == -35.0

    def test_vignette_restore_without_emitting(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.adjustments_changed.connect(received.append)
        panel.set_adjustments({"vignette": 25.0}, emit_signal=False)
        assert panel.get_adjustments()["vignette"] == 25.0
        assert received == []


class TestToolsPanelGrain:
    def test_grain_range_default_and_signal(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.adjustments_changed.connect(received.append)
        assert panel._grain_slider._spin_box.minimum() == 0.0
        assert panel._grain_slider._spin_box.maximum() == 100.0
        assert panel.get_adjustments()["grain"] == 0.0
        panel._grain_slider.set_value(35.0)
        assert received[-1]["grain"] == 35.0

    def test_grain_restore_without_emitting(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.adjustments_changed.connect(received.append)
        panel.set_adjustments({"grain": 25.0}, emit_signal=False)
        assert panel.get_adjustments()["grain"] == 25.0
        assert received == []


class TestToolsPanelSharpening:
    def test_sharpening_range_default_and_signal(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.adjustments_changed.connect(received.append)
        assert panel._sharpening_slider._spin_box.minimum() == 0.0
        assert panel._sharpening_slider._spin_box.maximum() == 100.0
        assert panel.get_adjustments()["sharpening"] == 0.0
        panel._sharpening_slider.set_value(35.0)
        assert received[-1]["sharpening"] == 35.0

    def test_sharpening_restore_without_emitting(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.adjustments_changed.connect(received.append)
        panel.set_adjustments({"sharpening": 25.0}, emit_signal=False)
        assert panel.get_adjustments()["sharpening"] == 25.0
        assert received == []

    def test_detail_section_exists_and_starts_collapsed(self, qapp):
        panel = ToolsPanel()
        assert "Detail" in panel._sections
        assert panel._sections["Detail"].is_expanded() is False

    def test_reset_detail_resets_only_sharpening(self, qapp):
        panel = ToolsPanel()
        panel._sharpening_slider.set_value(60.0)
        panel._clarity_slider.set_value(40.0)
        # Detail's reset button is now third-to-last: Optics (after
        # Detail) and Geometry (after Optics) each own a later one.
        panel._section_reset_buttons[-3].click()
        assert panel.get_adjustments()["sharpening"] == 0.0
        assert panel.get_adjustments()["clarity"] == 40.0


class TestToolsPanelLuminanceNR:
    def test_luminance_nr_range_default_and_signal(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.adjustments_changed.connect(received.append)
        assert panel._luminance_nr_slider._spin_box.minimum() == 0.0
        assert panel._luminance_nr_slider._spin_box.maximum() == 100.0
        assert panel.get_adjustments()["luminance_nr"] == 0.0
        panel._luminance_nr_slider.set_value(35.0)
        assert received[-1]["luminance_nr"] == 35.0

    def test_luminance_nr_restore_without_emitting(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.adjustments_changed.connect(received.append)
        panel.set_adjustments({"luminance_nr": 25.0}, emit_signal=False)
        assert panel.get_adjustments()["luminance_nr"] == 25.0
        assert received == []

    def test_luminance_nr_in_detail_section(self, qapp):
        panel = ToolsPanel()
        assert "Detail" in panel._sections

    def test_reset_detail_resets_both_sharpening_and_luminance_nr(self, qapp):
        panel = ToolsPanel()
        panel._sharpening_slider.set_value(60.0)
        panel._luminance_nr_slider.set_value(55.0)
        panel._clarity_slider.set_value(40.0)
        # Detail's reset button is now third-to-last: Optics (after
        # Detail) and Geometry (after Optics) each own a later one.
        panel._section_reset_buttons[-3].click()
        assert panel.get_adjustments()["sharpening"] == 0.0
        assert panel.get_adjustments()["luminance_nr"] == 0.0
        assert panel.get_adjustments()["clarity"] == 40.0


class TestToolsPanelColorNR:
    def test_color_nr_range_default_and_signal(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.adjustments_changed.connect(received.append)
        assert panel._color_nr_slider._spin_box.minimum() == 0.0
        assert panel._color_nr_slider._spin_box.maximum() == 100.0
        assert panel.get_adjustments()["color_nr"] == 0.0
        panel._color_nr_slider.set_value(35.0)
        assert received[-1]["color_nr"] == 35.0

    def test_color_nr_restore_without_emitting(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.adjustments_changed.connect(received.append)
        panel.set_adjustments({"color_nr": 25.0}, emit_signal=False)
        assert panel.get_adjustments()["color_nr"] == 25.0
        assert received == []

    def test_color_nr_in_detail_section(self, qapp):
        panel = ToolsPanel()
        assert "Detail" in panel._sections

    def test_reset_detail_resets_all_three_detail_sliders(self, qapp):
        """This completes Phase G's Detail group -- the "Reset Detail"
        button must reset Sharpening, Luminance NR, and Color NR
        together, since all three now share the single Detail section."""
        panel = ToolsPanel()
        panel._sharpening_slider.set_value(60.0)
        panel._luminance_nr_slider.set_value(55.0)
        panel._color_nr_slider.set_value(45.0)
        panel._clarity_slider.set_value(40.0)
        # Detail's reset button is now third-to-last: Optics (after
        # Detail) and Geometry (after Optics) each own a later one.
        panel._section_reset_buttons[-3].click()
        assert panel.get_adjustments()["sharpening"] == 0.0
        assert panel.get_adjustments()["luminance_nr"] == 0.0
        assert panel.get_adjustments()["color_nr"] == 0.0
        assert panel.get_adjustments()["clarity"] == 40.0


class TestToolsPanelOptics:
    """Phase H (Optics) -- Remove Chromatic Aberration.

    This mirrors the Sharpening slice's precedent for creating a brand
    new section (rather than Color NR's "add to an existing section")
    since Optics did not exist before this slice.
    """

    def test_optics_section_exists_and_starts_collapsed(self, qapp):
        panel = ToolsPanel()
        assert "Optics" in panel._sections
        assert panel._sections["Optics"].is_expanded() is False

    def test_remove_ca_range_default_and_signal(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.adjustments_changed.connect(received.append)
        assert panel._remove_ca_slider._spin_box.minimum() == 0.0
        assert panel._remove_ca_slider._spin_box.maximum() == 100.0
        assert panel.get_adjustments()["remove_ca"] == 0.0
        panel._remove_ca_slider.set_value(35.0)
        assert received[-1]["remove_ca"] == 35.0

    def test_remove_ca_restore_without_emitting(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.adjustments_changed.connect(received.append)
        panel.set_adjustments({"remove_ca": 25.0}, emit_signal=False)
        assert panel.get_adjustments()["remove_ca"] == 25.0
        assert received == []

    def test_defringe_range_default_and_signal(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.adjustments_changed.connect(received.append)
        assert panel._defringe_slider._spin_box.minimum() == 0.0
        assert panel._defringe_slider._spin_box.maximum() == 100.0
        assert panel.get_adjustments()["defringe"] == 0.0
        panel._defringe_slider.set_value(35.0)
        assert received[-1]["defringe"] == 35.0

    def test_defringe_restore_without_emitting(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.adjustments_changed.connect(received.append)
        panel.set_adjustments({"defringe": 25.0}, emit_signal=False)
        assert panel.get_adjustments()["defringe"] == 25.0
        assert received == []

    def test_reset_optics_resets_remove_ca_and_defringe_together(self, qapp):
        panel = ToolsPanel()
        panel._remove_ca_slider.set_value(60.0)
        panel._defringe_slider.set_value(70.0)
        panel._clarity_slider.set_value(40.0)
        # Optics' reset button is now second-to-last since the Geometry
        # section (added after Optics) owns the final reset button.
        optics_reset_button = panel._section_reset_buttons[-2]
        optics_reset_button.click()
        assert panel.get_adjustments()["remove_ca"] == 0.0
        assert panel.get_adjustments()["defringe"] == 0.0
        assert panel.get_adjustments()["clarity"] == 40.0


class TestToolsPanelGeometry:
    """Phase I (Geometry) -- Straighten.

    This mirrors the Optics/Remove CA slice's precedent for creating a
    brand new section (rather than extending an existing one), since
    Geometry did not exist before this slice. Only Straighten lives here
    -- the full interactive Crop tool and Upright modes are explicitly
    out of scope for this slice (see
    docs/planning/implementation-notes/2026-10-12-straighten.md section 1).
    """

    def test_geometry_section_exists_and_starts_collapsed(self, qapp):
        panel = ToolsPanel()
        assert "Geometry" in panel._sections
        assert panel._sections["Geometry"].is_expanded() is False

    def test_straighten_range_default_and_signal(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.adjustments_changed.connect(received.append)
        assert panel._straighten_slider._spin_box.minimum() == -45.0
        assert panel._straighten_slider._spin_box.maximum() == 45.0
        assert panel.get_adjustments()["straighten"] == 0.0
        panel._straighten_slider.set_value(12.5)
        assert received[-1]["straighten"] == 12.5

    def test_straighten_restore_without_emitting(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.adjustments_changed.connect(received.append)
        panel.set_adjustments({"straighten": -20.0}, emit_signal=False)
        assert panel.get_adjustments()["straighten"] == -20.0
        assert received == []

    def test_reset_geometry_resets_only_straighten(self, qapp):
        panel = ToolsPanel()
        panel._straighten_slider.set_value(30.0)
        panel._clarity_slider.set_value(40.0)
        # Geometry's reset button is now the last one, since Geometry is
        # the final section added after Optics.
        geometry_reset_button = panel._section_reset_buttons[-1]
        geometry_reset_button.click()
        assert panel.get_adjustments()["straighten"] == 0.0
        assert panel.get_adjustments()["clarity"] == 40.0


class TestToolsPanelProfileSelector:
    """Tests for the Profile combo + Apply button (Profile selector slice)."""

    def test_combo_populated_with_builtin_profile_names_in_order(self, qapp):
        panel = ToolsPanel()
        combo_items = [
            panel._profile_combo.itemText(i)
            for i in range(panel._profile_combo.count())
        ]
        assert combo_items == list(BUILTIN_PROFILES.keys())
        assert combo_items[0] == "Standard"

    def test_selecting_combo_entry_alone_does_not_emit_signal(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.profile_apply_requested.connect(received.append)
        panel._profile_combo.setCurrentText("Vivid")
        assert received == []

    def test_clicking_apply_emits_profile_apply_requested_with_selected_name(
        self, qapp
    ):
        panel = ToolsPanel()
        received = []
        panel.profile_apply_requested.connect(received.append)
        panel._profile_combo.setCurrentText("Monochrome")
        panel._profile_apply_button.click()
        assert received == ["Monochrome"]

    def test_tools_panel_does_not_itself_apply_profile_values(self, qapp):
        """ToolsPanel only emits the chosen name; it must never call into
        ImageController or apply BUILTIN_PROFILES values itself -- that is
        MainWindow's job."""
        panel = ToolsPanel()
        panel.set_adjustments = MagicMock(wraps=panel.set_adjustments)
        panel._profile_combo.setCurrentText("Landscape")
        panel._profile_apply_button.click()
        panel.set_adjustments.assert_not_called()


class TestToolsPanelWbPresets:
    """Tests for the White Balance preset combo + Apply button (WB
    presets slice, Phase E)."""

    def test_combo_populated_with_wb_preset_names_in_order(self, qapp):
        panel = ToolsPanel()
        combo_items = [
            panel._wb_preset_combo.itemText(i)
            for i in range(panel._wb_preset_combo.count())
        ]
        assert combo_items == list(WB_PRESETS.keys())
        assert combo_items[0] == "As Shot"

    def test_selecting_combo_entry_alone_does_not_change_sliders(self, qapp):
        panel = ToolsPanel()
        panel._wb_preset_combo.setCurrentText("Tungsten")
        assert panel.get_adjustments()["temperature"] == 0.0
        assert panel.get_adjustments()["tint"] == 0.0

    def test_clicking_apply_sets_sliders_to_preset_values(self, qapp):
        panel = ToolsPanel()
        panel._wb_preset_combo.setCurrentText("Tungsten")
        panel._wb_preset_apply_button.click()
        preset = WB_PRESETS["Tungsten"]
        assert panel.get_adjustments()["temperature"] == preset["temperature"]
        assert panel.get_adjustments()["tint"] == preset["tint"]

    def test_apply_emits_adjustments_changed_touching_only_wb_keys(self, qapp):
        panel = ToolsPanel()
        # Give some other sliders non-default values first, to prove
        # Apply leaves them untouched.
        panel._exposure_slider.set_value(1.5)
        panel._saturation_slider.set_value(-30.0)
        prior_adjustments = panel.get_adjustments()

        received = []
        panel.adjustments_changed.connect(received.append)
        panel._wb_preset_combo.setCurrentText("Fluorescent")
        panel._wb_preset_apply_button.click()

        assert received, "adjustments_changed was never emitted"
        final = received[-1]
        preset = WB_PRESETS["Fluorescent"]
        assert final["temperature"] == preset["temperature"]
        assert final["tint"] == preset["tint"]
        for key, value in prior_adjustments.items():
            if key in ("temperature", "tint"):
                continue
            assert final[key] == value, (
                f"Applying a WB preset changed unrelated key {key!r}"
            )

    def test_apply_emits_slider_released(self, qapp):
        panel = ToolsPanel()
        received = []
        panel.slider_released.connect(lambda: received.append(True))
        panel._wb_preset_combo.setCurrentText("Daylight")
        panel._wb_preset_apply_button.click()
        assert received == [True]

    def test_unknown_preset_name_is_a_no_op(self, qapp):
        panel = ToolsPanel()
        panel._apply_wb_preset("Not A Real Preset")
        assert panel.get_adjustments()["temperature"] == 0.0
        assert panel.get_adjustments()["tint"] == 0.0
