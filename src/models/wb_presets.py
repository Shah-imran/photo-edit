"""Built-in white-balance presets (Phase E, PDF section 13: Color --
"Temperature/Tint + WB presets").

A WB preset here is a **preset-apply action** for exactly two existing
sliders (Temperature and Tint), not a new processing stage and not a
real white-balance algorithm. See
``docs/planning/implementation-notes/2026-10-13-wb-presets.md`` section
1 for the full scope boundary; the short version:

- **These are NOT calibrated Kelvin color temperatures.** The
  Temperature and Tint sliders in ``src/views/tools_panel.py`` are this
  app's own arbitrary UI units, each ranging ``-100.0..100.0`` (read
  directly from the ``AdjustmentSlider(...)`` construction for both
  keys, not assumed or recalled from memory). "Daylight"/"Cloudy"/
  "Shade"/"Tungsten"/"Fluorescent"/"Flash" below are representative
  *directional* placements within that arbitrary scale -- chosen so
  their relative warmth/coolness relationships mirror the real world
  (tungsten light is strongly orange, so its correction is strongly
  cool-shifted/negative; shade is bluer than daylight, so its
  correction is warmer/more positive than daylight's; fluorescent light
  commonly has a green cast, so its correction leans magenta/positive
  on Tint) -- not a physically-calibrated Kelvin-to-slider-unit
  conversion. Nobody should treat these numbers as real color
  temperatures.
- **No "Auto" entry.** A real Auto white balance requires examining the
  actual pixel data (gray-world or illuminant estimation) to compute a
  correction -- that is a new image-analysis processing feature, not a
  preset lookup, and is intentionally not built here. It remains a
  durable, separate future gap.
- **No "Custom" entry.** In Lightroom, "Custom" just means Temperature/
  Tint have been manually moved away from any preset's values -- that
  state already exists implicitly the moment a user drags either
  slider, so no new code is needed to represent it.
"""

from typing import Dict

# Temperature/Tint range, as constructed in src/views/tools_panel.py's
# _setup_ui (both -100.0..100.0). Cited here for the value-range
# comments below; the real, authoritative range lives in
# tools_panel.py and is cross-checked independently (parsed straight
# from that source file) by
# tests/unit/test_models/test_wb_presets.py.
WB_PRESETS: Dict[str, Dict[str, float]] = {
    # Neutral baseline: whatever Temperature/Tint the image already
    # has (or started at) is left untouched. Matches "As Shot" in real
    # Lightroom -- the camera's own as-recorded white balance, not a
    # forced recalculation.
    "As Shot": {"temperature": 0.0, "tint": 0.0},
    # Reference midday sunlight. Treated as the slightly-warm-of-
    # neutral baseline the other outdoor presets are measured against.
    "Daylight": {"temperature": 10.0, "tint": 0.0},
    # Overcast skies filter out some direct warm sunlight, so the
    # ambient light is bluer than daylight -- the correction needs to
    # add more warmth than Daylight's.
    "Cloudy": {"temperature": 20.0, "tint": 0.0},
    "Shade": {"temperature": 30.0, "tint": 5.0},
    # Incandescent/tungsten bulbs are strongly orange; neutralizing
    # that calls for a strong cool/blue-shifted correction -- by far
    # the most negative Temperature value here, well apart from every
    # outdoor preset above.
    "Tungsten": {"temperature": -40.0, "tint": 10.0},
    # Fluorescent tubes commonly cast green, which the Tint slider's
    # own green(-)/magenta(+) gradient corrects with a positive
    # (magenta) value -- the largest Tint value here -- alongside a
    # moderate cool Temperature shift.
    "Fluorescent": {"temperature": -20.0, "tint": 25.0},
    # Camera flash is close to daylight-balanced, often marginally
    # warmer -- a small positive Temperature nudge, no Tint shift.
    "Flash": {"temperature": 5.0, "tint": 0.0},
}
