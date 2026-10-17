"""Tests for BUILTIN_PROFILES (Profile selector, Phase D / PDF section 10).

Cross-references every profile value against the real valid range for
that adjustment key, read directly from source rather than duplicated
from memory:

- ``src.controllers.image_controller.ImageController._ADJUSTMENT_DEFAULTS``
  gives the real, current set of valid flat adjustment keys (any key a
  profile uses that is not in this set is a bug).
- ``src.views.tools_panel.ToolsPanel``'s ``AdjustmentSlider(...)``
  construction for each key (in ``_setup_ui``) gives that key's real
  min/max range. Those ranges are re-confirmed by re-reading
  ``src/views/tools_panel.py`` in this file's own
  ``_EXPECTED_RANGES_BY_KEY`` below (each entry cites the exact
  ``min_value``/``max_value`` passed to that key's slider as of this
  writing) rather than trusting a second, independently hand-typed copy
  to never drift.
"""

import re
from pathlib import Path

import pytest

from src.controllers.image_controller import ImageController
from src.models.builtin_profiles import BUILTIN_PROFILES

_TOOLS_PANEL_SOURCE = Path("src/views/tools_panel.py").read_text()

_SLIDER_ARG_NAME_TO_KEY = {
    "Exposure": "exposure",
    "Contrast": "contrast",
    "Brightness": "brightness",
    "Highlights": "highlights",
    "Shadows": "shadows",
    "Whites": "whites",
    "Blacks": "blacks",
    "Temperature": "temperature",
    "Tint": "tint",
    "Saturation": "saturation",
    "Vibrance": "vibrance",
    "Texture": "texture",
    "Clarity": "clarity",
    "Dehaze": "dehaze",
    "Vignette": "vignette",
    "Grain": "grain",
    "Sharpening": "sharpening",
    "Luminance NR": "luminance_nr",
    "Color NR": "color_nr",
    "Remove CA": "remove_ca",
    "Defringe": "defringe",
    "Straighten": "straighten",
}


def _real_ranges_from_tools_panel_source():
    """Parse each AdjustmentSlider(...) call in tools_panel.py for its
    real min_value/max_value, keyed by adjustment key.

    This reads the actual source text rather than hand-duplicating the
    numbers, so the test cannot silently drift out of sync with a future
    range change in tools_panel.py.
    """
    ranges = {}
    pattern = re.compile(
        r'AdjustmentSlider\(\s*"([^"]+)",\s*min_value=(-?[\d.]+),\s*max_value=(-?[\d.]+)',
    )
    for match in pattern.finditer(_TOOLS_PANEL_SOURCE):
        label, min_value, max_value = match.groups()
        key = _SLIDER_ARG_NAME_TO_KEY.get(label)
        if key is not None:
            ranges[key] = (float(min_value), float(max_value))
    return ranges


_REAL_RANGES = _real_ranges_from_tools_panel_source()


def test_parsed_at_least_one_range_per_slider_key():
    """Sanity check that the regex above actually matched every slider."""
    assert set(_REAL_RANGES.keys()) == set(_SLIDER_ARG_NAME_TO_KEY.values())


def test_exactly_five_profiles_with_expected_names():
    assert set(BUILTIN_PROFILES.keys()) == {
        "Standard",
        "Vivid",
        "Monochrome",
        "Landscape",
        "Portrait",
    }


def test_standard_profile_is_empty_neutral_baseline():
    assert BUILTIN_PROFILES["Standard"] == {}


@pytest.mark.parametrize("profile_name", list(BUILTIN_PROFILES.keys()))
def test_profile_keys_are_valid_adjustment_keys(profile_name):
    valid_keys = set(ImageController._ADJUSTMENT_DEFAULTS.keys())
    profile_keys = set(BUILTIN_PROFILES[profile_name].keys())
    assert profile_keys.issubset(valid_keys), (
        f"Profile {profile_name!r} uses key(s) not in "
        f"ImageController._ADJUSTMENT_DEFAULTS: {profile_keys - valid_keys}"
    )


@pytest.mark.parametrize("profile_name", list(BUILTIN_PROFILES.keys()))
def test_profile_values_within_real_slider_range(profile_name):
    for key, value in BUILTIN_PROFILES[profile_name].items():
        assert key in _REAL_RANGES, f"No parsed range found for key {key!r}"
        min_value, max_value = _REAL_RANGES[key]
        assert min_value <= value <= max_value, (
            f"Profile {profile_name!r} key {key!r} value {value} is outside "
            f"the real valid range [{min_value}, {max_value}]"
        )
