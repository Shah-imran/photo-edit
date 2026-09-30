"""Unit tests for AdjustmentLayer and AdjustmentStack."""

import pytest

from src.models.adjustment_layer import AdjustmentLayer, AdjustmentStack


class TestAdjustmentLayer:
    """Tests for the AdjustmentLayer dataclass."""

    def test_defaults(self):
        layer = AdjustmentLayer(type="basic")
        assert layer.type == "basic"
        assert layer.enabled is True
        assert layer.params == {}
        assert layer.mask is None

    def test_to_dict_without_mask(self):
        layer = AdjustmentLayer(type="basic", params={"exposure": 0.5})
        data = layer.to_dict()
        assert data == {"type": "basic", "enabled": True, "params": {"exposure": 0.5}}

    def test_to_dict_with_mask(self):
        mask = {"kind": "radial_gradient", "data": {"cx": 0.5, "cy": 0.5}}
        layer = AdjustmentLayer(type="local", params={"exposure": -0.5}, mask=mask)
        data = layer.to_dict()
        assert data["mask"] == mask

    def test_to_dict_copies_params_not_aliases(self):
        params = {"exposure": 1.0}
        layer = AdjustmentLayer(type="basic", params=params)
        data = layer.to_dict()
        data["params"]["exposure"] = 999
        assert layer.params["exposure"] == 1.0

    def test_from_dict_round_trip(self):
        original = AdjustmentLayer(
            type="wb", enabled=False, params={"temp": 5500, "tint": 0}
        )
        restored = AdjustmentLayer.from_dict(original.to_dict())
        assert restored == original

    def test_from_dict_with_mask_round_trip(self):
        original = AdjustmentLayer(
            type="local",
            params={"exposure": -0.3},
            mask={"kind": "brush", "data": {"strokes": []}},
        )
        restored = AdjustmentLayer.from_dict(original.to_dict())
        assert restored == original

    def test_from_dict_defaults_missing_fields(self):
        layer = AdjustmentLayer.from_dict({"type": "curve"})
        assert layer.enabled is True
        assert layer.params == {}
        assert layer.mask is None

    def test_from_dict_requires_type(self):
        with pytest.raises(KeyError):
            AdjustmentLayer.from_dict({"enabled": True})


class TestAdjustmentStack:
    """Tests for the AdjustmentStack container."""

    def test_empty_stack(self):
        stack = AdjustmentStack()
        assert len(stack) == 0
        assert stack.is_empty() is True

    def test_add_layer_preserves_order(self):
        stack = AdjustmentStack()
        stack.add_layer(AdjustmentLayer(type="wb"))
        stack.add_layer(AdjustmentLayer(type="basic"))
        stack.add_layer(AdjustmentLayer(type="curve"))
        assert [layer.type for layer in stack] == ["wb", "basic", "curve"]

    def test_init_copies_list_not_aliases(self):
        layers = [AdjustmentLayer(type="basic")]
        stack = AdjustmentStack(layers)
        layers.append(AdjustmentLayer(type="curve"))
        assert len(stack) == 1

    def test_get_layer_found(self):
        stack = AdjustmentStack([AdjustmentLayer(type="basic", params={"exposure": 1.0})])
        layer = stack.get_layer("basic")
        assert layer is not None
        assert layer.params["exposure"] == 1.0

    def test_get_layer_not_found(self):
        stack = AdjustmentStack([AdjustmentLayer(type="basic")])
        assert stack.get_layer("curve") is None

    def test_to_dict_includes_schema_version(self):
        stack = AdjustmentStack([AdjustmentLayer(type="basic")])
        data = stack.to_dict()
        assert data["version"] == AdjustmentStack.SCHEMA_VERSION
        assert len(data["layers"]) == 1

    def test_round_trip_preserves_order_and_content(self):
        stack = AdjustmentStack(
            [
                AdjustmentLayer(type="wb", params={"temp": 6500}),
                AdjustmentLayer(type="basic", params={"exposure": 0.3, "contrast": 10}),
                AdjustmentLayer(type="hsl", enabled=False, params={}),
            ]
        )
        restored = AdjustmentStack.from_dict(stack.to_dict())
        assert len(restored) == 3
        assert [layer.type for layer in restored] == ["wb", "basic", "hsl"]
        assert restored.get_layer("basic").params == {"exposure": 0.3, "contrast": 10}
        assert restored.get_layer("hsl").enabled is False

    def test_empty_stack_round_trip(self):
        stack = AdjustmentStack()
        restored = AdjustmentStack.from_dict(stack.to_dict())
        assert restored.is_empty()

    def test_from_dict_rejects_unknown_version(self):
        with pytest.raises(ValueError):
            AdjustmentStack.from_dict({"version": 999, "layers": []})

    def test_from_dict_rejects_missing_version(self):
        with pytest.raises(ValueError):
            AdjustmentStack.from_dict({"layers": []})
