"""Built-in "Profile" presets (Phase D, PDF section 10: Profiles and presets).

A profile here is a **preset-apply action**, not a persistent, separate
rendering stage. See
``docs/planning/implementation-notes/2026-10-13-profile-selector.md``
section 1 for why this is deliberately simpler than real Lightroom
Profiles (which apply as a baseline *underneath* the Develop sliders,
remembered independently of them).

Each profile is a partial adjustment-state dict: only the keys it wants
to set away from neutral. Any key a profile dict omits is defaulted to
neutral by ``ImageController.restore_adjustment_state`` /
``ToolsPanel.set_adjustments`` (both already tolerate a partial dict via
``.get(key, default)``), so a profile does not need to spell out every
key in the full adjustment-state schema.

Every value below was checked against that key's real valid range, as
defined by the ``AdjustmentSlider(...)`` construction for that key in
``src/views/tools_panel.py`` (the UI-level range; ``ImageController``
itself does not clamp). The range cited in each comment was read
directly from that file, not recalled from memory.
"""

from typing import Dict

# Key ranges, as constructed in src/views/tools_panel.py's _setup_ui
# (cited here for the value-range comments below; not re-exported/used
# programmatically -- the real, authoritative ranges live in
# tools_panel.py and are cross-checked independently by
# tests/unit/test_models/test_builtin_profiles.py):
#   exposure: -5.0..5.0          contrast: -100.0..100.0
#   brightness: -100.0..100.0    highlights: -100.0..100.0
#   shadows: -100.0..100.0       whites: -100.0..100.0
#   blacks: -100.0..100.0        temperature: -100.0..100.0
#   tint: -100.0..100.0          saturation: -100.0..100.0
#   vibrance: -100.0..100.0      texture: -100.0..100.0
#   clarity: -100.0..100.0       dehaze: -100.0..100.0
#   vignette: -100.0..100.0      grain: 0.0..100.0
#   sharpening: 0.0..100.0       luminance_nr: 0.0..100.0
#   color_nr: 0.0..100.0         remove_ca: 0.0..100.0
#   defringe: 0.0..100.0         straighten: -45.0..45.0

BUILTIN_PROFILES: Dict[str, Dict[str, float]] = {
    # Neutral baseline, analogous to Adobe Standard. An empty dict is
    # intentional: it is treated as equivalent to Reset (every key
    # defaults to neutral), which is the correct "no profile" behavior.
    "Standard": {},
    # Boosted punch, but deliberately tasteful rather than clipped-looking:
    # contrast +15 (well inside -100..100), vibrance +25 and saturation +10
    # (both well inside -100..100). Vibrance is pushed harder than
    # saturation because vibrance protects already-saturated/skin tones
    # from clipping while still reading as "vivid," whereas a large flat
    # saturation boost looks garish faster.
    "Vivid": {
        "contrast": 15.0,
        "vibrance": 25.0,
        "saturation": 10.0,
    },
    # Full desaturation (saturation at its minimum valid value, -100.0,
    # confirmed against the Saturation slider's own min_value=-100.0 in
    # tools_panel.py -- not assumed) plus a small contrast lift (+20,
    # inside -100..100) for the classic punchier black & white look.
    # No separate "monochrome mode" flag exists or is invented here --
    # this uses only the existing saturation/contrast keys.
    "Monochrome": {
        "saturation": -100.0,
        "contrast": 20.0,
    },
    # Wide scenic look: moderate clarity (+20) and vibrance (+20) for
    # local contrast and color pop in foliage/sky, a touch of dehaze
    # (+10) to cut atmospheric haze, and a touch of vignette (-15,
    # negative darkens the edges) to draw the eye inward. All four are
    # well inside their shared -100..100 range.
    "Landscape": {
        "clarity": 20.0,
        "vibrance": 20.0,
        "dehaze": 10.0,
        "vignette": -15.0,
    },
    # Flattering people look: a small warm temperature shift (+10, inside
    # -100..100) for pleasant skin tones, a touch of positive shadows
    # (+10) to open up shadow detail on faces, and a small negative
    # texture (-10) plus a small negative clarity (-5) to softly reduce
    # fine skin detail/local contrast without looking soft overall.
    "Portrait": {
        "temperature": 10.0,
        "shadows": 10.0,
        "texture": -10.0,
        "clarity": -5.0,
    },
}
