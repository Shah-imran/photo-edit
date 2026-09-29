"""Non-destructive adjustment layer and stack model.

This is the data model the Lightroom-parity design doc describes under
"Implementation Spec: Core Tonal & Color Adjustments" and "Data Model &
File Formats": an ``AdjustmentStack`` is an ordered list of
``AdjustmentLayer`` objects, each naming a processing step (``"basic"``,
``"curve"``, ``"wb"``, ...) plus the parameters for that step. It is the
type of object that will eventually be serialized into the catalog, copied
between images, saved as a preset, or put on the clipboard - none of which
exist yet, but all of which need this same shape underneath them.

This module intentionally has zero dependencies on Qt, PIL, or any
processor: it is pure data, so it can be constructed, serialized, and
tested without a running application.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AdjustmentLayer:
    """A single step in an adjustment stack.

    Attributes:
        type: The kind of adjustment (e.g. "basic", "curve", "wb", "hsl",
            "grading", "effects", "detail", "optics", "geometry", "local").
        enabled: Whether this layer is currently applied.
        params: Layer-specific parameters, e.g. {"exposure": 0.3,
            "contrast": 10} for a "basic" layer.
        mask: For a "local" layer, the mask that confines it to part of the
            image (see the Local Adjustments & Masking spec, Phase J - not
            implemented yet). ``None`` for a global layer. Stored as a
            plain dict for now since the mask model does not exist yet;
            once it does, this becomes a typed ``MaskRef``.
    """

    type: str
    enabled: bool = True
    params: Dict[str, Any] = field(default_factory=dict)
    mask: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize this layer to a plain-dict, JSON-compatible form."""
        data: Dict[str, Any] = {
            "type": self.type,
            "enabled": self.enabled,
            "params": dict(self.params),
        }
        if self.mask is not None:
            data["mask"] = dict(self.mask)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AdjustmentLayer":
        """Deserialize a layer from the dict shape :meth:`to_dict` produces.

        Args:
            data: A dict with at least a "type" key.

        Raises:
            KeyError: If "type" is missing.
        """
        mask = data.get("mask")
        return cls(
            type=data["type"],
            enabled=data.get("enabled", True),
            params=dict(data.get("params", {})),
            mask=dict(mask) if mask is not None else None,
        )


class AdjustmentStack:
    """An ordered, serializable collection of :class:`AdjustmentLayer`.

    This is what the Target Architecture section of the design doc calls
    the thing that "gets saved to the project file, copied between images,
    and undone/redone" - the single non-destructive representation of an
    image's edits, replacing the flat ``Dict[str, float]`` currently kept
    on ``ToolsPanel``/``ImageController``.
    """

    #: Current on-disk/serialization format version. A format change bumps
    #: this and adds a migration function, per the versioning discipline
    #: the project's own docs/planning/PRODUCT_ROADMAP.md and
    #: INCREMENTAL_WORKFLOW.md call for - never a silent shape change.
    SCHEMA_VERSION = 1

    def __init__(self, layers: Optional[List[AdjustmentLayer]] = None):
        """Initialize the stack.

        Args:
            layers: Optional initial list of layers, in application order.
                The list is copied, not aliased.
        """
        self.layers: List[AdjustmentLayer] = list(layers) if layers else []

    def add_layer(self, layer: AdjustmentLayer) -> None:
        """Append a layer to the end of the stack (applied last)."""
        self.layers.append(layer)

    def get_layer(self, layer_type: str) -> Optional[AdjustmentLayer]:
        """Find the first layer of a given type.

        Args:
            layer_type: The layer "type" to look for.

        Returns:
            The matching layer, or ``None`` if no layer of that type exists.
        """
        for layer in self.layers:
            if layer.type == layer_type:
                return layer
        return None

    def is_empty(self) -> bool:
        """Return True if the stack has no layers."""
        return len(self.layers) == 0

    def __len__(self) -> int:
        return len(self.layers)

    def __iter__(self):
        return iter(self.layers)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the whole stack, including its schema version."""
        return {
            "version": self.SCHEMA_VERSION,
            "layers": [layer.to_dict() for layer in self.layers],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AdjustmentStack":
        """Deserialize a stack from the dict shape :meth:`to_dict` produces.

        Args:
            data: A dict with "version" and "layers" keys.

        Raises:
            ValueError: If "version" does not match :data:`SCHEMA_VERSION`.
                A version bump always needs an explicit migration function
                added alongside it - there is deliberately no attempt to
                guess an older shape here.
        """
        version = data.get("version")
        if version != cls.SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported AdjustmentStack schema version: {version!r} "
                f"(expected {cls.SCHEMA_VERSION})"
            )
        layers = [AdjustmentLayer.from_dict(item) for item in data.get("layers", [])]
        return cls(layers)
