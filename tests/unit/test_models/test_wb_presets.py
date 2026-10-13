"""Tests for WB_PRESETS (Phase E, PDF section 13: "Temperature/Tint +
WB presets").

Cross-references every preset value against the real valid range for
the Temperature/Tint sliders, read directly from source rather than
duplicated from memory, following the same technique
``test_builtin_profiles.py`` already established.
"""

import re
from pathlib import Path

import pytest

from src.models.wb_presets import WB_PRESETS

_TOOLS_PANEL_SOURCE = Path("src/views/tools_panel.py").read_text()


def _real_ranges_from_tools_panel_source():
    """Parse the Temperature/Tint AdjustmentSlider(...) calls in
    tools_panel.py for their real min_value/max_value.

    This reads the actual source text rather than hand-duplicating the
    numbers, so the test cannot silently drift out of sync with a
    future range change in tools_panel.py.
    """
    ranges = {}
    pattern = re.compile(
        r'AdjustmentSlider\(\s*"([^"]+)",\s*min_value=(-?[\d.]+),\s*max_value=(-?[\d.]+)',
    )
    for match in pattern.finditer(_TOOLS_PANEL_SOURCE):
        label, min_value, max_value = match.groups()
        key = {"Temperature": "temperature", "Tint": "tint"}.get(label)
        if key is not None:
            ranges[key] = (float(min_value), float(max_value))
    return ranges


_REAL_RANGES = _real_ranges_from_tools_panel_source()


def test_parsed_both_temperature_and_tint_ranges():
    """Sanity check that the regex above actually matched both sliders."""
    assert set(_REAL_RANGES.keys()) == {"temperature", "tint"}


def test_exactly_seven_presets_with_expected_names():
    assert set(WB_PRESETS.keys()) == {
        "As Shot",
        "Daylight",
        "Cloudy",
        "Shade",
        "Tungsten",
        "Fluorescent",
        "Flash",
    }


def test_as_shot_is_exactly_neutral():
    assert WB_PRESETS["As Shot"] == {"temperature": 0.0, "tint": 0.0}


@pytest.mark.parametrize("preset_name", list(WB_PRESETS.keys()))
def test_preset_has_exactly_temperature_and_tint_keys(preset_name):
    assert set(WB_PRESETS[preset_name].keys()) == {"temperature", "tint"}


@pytest.mark.parametrize("preset_name", list(WB_PRESETS.keys()))
def test_preset_values_within_real_slider_range(preset_name):
    for key, value in WB_PRESETS[preset_name].items():
        assert key in _REAL_RANGES, f"No parsed range found for key {key!r}"
        min_value, max_value = _REAL_RANGES[key]
        assert min_value <= value <= max_value, (
            f"Preset {preset_name!r} key {key!r} value {value} is outside "
            f"the real valid range [{min_value}, {max_value}]"
        )


def test_tungsten_is_the_coolest_preset():
    """Tungsten light is strongly orange, so its correction should be
    the most cool/blue-shifted (most negative Temperature) of all
    presets -- a real-world relative relationship this slice must
    preserve even though the values themselves are arbitrary units."""
    tungsten_temp = WB_PRESETS["Tungsten"]["temperature"]
    for name, preset in WB_PRESETS.items():
        if name == "Tungsten":
            continue
        assert tungsten_temp < preset["temperature"]


def test_shade_is_warmer_than_daylight_which_is_warmer_than_as_shot():
    assert (
        WB_PRESETS["As Shot"]["temperature"]
        < WB_PRESETS["Daylight"]["temperature"]
        < WB_PRESETS["Cloudy"]["temperature"]
        < WB_PRESETS["Shade"]["temperature"]
    )
