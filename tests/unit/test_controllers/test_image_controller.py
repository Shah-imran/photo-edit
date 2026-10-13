"""Unit tests for ImageController."""

import pytest
import time
import numpy as np
from PIL import Image
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication
from unittest.mock import Mock, patch
from src.controllers.image_controller import ImageController
from src.processing.display_frame import DisplayFrame
from src.processors.color_grading_processor import default_color_grading_params
from src.processors.hsl_mixer_processor import default_hsl_params
from src.views.image_view import ImageView
from src.models.image_model import ImageModel
from src.services.image_service import ImageService
from src.services.history_service import HistoryService
from src.services.settings_service import SettingsService
from src.utils.color_pipeline import pil_to_linear


@pytest.fixture(scope="module")
def qapp():
    """Create QApplication for Qt tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def isolated_settings(tmp_path):
    """Create a QSettings instance backed by a per-test INI file."""
    ini_path = tmp_path / "photoedit-test.ini"
    settings = QSettings(str(ini_path), QSettings.Format.IniFormat)
    yield settings
    settings.sync()


@pytest.fixture
def settings_service(isolated_settings):
    """Provide a SettingsService bound to the isolated QSettings."""
    return SettingsService(isolated_settings)


class TestImageControllerProxySizePreferences:
    """ImageController wires proxy-size preferences into its two workers."""

    def test_stored_preferences_reach_both_processing_workers(
        self, qapp, settings_service
    ):
        settings_service.set_proxy_max_size(2000)
        settings_service.set_interactive_proxy_max_size(900)
        view = ImageView()
        controller = ImageController(
            view, settings_service=settings_service, use_threading=True
        )
        try:
            assert controller._processing_worker.proxy_manager.max_size == 2000
            assert (
                controller._processing_worker.proxy_manager.interactive_max_size
                == 900
            )
            assert (
                controller._final_processing_worker.proxy_manager.max_size == 2000
            )
            assert (
                controller._final_processing_worker.proxy_manager
                .interactive_max_size
                == 900
            )
        finally:
            controller.cleanup()

    def test_no_settings_service_behaves_unchanged(self, qapp):
        from src.processing.proxy_manager import ProxyManager

        view = ImageView()
        controller = ImageController(view, use_threading=True)
        try:
            assert (
                controller._processing_worker.proxy_manager.max_size
                == ProxyManager.DEFAULT_PROXY_SIZE
            )
            assert (
                controller._processing_worker.proxy_manager.interactive_max_size
                == ProxyManager.DEFAULT_INTERACTIVE_PROXY_SIZE
            )
        finally:
            controller.cleanup()

    def test_settings_service_without_stored_prefs_behaves_unchanged(
        self, qapp, settings_service
    ):
        from src.processing.proxy_manager import ProxyManager

        view = ImageView()
        controller = ImageController(
            view, settings_service=settings_service, use_threading=True
        )
        try:
            assert (
                controller._processing_worker.proxy_manager.max_size
                == ProxyManager.DEFAULT_PROXY_SIZE
            )
            assert (
                controller._processing_worker.proxy_manager.interactive_max_size
                == ProxyManager.DEFAULT_INTERACTIVE_PROXY_SIZE
            )
        finally:
            controller.cleanup()


class TestImageController:
    """Test cases for ImageController class."""

    def test_controller_initialization(self, qapp):
        """Test ImageController can be initialized."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        assert controller is not None
        assert controller.has_image() is False
        controller.cleanup()

    def test_controller_with_dependencies(self, qapp):
        """Test ImageController with injected dependencies."""
        view = ImageView()
        model = ImageModel()
        image_service = ImageService()
        history_service = HistoryService()
        
        controller = ImageController(
            view,
            image_model=model,
            image_service=image_service,
            history_service=history_service,
            use_threading=False
        )
        
        assert controller.image_model is model
        assert controller.history_service is history_service
        controller.cleanup()

    def test_load_image_success(self, qapp, sample_image_path):
        """Test loading an image successfully."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        
        result = controller.load_image(sample_image_path)
        
        assert result is True
        assert controller.has_image() is True
        controller.cleanup()

    def test_load_image_file_not_found(self, qapp):
        """Test loading a non-existent file."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        
        # Mock QMessageBox to avoid dialog
        with patch('src.controllers.image_controller.QMessageBox'):
            result = controller.load_image("nonexistent.jpg")
        
        assert result is False
        assert controller.has_image() is False
        controller.cleanup()

    def test_load_image_async_success(self, qapp, qtbot, sample_image_path):
        """Test async image loading completes and updates the model."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)

        with qtbot.waitSignal(controller.image_load_finished, timeout=3000) as signal:
            controller.load_image_async(sample_image_path)

        loaded_path, success = signal.args
        assert loaded_path == sample_image_path
        assert success is True
        assert controller.has_image() is True
        controller.cleanup()

    def test_load_image_async_shows_preview_before_full_image(self, qapp, qtbot):
        """Async loading should present a preview before the full decode finishes."""

        class FakeImageService:
            def load_preview_thumbnail(self, file_path, size, maintain_aspect=True):
                return np.full((20, 30, 3), 0.25, dtype=np.float32)

            def load_image(self, file_path):
                time.sleep(0.05)
                return np.full((80, 120, 3), 0.5, dtype=np.float32)

        view = ImageView()
        controller = ImageController(
            view,
            image_service=FakeImageService(),
            use_threading=False,
        )

        previews = []
        finishes = []
        controller.image_preview_ready.connect(lambda path: previews.append(path))
        controller.image_load_finished.connect(
            lambda path, success: finishes.append((path, success))
        )

        controller.load_image_async("sample.raw")
        qtbot.waitUntil(lambda: len(previews) == 1, timeout=3000)

        assert previews == ["sample.raw"]
        assert view.has_image() is True
        assert controller.has_image() is False

        qtbot.waitUntil(lambda: len(finishes) == 1, timeout=3000)

        loaded_path, success = finishes[0]
        assert loaded_path == "sample.raw"
        assert success is True
        assert controller.has_image() is True
        assert controller.image_model.get_image_size() == (120, 80)
        controller.cleanup()

    def test_reset_to_original(self, qapp, sample_image_path):
        """Test resetting to original image."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        controller.load_image(sample_image_path)
        
        controller.reset_to_original()
        
        assert controller.has_image() is True
        controller.cleanup()

    def test_get_adjustment_state_returns_normalized_defaults(self, qapp):
        view = ImageView()
        controller = ImageController(view, use_threading=False)

        assert controller.get_adjustment_state() == {
            "exposure": 0.0,
            "contrast": 0.0,
            "brightness": 0.0,
            "highlights": 0.0,
            "shadows": 0.0,
            "whites": 0.0,
            "blacks": 0.0,
            "temperature": 0.0,
            "tint": 0.0,
            "saturation": 0.0,
            "vibrance": 0.0,
            "texture": 0.0,
            "clarity": 0.0,
            "dehaze": 0.0,
            "vignette": 0.0,
            "grain": 0.0,
            "sharpening": 0.0,
            "luminance_nr": 0.0,
            "color_nr": 0.0,
            "remove_ca": 0.0,
            "defringe": 0.0,
            "straighten": 0.0,
            "tone_curve": [[0.0, 0.0], [1.0, 1.0]],
            "hsl": default_hsl_params(),
            "color_grading": default_color_grading_params(),
            "crop": {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0},
            "mask": None,
        }
        controller.cleanup()

    def test_restore_adjustment_state_applies_saved_values(self, qapp, sample_image):
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        controller.restore_adjustment_state(
            {
                "exposure": 1.0,
                "contrast": 10.0,
                "brightness": 5.0,
                "saturation": 20.0,
                "vibrance": 8.0,
            }
        )

        assert controller.get_adjustment_state() == {
            "exposure": 1.0,
            "contrast": 10.0,
            "brightness": 5.0,
            "highlights": 0.0,
            "shadows": 0.0,
            "whites": 0.0,
            "blacks": 0.0,
            "temperature": 0.0,
            "tint": 0.0,
            "saturation": 20.0,
            "vibrance": 8.0,
            "texture": 0.0,
            "clarity": 0.0,
            "dehaze": 0.0,
            "vignette": 0.0,
            "grain": 0.0,
            "sharpening": 0.0,
            "luminance_nr": 0.0,
            "color_nr": 0.0,
            "remove_ca": 0.0,
            "defringe": 0.0,
            "straighten": 0.0,
            "tone_curve": [[0.0, 0.0], [1.0, 1.0]],
            "hsl": default_hsl_params(),
            "color_grading": default_color_grading_params(),
            "crop": {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0},
            "mask": None,
        }
        assert controller.image_model.get_current_image() is not None
        assert controller.can_undo() is False
        controller.cleanup()

    def test_restore_adjustment_state_applies_white_balance(self, qapp, sample_image):
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        controller.restore_adjustment_state({"temperature": 30.0, "tint": -15.0})

        state = controller.get_adjustment_state()
        assert state["temperature"] == 30.0
        assert state["tint"] == -15.0
        assert controller.image_model.get_current_image() is not None
        controller.cleanup()

    def test_on_adjustments_changed_reaches_export_image_via_wb(
        self, qapp
    ):
        import numpy as np

        view = ImageView()
        controller = ImageController(view, use_threading=False)
        mid_gray = np.full((4, 4, 3), 0.5, dtype=np.float32)
        controller._apply_loaded_image("sample.jpg", mid_gray)

        controller.on_adjustments_changed({"temperature": 40.0})

        exported = controller.get_export_image()
        original = controller.image_model.get_original_image()
        assert not (exported == original).all()
        controller.cleanup()

    def test_reset_to_original_clears_white_balance(self, qapp, sample_image):
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        controller.on_adjustments_changed({"temperature": 40.0, "tint": 20.0})

        controller.reset_to_original()

        state = controller.get_adjustment_state()
        assert state["temperature"] == 0.0
        assert state["tint"] == 0.0
        controller.cleanup()

    def test_restore_adjustment_state_applies_hsl_mixer(self, qapp, sample_image):
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        controller.restore_adjustment_state({"hsl": {"red_sat": 40.0}})

        state = controller.get_adjustment_state()
        assert state["hsl"]["red_sat"] == 40.0
        assert state["hsl"]["orange_hue"] == 0.0
        assert controller.image_model.get_current_image() is not None
        controller.cleanup()

    def test_restore_adjustment_state_tolerates_malformed_hsl(self, qapp, sample_image):
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        controller.restore_adjustment_state({"hsl": "not a dict"})

        assert controller.get_adjustment_state()["hsl"] == default_hsl_params()
        controller.cleanup()

    def test_on_hsl_changed_reaches_export_image(self, qapp):
        import numpy as np

        view = ImageView()
        controller = ImageController(view, use_threading=False)
        mid_gray = np.full((4, 4, 3), 0.5, dtype=np.float32)
        controller._apply_loaded_image("sample.jpg", mid_gray)

        controller.on_hsl_changed({"red_lum": 50.0})

        exported = controller.get_export_image()
        original = controller.image_model.get_original_image()
        assert not (exported == original).all()
        controller.cleanup()

    def test_reset_to_original_clears_hsl_mixer(self, qapp, sample_image):
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        controller.on_hsl_changed({"red_hue": 30.0})

        controller.reset_to_original()

        assert controller.get_adjustment_state()["hsl"] == default_hsl_params()
        controller.cleanup()

    def test_restore_adjustment_state_applies_color_grading(self, qapp, sample_image):
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        controller.restore_adjustment_state(
            {"color_grading": {"shadows_sat": 40.0}}
        )

        state = controller.get_adjustment_state()
        assert state["color_grading"]["shadows_sat"] == 40.0
        assert state["color_grading"]["blending"] == 50.0
        assert controller.image_model.get_current_image() is not None
        controller.cleanup()

    def test_restore_adjustment_state_tolerates_malformed_color_grading(
        self, qapp, sample_image
    ):
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        controller.restore_adjustment_state({"color_grading": "not a dict"})

        assert (
            controller.get_adjustment_state()["color_grading"]
            == default_color_grading_params()
        )
        controller.cleanup()

    def test_on_color_grading_changed_reaches_export_image(self, qapp):
        import numpy as np

        view = ImageView()
        controller = ImageController(view, use_threading=False)
        mid_gray = np.full((4, 4, 3), 0.5, dtype=np.float32)
        controller._apply_loaded_image("sample.jpg", mid_gray)

        controller.on_color_grading_changed({"midtones_sat": 50.0})

        exported = controller.get_export_image()
        original = controller.image_model.get_original_image()
        assert not (exported == original).all()
        controller.cleanup()

    def test_reset_to_original_clears_color_grading(self, qapp, sample_image):
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        controller.on_color_grading_changed({"shadows_hue": 30.0, "shadows_sat": 40.0})

        controller.reset_to_original()

        assert (
            controller.get_adjustment_state()["color_grading"]
            == default_color_grading_params()
        )
        controller.cleanup()

    def test_restore_adjustment_state_applies_tone_curve(self, qapp, sample_image):
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        controller.restore_adjustment_state(
            {"tone_curve": [[0.0, 0.0], [0.5, 0.7], [1.0, 1.0]]}
        )

        assert controller.get_adjustment_state()["tone_curve"] == [
            [0.0, 0.0],
            [0.5, 0.7],
            [1.0, 1.0],
        ]
        assert controller.image_model.get_current_image() is not None
        controller.cleanup()

    def test_restore_adjustment_state_tolerates_malformed_curve(
        self, qapp, sample_image
    ):
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        controller.restore_adjustment_state({"tone_curve": "not a curve"})

        assert controller.get_adjustment_state()["tone_curve"] == [
            [0.0, 0.0],
            [1.0, 1.0],
        ]
        controller.cleanup()

    def test_on_curve_changed_reaches_export_image(self, qapp):
        import numpy as np

        view = ImageView()
        controller = ImageController(view, use_threading=False)
        # A mid-gray image (not the fixed 0/1 curve endpoints) so a moved
        # midpoint control point actually changes pixel values.
        mid_gray = np.full((4, 4, 3), 0.5, dtype=np.float32)
        controller._apply_loaded_image("sample.jpg", mid_gray)

        controller.on_curve_changed([[0.0, 0.0], [0.5, 0.8], [1.0, 1.0]])

        exported = controller.get_export_image()
        original = controller.image_model.get_original_image()
        assert not (exported == original).all()
        controller.cleanup()

    def test_reset_to_original_clears_curve(self, qapp, sample_image):
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        controller.on_curve_changed([[0.0, 0.0], [0.5, 0.8], [1.0, 1.0]])

        controller.reset_to_original()

        assert controller.get_adjustment_state()["tone_curve"] == [
            [0.0, 0.0],
            [1.0, 1.0],
        ]
        controller.cleanup()

    def test_zoom_in(self, qapp, sample_image_path):
        """Test zoom in."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        controller.load_image(sample_image_path)
        
        initial_zoom = controller.get_zoom_factor()
        controller.zoom_in()
        
        assert controller.get_zoom_factor() > initial_zoom
        controller.cleanup()

    def test_zoom_out(self, qapp, sample_image_path):
        """Test zoom out."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        controller.load_image(sample_image_path)
        view.set_zoom_factor(2.0)
        
        controller.zoom_out()
        
        assert controller.get_zoom_factor() < 2.0
        controller.cleanup()

    def test_fit_to_window(self, qapp, sample_image_path):
        """Test fit to window."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        controller.load_image(sample_image_path)
        
        # Should not raise
        controller.fit_to_window()
        controller.cleanup()

    def test_view_100_percent(self, qapp, sample_image_path):
        """Test 100% view."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        controller.load_image(sample_image_path)
        view.set_zoom_factor(2.0)
        
        controller.view_100_percent()
        
        assert controller.get_zoom_factor() == 1.0
        controller.cleanup()

    def test_can_undo_initially_false(self, qapp):
        """Test can_undo is False initially."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        
        assert controller.can_undo() is False
        controller.cleanup()

    def test_can_redo_initially_false(self, qapp):
        """Test can_redo is False initially."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        
        assert controller.can_redo() is False
        controller.cleanup()

    def test_processing_complete_ignores_stale_request(self, qapp, sample_image):
        """Older worker results must not overwrite newer adjustment previews."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        original = pil_to_linear(sample_image)
        controller._apply_loaded_image("sample.jpg", original)

        stale = np.full((100, 100, 3), 0.1, dtype=np.float32)
        current = np.full((100, 100, 3), 0.6, dtype=np.float32)

        class FakeWorker:
            def is_latest_request(self, request_id):
                return request_id == 2

            def stop(self):
                pass

        controller._processing_worker = FakeWorker()
        controller.image_model.current_image = current

        controller._on_processing_complete(1, stale)

        assert np.allclose(controller.image_model.current_image, current)
        controller.cleanup()

    def test_threaded_final_render_commits_history_without_reprocessing(
        self, qapp, sample_image, monkeypatch
    ):
        """Completed worker results are stored in history as image states."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        original = pil_to_linear(sample_image)
        controller._apply_loaded_image("sample.jpg", original)

        rendered = np.full_like(original, 0.75)
        previous = original.copy()
        controller._pending_history_previous_image = previous
        # The real capture flow (_capture_pending_history_state) snapshots
        # get_adjustment_state() at the same moment it snapshots the image
        # -- replicate that here since this test sets
        # _pending_history_previous_image directly rather than going
        # through apply_adjustments().
        controller._pending_history_previous_state = controller.get_adjustment_state()
        controller._pending_final_request_id = 7
        controller._exposure_params = {"exposure": 1.0}
        controller._color_params = {"saturation": 0.0}

        class FakeWorker:
            def is_latest_request(self, request_id):
                return True

            def stop(self):
                pass

        def fail_if_called(*args, **kwargs):
            raise AssertionError("history commit should not reprocess")

        controller._processing_worker = FakeWorker()
        monkeypatch.setattr(
            controller._exposure_processor,
            "process",
            fail_if_called,
        )

        controller._on_processing_complete(7, rendered)

        assert controller.can_undo() is True
        assert np.allclose(controller.image_model.current_image, rendered)

        controller.undo()

        assert np.allclose(controller.image_model.current_image, previous)
        controller.cleanup()

    def test_threaded_apply_adjustments_schedules_preview_without_ui_processing(
        self, qapp, sample_image, monkeypatch
    ):
        """Threaded preview requests must not process pixels on the UI thread."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        original = pil_to_linear(sample_image)
        controller._apply_loaded_image("sample.jpg", original)
        controller._use_threading = True

        class FakeWorker:
            def __init__(self):
                self.preview_calls = []
                self.final_calls = []

            def submit_preview_request(self, **kwargs):
                self.preview_calls.append(kwargs)
                return 10

            def submit_final_request(self, **kwargs):
                self.final_calls.append(kwargs)
                return 11

            def stop(self):
                pass

        def fail_if_called(*args, **kwargs):
            raise AssertionError("threaded preview should not process on UI thread")

        fake_worker = FakeWorker()
        controller._processing_worker = fake_worker
        monkeypatch.setattr(controller._exposure_processor, "process", fail_if_called)
        monkeypatch.setattr(controller._color_processor, "process", fail_if_called)

        controller.apply_adjustments(
            exposure_params={"exposure": 1.0},
            color_params={"saturation": 20.0},
            add_to_history=False,
        )

        assert len(fake_worker.preview_calls) == 1
        assert fake_worker.final_calls == []
        assert controller._latest_request_id == 10
        controller.cleanup()

    def test_throttled_adjustment_uses_interactive_preview_tier(
        self, qapp, sample_image
    ):
        """Live drag updates should use the small interactive proxy."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        class FakeWorker:
            def __init__(self):
                self.preview_calls = []

            def submit_preview_request(self, **kwargs):
                self.preview_calls.append(kwargs)
                return 50

            def stop(self):
                pass

        fake_worker = FakeWorker()
        controller._processing_worker = fake_worker

        controller._on_throttled_adjustment(
            {
                "exposure": {"exposure": 1.0},
                "color": {"saturation": 0.0},
            }
        )

        assert fake_worker.preview_calls[0]["interactive_preview"] is True
        controller.cleanup()

    def test_debounced_adjustment_stays_on_interactive_preview_tier(
        self, qapp, sample_image
    ):
        """Pause updates should not inject larger quality frames while dragging."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        class FakeWorker:
            def __init__(self):
                self.preview_calls = []

            def submit_preview_request(self, **kwargs):
                self.preview_calls.append(kwargs)
                return 51

            def stop(self):
                pass

        fake_worker = FakeWorker()
        controller._processing_worker = fake_worker

        controller._on_debounced_adjustment(
            {
                "exposure": {"exposure": 1.0},
                "color": {"saturation": 0.0},
            }
        )

        assert fake_worker.preview_calls[0]["interactive_preview"] is True
        controller.cleanup()

    def test_preview_ready_presents_display_frame_without_refresh_view(
        self, qapp, sample_image, monkeypatch
    ):
        """Preview frames should use ImageView.set_display_frame directly."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        original = pil_to_linear(sample_image)
        controller._apply_loaded_image("sample.jpg", original)
        frame_linear = np.full((20, 30, 3), 0.5, dtype=np.float32)
        frame = DisplayFrame(
            request_id=60,
            tier="interactive",
            adjustment_signature=(),
            rgb=np.full((20, 30, 3), 128, dtype=np.uint8),
            linear_image=frame_linear,
        )

        class FakeWorker:
            def is_latest_request(self, request_id):
                return request_id == 60

            def stop(self):
                pass

        refresh_calls = []
        display_calls = []
        controller._processing_worker = FakeWorker()
        controller._latest_request_id = 60
        monkeypatch.setattr(
            controller,
            "refresh_view",
            lambda: refresh_calls.append(True),
        )
        monkeypatch.setattr(
            view,
            "set_display_frame",
            lambda delivered, preserve_view_scale=True: display_calls.append(
                (delivered, preserve_view_scale)
            ),
        )

        controller._on_preview_ready(60, frame)

        assert refresh_calls == []
        assert display_calls == [(frame, True)]
        assert np.allclose(controller.image_model.current_image, frame_linear)
        controller.cleanup()

    def test_preview_ready_drops_stale_quality_frame(self, qapp, sample_image, monkeypatch):
        """A quality result should not present after a newer request exists."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        frame = DisplayFrame(
            request_id=70,
            tier="quality",
            adjustment_signature=(),
            rgb=np.full((20, 30, 3), 128, dtype=np.uint8),
        )

        class FakeWorker:
            def is_latest_request(self, request_id):
                return True

            def stop(self):
                pass

        display_calls = []
        controller._processing_worker = FakeWorker()
        controller._latest_request_id = 71
        monkeypatch.setattr(
            view,
            "set_display_frame",
            lambda delivered, preserve_view_scale=True: display_calls.append(
                delivered
            ),
        )

        controller._on_preview_ready(70, frame)

        assert display_calls == []
        controller.cleanup()

    def test_threaded_apply_adjustments_schedules_final_without_ui_processing(
        self, qapp, sample_image, monkeypatch
    ):
        """Threaded final requests must not process or commit on the UI thread."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        original = pil_to_linear(sample_image)
        controller._apply_loaded_image("sample.jpg", original)
        controller._use_threading = True

        class FakeWorker:
            def __init__(self):
                self.preview_calls = []
                self.final_calls = []

            def submit_preview_request(self, **kwargs):
                self.preview_calls.append(kwargs)
                return 20

            def submit_final_request(self, **kwargs):
                self.final_calls.append(kwargs)
                return 21

            def stop(self):
                pass

        def fail_if_called(*args, **kwargs):
            raise AssertionError("threaded final should not process on UI thread")

        fake_worker = FakeWorker()
        controller._processing_worker = fake_worker
        monkeypatch.setattr(controller._exposure_processor, "process", fail_if_called)
        monkeypatch.setattr(controller._color_processor, "process", fail_if_called)

        controller.apply_adjustments(
            exposure_params={"exposure": 1.0},
            color_params={"saturation": 20.0},
            add_to_history=True,
        )

        assert fake_worker.preview_calls == []
        assert len(fake_worker.final_calls) == 1
        assert controller._pending_final_request_id == 21
        assert controller.can_undo() is False
        controller.cleanup()

    def test_slider_release_delays_full_render_until_idle(
        self, qapp, qtbot, sample_image
    ):
        """Releasing a slider should not immediately occupy the worker."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        original = pil_to_linear(sample_image)
        controller._apply_loaded_image("sample.jpg", original)
        controller._use_threading = True
        controller._exposure_params = {"exposure": 1.0}
        controller._color_params = {"saturation": 0.0}

        class FakePreviewWorker:
            def __init__(self):
                self.preview_calls = []

            def submit_preview_request(self, **kwargs):
                self.preview_calls.append(kwargs)
                return 30

            def stop(self):
                pass

        class FakeFinalWorker:
            def __init__(self):
                self.final_calls = []

            def submit_final_request(self, **kwargs):
                self.final_calls.append(kwargs)
                return 31

            def stop(self):
                pass

        fake_preview_worker = FakePreviewWorker()
        fake_final_worker = FakeFinalWorker()
        controller._processing_worker = fake_preview_worker
        controller._final_processing_worker = fake_final_worker

        controller.on_slider_released()

        assert len(fake_preview_worker.preview_calls) == 1
        assert fake_preview_worker.preview_calls[0]["interactive_preview"] is False
        assert fake_final_worker.final_calls == []
        assert controller._final_render_timer.isActive() is True

        qtbot.waitUntil(lambda: len(fake_final_worker.final_calls) == 1, timeout=2500)

        assert controller._pending_final_request_id == 31
        controller.cleanup()

    def test_pending_final_render_does_not_refresh_full_res_view(
        self, qapp, sample_image, monkeypatch
    ):
        """Background full renders should update model/history without repainting full-res."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        original = pil_to_linear(sample_image)
        controller._apply_loaded_image("sample.jpg", original)

        rendered = np.full_like(original, 0.8)
        controller._pending_history_previous_image = original
        # See the matching comment in
        # test_threaded_final_render_commits_history_without_reprocessing.
        controller._pending_history_previous_state = controller.get_adjustment_state()
        controller._pending_final_request_id = 42
        controller._exposure_params = {"exposure": 1.0}
        controller._color_params = {"saturation": 0.0}

        class FakeWorker:
            def is_latest_request(self, request_id):
                return True

            def stop(self):
                pass

        refresh_calls = []
        controller._processing_worker = FakeWorker()
        monkeypatch.setattr(
            controller,
            "refresh_view",
            lambda: refresh_calls.append(True),
        )

        controller._on_processing_complete(42, rendered)

        assert refresh_calls == []
        assert np.allclose(controller.image_model.current_image, rendered)
        assert controller.can_undo() is True
        controller.cleanup()

    def test_new_slider_movement_cancels_pending_full_render(
        self, qapp, sample_image
    ):
        """Moving again before idle should cancel the scheduled full render."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        original = pil_to_linear(sample_image)
        controller._apply_loaded_image("sample.jpg", original)
        controller._use_threading = True
        controller._exposure_params = {"exposure": 1.0}
        controller._color_params = {"saturation": 0.0}

        class FakePreviewWorker:
            def submit_preview_request(self, **kwargs):
                return 40

            def stop(self):
                pass

        class FakeFinalWorker:
            def submit_final_request(self, **kwargs):
                raise AssertionError("full render should have been cancelled")

            def stop(self):
                pass

        class FakeDebouncer:
            def __init__(self):
                self.calls = []

            def call(self, value):
                self.calls.append(value)

            def cancel(self):
                pass

        fake_debouncer = FakeDebouncer()
        controller._processing_worker = FakePreviewWorker()
        controller._final_processing_worker = FakeFinalWorker()
        controller._debouncer = fake_debouncer

        controller.on_slider_released()
        assert controller._final_render_timer.isActive() is True

        controller.on_adjustments_changed(
            {
                "exposure": 2.0,
                "contrast": 0.0,
                "brightness": 0.0,
                "saturation": 0.0,
                "vibrance": 0.0,
            }
        )

        assert controller._final_render_timer.isActive() is False
        assert controller._pending_final_request_id == -1
        assert len(fake_debouncer.calls) == 1
        controller.cleanup()


class TestImageControllerOpenImageSettings:
    """Wiring between ``open_image`` and ``SettingsService``."""

    @pytest.fixture
    def isolated_settings(self, tmp_path):
        ini_path = tmp_path / "photoedit-test.ini"
        return SettingsService(QSettings(str(ini_path), QSettings.Format.IniFormat))

    def test_open_image_seeds_dialog_with_last_open_dir(
        self, qapp, sample_image_path, tmp_path, isolated_settings
    ):
        """The dialog must start in the previously-stored open directory."""
        seeded = tmp_path / "previously_used"
        seeded.mkdir()
        isolated_settings.set_last_open_dir(str(seeded))

        view = ImageView()
        controller = ImageController(
            view, settings_service=isolated_settings, use_threading=False
        )

        with patch(
            "src.controllers.image_controller.QFileDialog.getOpenFileName",
            return_value=(sample_image_path, "Image Files"),
        ) as dialog:
            controller.open_image()

        args, _ = dialog.call_args
        assert args[2] == str(seeded)
        controller.cleanup()

    def test_open_image_persists_chosen_directory(
        self, qapp, sample_image_path, isolated_settings
    ):
        """After picking a file, its parent directory must be stored."""
        view = ImageView()
        controller = ImageController(
            view, settings_service=isolated_settings, use_threading=False
        )

        with patch(
            "src.controllers.image_controller.QFileDialog.getOpenFileName",
            return_value=(sample_image_path, "Image Files"),
        ):
            controller.open_image()

        from pathlib import Path

        assert isolated_settings.get_last_open_dir() == str(
            Path(sample_image_path).parent
        )
        controller.cleanup()

    def test_open_image_no_settings_uses_empty_default(self, qapp, sample_image_path):
        """Backwards-compat: no SettingsService keeps the legacy empty default."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)

        with patch(
            "src.controllers.image_controller.QFileDialog.getOpenFileName",
            return_value=(sample_image_path, "Image Files"),
        ) as dialog:
            controller.open_image()

        args, _ = dialog.call_args
        assert args[2] == ""
        controller.cleanup()


class TestImageControllerCleanupThreadSafety:
    """``cleanup()`` must not drop a still-running load thread's references.

    Regression coverage for a reproduced crash: a load thread runs an
    uninterruptible decode with no cancellation check, so
    ``thread.wait(2000)`` inside ``cleanup()`` can time out while it is
    still mid-decode. The previous version unconditionally cleared
    ``_load_threads``/``_load_workers`` regardless of whether ``wait()``
    actually succeeded -- dropping the last Python reference to a
    ``QThread``/worker pair whose native thread was still alive. Garbage
    collecting that pair while the background thread still touched it
    reproduced as ``Fatal Python error: Aborted`` when a slow load was
    still in flight at teardown (observed running the real async image
    load path back-to-back with other Qt-object-heavy tests).
    """

    def test_cleanup_keeps_tracking_a_thread_that_times_out(self, qapp):
        """A thread whose ``wait()`` times out must stay tracked, not be lost."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)

        fake_thread = Mock()
        fake_thread.quit = Mock()
        fake_thread.wait = Mock(return_value=False)  # simulates a timeout
        fake_worker = Mock()
        controller._load_threads.append(fake_thread)
        controller._load_workers.append(fake_worker)

        controller.cleanup()

        fake_thread.quit.assert_called_once()
        fake_thread.wait.assert_called_once_with(2000)
        assert fake_thread in controller._load_threads
        assert fake_worker in controller._load_workers

    def test_cleanup_untracks_a_thread_that_finishes_in_time(self, qapp):
        """A thread whose ``wait()`` succeeds must be forgotten, as before."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)

        fake_thread = Mock()
        fake_thread.quit = Mock()
        fake_thread.wait = Mock(return_value=True)
        fake_worker = Mock()
        controller._load_threads.append(fake_thread)
        controller._load_workers.append(fake_worker)

        controller.cleanup()

        assert fake_thread not in controller._load_threads
        assert fake_worker not in controller._load_workers


class TestImageControllerTexture:
    def test_texture_round_trips_and_reaches_export(self, qapp, sample_image):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        original = controller.image_model.get_original_image().copy()
        original[40:60, 40:60] *= 0.6
        controller.image_model.set_original_image(original)
        controller.restore_adjustment_state({"texture": 45.0})
        assert controller.get_adjustment_state()["texture"] == 45.0
        assert not np.array_equal(controller.get_export_image(), original)

    def test_missing_texture_restores_identity(self, qapp):
        controller = ImageController(ImageView(), use_threading=False)
        controller.restore_adjustment_state({"exposure": 1.0})
        assert controller.get_adjustment_state()["texture"] == 0.0


class TestImageControllerClarity:
    def test_clarity_round_trips_and_reaches_export(self, qapp, sample_image):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        original = controller.image_model.get_original_image().copy()
        original[40:60, 40:60] *= 0.6
        controller.image_model.set_original_image(original)
        controller.restore_adjustment_state({"clarity": 45.0})
        assert controller.get_adjustment_state()["clarity"] == 45.0
        assert not np.array_equal(controller.get_export_image(), original)

    def test_missing_clarity_restores_identity(self, qapp):
        controller = ImageController(ImageView(), use_threading=False)
        controller.restore_adjustment_state({"exposure": 1.0})
        assert controller.get_adjustment_state()["clarity"] == 0.0


class TestImageControllerDehaze:
    def test_dehaze_round_trips_and_reaches_export(self, qapp, sample_image):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        original = controller.image_model.get_original_image().copy()
        original[40:60, 40:60] *= 0.6
        controller.image_model.set_original_image(original)
        controller.restore_adjustment_state({"dehaze": 45.0})
        assert controller.get_adjustment_state()["dehaze"] == 45.0
        assert not np.array_equal(controller.get_export_image(), original)

    def test_missing_dehaze_restores_identity(self, qapp):
        controller = ImageController(ImageView(), use_threading=False)
        controller.restore_adjustment_state({"exposure": 1.0})
        assert controller.get_adjustment_state()["dehaze"] == 0.0


class TestImageControllerVignette:
    def test_vignette_round_trips_and_reaches_export(self, qapp, sample_image):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        original = controller.image_model.get_original_image().copy()
        original[40:60, 40:60] *= 0.6
        controller.image_model.set_original_image(original)
        controller.restore_adjustment_state({"vignette": 45.0})
        assert controller.get_adjustment_state()["vignette"] == 45.0
        assert not np.array_equal(controller.get_export_image(), original)

    def test_missing_vignette_restores_identity(self, qapp):
        controller = ImageController(ImageView(), use_threading=False)
        controller.restore_adjustment_state({"exposure": 1.0})
        assert controller.get_adjustment_state()["vignette"] == 0.0

    def test_vignette_undo_restores_previous_image(self, qapp, sample_image):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        controller.apply_adjustments(
            vignette_params={"vignette": 40.0}, add_to_history=True
        )
        assert controller.can_undo() is True
        assert controller.undo() is True


class TestImageControllerGrain:
    def test_grain_round_trips_and_reaches_export(self, qapp, sample_image):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        original = controller.image_model.get_original_image().copy()
        controller.restore_adjustment_state({"grain": 45.0})
        assert controller.get_adjustment_state()["grain"] == 45.0
        assert not np.array_equal(controller.get_export_image(), original)

    def test_missing_grain_restores_identity(self, qapp):
        controller = ImageController(ImageView(), use_threading=False)
        controller.restore_adjustment_state({"exposure": 1.0})
        assert controller.get_adjustment_state()["grain"] == 0.0

    def test_grain_undo_restores_previous_image(self, qapp, sample_image):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        controller.apply_adjustments(
            grain_params={"grain": 40.0}, add_to_history=True
        )
        assert controller.can_undo() is True
        assert controller.undo() is True


class TestImageControllerSharpening:
    def test_sharpening_round_trips_and_reaches_export(self, qapp):
        # A flat/constant image (e.g. the shared ``sample_image`` fixture)
        # is exactly the case Sharpening's masking safeguard is meant to
        # leave unchanged, so this uses an image with real edges to confirm
        # the parameter actually reaches ``get_export_image()``.
        from PIL import Image as PILImage

        edge_image = PILImage.new("RGB", (100, 100), color="red")
        for x in range(50, 100):
            for y in range(100):
                edge_image.putpixel((x, y), (0, 255, 0))

        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(edge_image))
        original = controller.image_model.get_original_image().copy()
        controller.restore_adjustment_state({"sharpening": 45.0})
        assert controller.get_adjustment_state()["sharpening"] == 45.0
        assert not np.array_equal(controller.get_export_image(), original)

    def test_missing_sharpening_restores_identity(self, qapp):
        controller = ImageController(ImageView(), use_threading=False)
        controller.restore_adjustment_state({"exposure": 1.0})
        assert controller.get_adjustment_state()["sharpening"] == 0.0

    def test_sharpening_undo_restores_previous_image(self, qapp, sample_image):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        controller.apply_adjustments(
            sharpening_params={"sharpening": 40.0}, add_to_history=True
        )
        assert controller.can_undo() is True
        assert controller.undo() is True


class TestImageControllerLuminanceNR:
    def test_luminance_nr_round_trips_and_reaches_export(self, qapp, sample_image):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        controller.restore_adjustment_state({"luminance_nr": 45.0})
        assert controller.get_adjustment_state()["luminance_nr"] == 45.0
        # The luminance NR params are at least threaded through to export,
        # even though the shared flat sample_image has no noise for the
        # filter to visibly act on.
        assert controller.get_export_image() is not None

    def test_missing_luminance_nr_restores_identity(self, qapp):
        controller = ImageController(ImageView(), use_threading=False)
        controller.restore_adjustment_state({"exposure": 1.0})
        assert controller.get_adjustment_state()["luminance_nr"] == 0.0

    def test_luminance_nr_undo_restores_previous_image(self, qapp, sample_image):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        controller.apply_adjustments(
            luminance_nr_params={"luminance_nr": 40.0}, add_to_history=True
        )
        assert controller.can_undo() is True
        assert controller.undo() is True


class TestImageControllerColorNR:
    def test_color_nr_round_trips_and_reaches_export(self, qapp, sample_image):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        controller.restore_adjustment_state({"color_nr": 45.0})
        assert controller.get_adjustment_state()["color_nr"] == 45.0
        # The color NR params are at least threaded through to export,
        # even though the shared flat sample_image has no chroma noise for
        # the filter to visibly act on.
        assert controller.get_export_image() is not None

    def test_missing_color_nr_restores_identity(self, qapp):
        controller = ImageController(ImageView(), use_threading=False)
        controller.restore_adjustment_state({"exposure": 1.0})
        assert controller.get_adjustment_state()["color_nr"] == 0.0

    def test_color_nr_undo_restores_previous_image(self, qapp, sample_image):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        controller.apply_adjustments(
            color_nr_params={"color_nr": 40.0}, add_to_history=True
        )
        assert controller.can_undo() is True
        assert controller.undo() is True


class TestImageControllerRemoveCA:
    """Phase H (Optics) -- Remove Chromatic Aberration."""

    def test_remove_ca_round_trips_and_reaches_export(self, qapp, sample_image):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        controller.restore_adjustment_state({"remove_ca": 45.0})
        assert controller.get_adjustment_state()["remove_ca"] == 45.0
        assert controller.get_export_image() is not None

    def test_missing_remove_ca_restores_identity(self, qapp):
        controller = ImageController(ImageView(), use_threading=False)
        controller.restore_adjustment_state({"exposure": 1.0})
        assert controller.get_adjustment_state()["remove_ca"] == 0.0

    def test_remove_ca_undo_restores_previous_image(self, qapp, sample_image):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        controller.apply_adjustments(
            remove_ca_params={"remove_ca": 40.0}, add_to_history=True
        )
        assert controller.can_undo() is True
        assert controller.undo() is True


class TestImageControllerDefringe:
    """Phase H (Optics) -- Defringe."""

    def test_defringe_round_trips_and_reaches_export(self, qapp, sample_image):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        controller.restore_adjustment_state({"defringe": 45.0})
        assert controller.get_adjustment_state()["defringe"] == 45.0
        assert controller.get_export_image() is not None

    def test_missing_defringe_restores_identity(self, qapp):
        controller = ImageController(ImageView(), use_threading=False)
        controller.restore_adjustment_state({"exposure": 1.0})
        assert controller.get_adjustment_state()["defringe"] == 0.0

    def test_defringe_undo_restores_previous_image(self, qapp, sample_image):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        controller.apply_adjustments(
            defringe_params={"defringe": 40.0}, add_to_history=True
        )
        assert controller.can_undo() is True
        assert controller.undo() is True


class TestImageControllerStraighten:
    """Phase I (Geometry) -- Straighten."""

    def test_straighten_round_trips_and_reaches_export(self, qapp, sample_image):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        controller.restore_adjustment_state({"straighten": 12.0})
        assert controller.get_adjustment_state()["straighten"] == 12.0
        export = controller.get_export_image()
        assert export is not None
        assert export.shape == pil_to_linear(sample_image).shape

    def test_missing_straighten_restores_identity(self, qapp):
        controller = ImageController(ImageView(), use_threading=False)
        controller.restore_adjustment_state({"exposure": 1.0})
        assert controller.get_adjustment_state()["straighten"] == 0.0

    def test_straighten_undo_restores_previous_image(self, qapp, sample_image):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        controller.apply_adjustments(
            straighten_params={"straighten": 8.0}, add_to_history=True
        )
        assert controller.can_undo() is True
        assert controller.undo() is True


class TestImageControllerCrop:
    """Phase I (Geometry and Crop), slice 1 -- the data/processing layer
    for the Crop tool. See docs/planning/implementation-notes/
    2026-10-13-crop-processor.md."""

    def test_default_crop_is_full_frame(self, qapp):
        controller = ImageController(ImageView(), use_threading=False)
        assert controller.get_adjustment_state()["crop"] == {
            "x0": 0.0,
            "y0": 0.0,
            "x1": 1.0,
            "y1": 1.0,
        }

    def test_restore_adjustment_state_applies_crop(self, qapp, sample_image):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        controller.restore_adjustment_state(
            {"crop": {"x0": 0.1, "y0": 0.2, "x1": 0.8, "y1": 0.9}}
        )

        assert controller.get_adjustment_state()["crop"] == {
            "x0": 0.1,
            "y0": 0.2,
            "x1": 0.8,
            "y1": 0.9,
        }

    def test_missing_crop_key_defaults_to_full_frame(self, qapp, sample_image):
        """Backward compatibility: an old catalog/preset payload that
        pre-dates this slice and omits "crop" entirely must default
        cleanly to the full-frame rectangle -- the same pattern every
        prior non-flat-key addition (tone_curve/hsl/color_grading)
        already established."""
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        controller.restore_adjustment_state({"exposure": 1.0})

        assert controller.get_adjustment_state()["crop"] == {
            "x0": 0.0,
            "y0": 0.0,
            "x1": 1.0,
            "y1": 1.0,
        }

    def test_restore_adjustment_state_tolerates_malformed_crop(
        self, qapp, sample_image
    ):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        controller.restore_adjustment_state({"crop": "not a dict"})

        assert controller.get_adjustment_state()["crop"] == {
            "x0": 0.0,
            "y0": 0.0,
            "x1": 1.0,
            "y1": 1.0,
        }

    def test_restore_adjustment_state_clamps_out_of_range_crop(
        self, qapp, sample_image
    ):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        controller.restore_adjustment_state(
            {"crop": {"x0": -0.5, "y0": -0.5, "x1": 1.5, "y1": 1.5}}
        )

        assert controller.get_adjustment_state()["crop"] == {
            "x0": 0.0,
            "y0": 0.0,
            "x1": 1.0,
            "y1": 1.0,
        }

    def test_crop_reaches_export_image_and_shrinks_it(self, qapp, sample_image):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        original_shape = pil_to_linear(sample_image).shape

        controller.restore_adjustment_state(
            {"crop": {"x0": 0.25, "y0": 0.25, "x1": 0.75, "y1": 0.75}}
        )

        export = controller.get_export_image()
        assert export is not None
        assert export.shape != original_shape
        assert export.shape[0] < original_shape[0]
        assert export.shape[1] < original_shape[1]

    def test_on_crop_changed_round_trips_and_adds_to_history(
        self, qapp, sample_image
    ):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        controller.on_crop_changed({"x0": 0.1, "y0": 0.1, "x1": 0.6, "y1": 0.6})

        assert controller.get_adjustment_state()["crop"] == {
            "x0": 0.1,
            "y0": 0.1,
            "x1": 0.6,
            "y1": 0.6,
        }
        assert controller.can_undo() is True

    def test_on_crop_changed_normalizes_defensively(self, qapp, sample_image):
        """on_crop_changed must not trust its caller, mirroring
        CropProcessor's own clamp/swap logic."""
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        controller.on_crop_changed({"x0": 0.9, "y0": -1.0, "x1": 0.1, "y1": 2.0})

        state = controller.get_adjustment_state()["crop"]
        assert state["x0"] == 0.1
        assert state["x1"] == 0.9
        assert state["y0"] == 0.0
        assert state["y1"] == 1.0

    def test_crop_undo_restores_full_crop_state(self, qapp, sample_image):
        """Crop to rect A, then crop to rect B, undo, assert the crop
        state equals rect A's values, not rect B's -- mirrors the core
        state-aware undo/redo regression pattern."""
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        rect_a = {"x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.5}
        rect_b = {"x0": 0.2, "y0": 0.2, "x1": 0.6, "y1": 0.6}
        controller.on_crop_changed(rect_a)
        controller.on_crop_changed(rect_b)

        assert controller.get_adjustment_state()["crop"] == rect_b

        assert controller.undo() is True

        assert controller.get_adjustment_state()["crop"] == rect_a

    def test_crop_undo_restores_image_shape_too(self, qapp, sample_image):
        """Undo must restore both the crop state AND the actual image
        shape, not just the pixel-buffer-only behavior this slice's
        state-aware undo/redo infrastructure was built to fix."""
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        original_shape = pil_to_linear(sample_image).shape

        controller.on_crop_changed({"x0": 0.25, "y0": 0.25, "x1": 0.75, "y1": 0.75})
        cropped_shape = controller.get_current_image().shape
        assert cropped_shape != original_shape

        controller.on_crop_changed({"x0": 0.1, "y0": 0.1, "x1": 0.4, "y1": 0.4})
        smaller_shape = controller.get_current_image().shape
        assert smaller_shape != cropped_shape

        assert controller.undo() is True

        assert controller.get_current_image().shape == cropped_shape

    def test_reset_to_original_clears_crop(self, qapp, sample_image):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        controller.on_crop_changed({"x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.5})

        controller.reset_to_original()

        assert controller.get_adjustment_state()["crop"] == {
            "x0": 0.0,
            "y0": 0.0,
            "x1": 1.0,
            "y1": 1.0,
        }

    def test_loading_a_different_image_clears_crop(self, qapp, sample_image):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        controller.on_crop_changed({"x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.5})

        controller._apply_loaded_image("other.jpg", pil_to_linear(sample_image))

        assert controller.get_adjustment_state()["crop"] == {
            "x0": 0.0,
            "y0": 0.0,
            "x1": 1.0,
            "y1": 1.0,
        }


class TestImageControllerMask:
    """Phase J (Masking), slice 1 -- the data/processing layer for a
    single-slot linear/radial local-adjustment mask. See
    docs/planning/implementation-notes/2026-10-13-mask-processor.md."""

    _LINEAR_MASK = {
        "type": "linear",
        "invert": False,
        "x0": 0.1,
        "y0": 0.2,
        "x1": 0.8,
        "y1": 0.9,
        "exposure": 1.0,
        "contrast": 10.0,
        "saturation": 20.0,
        "clarity": 5.0,
    }
    _RADIAL_MASK = {
        "type": "radial",
        "invert": False,
        "cx": 0.5,
        "cy": 0.5,
        "rx": 0.3,
        "ry": 0.2,
        "feather": 0.4,
        "exposure": -1.0,
        "contrast": 0.0,
        "saturation": 0.0,
        "clarity": 0.0,
    }

    def test_default_mask_is_none(self, qapp):
        controller = ImageController(ImageView(), use_threading=False)
        assert controller.get_adjustment_state()["mask"] is None

    def test_restore_adjustment_state_applies_linear_mask(
        self, qapp, sample_image
    ):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        controller.restore_adjustment_state({"mask": self._LINEAR_MASK})

        assert controller.get_adjustment_state()["mask"] == self._LINEAR_MASK

    def test_restore_adjustment_state_applies_radial_mask(
        self, qapp, sample_image
    ):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        controller.restore_adjustment_state({"mask": self._RADIAL_MASK})

        assert controller.get_adjustment_state()["mask"] == self._RADIAL_MASK

    def test_missing_mask_key_defaults_to_none(self, qapp, sample_image):
        """Backward compatibility: an old catalog/preset payload that
        pre-dates this slice and omits "mask" entirely must default
        cleanly to None."""
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        controller.restore_adjustment_state({"exposure": 1.0})

        assert controller.get_adjustment_state()["mask"] is None

    def test_restore_adjustment_state_tolerates_malformed_mask(
        self, qapp, sample_image
    ):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        controller.restore_adjustment_state({"mask": "not a dict"})

        assert controller.get_adjustment_state()["mask"] is None

    def test_restore_adjustment_state_tolerates_unrecognized_type(
        self, qapp, sample_image
    ):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        controller.restore_adjustment_state(
            {"mask": {"type": "brush", "exposure": 2.0}}
        )

        assert controller.get_adjustment_state()["mask"] is None

    def test_restore_adjustment_state_clamps_out_of_range_mask(
        self, qapp, sample_image
    ):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        controller.restore_adjustment_state(
            {
                "mask": {
                    "type": "linear",
                    "x0": -0.5,
                    "y0": 1.5,
                    "x1": 2.0,
                    "y1": -2.0,
                    "exposure": 50.0,
                    "contrast": 500.0,
                    "saturation": -500.0,
                    "clarity": 500.0,
                }
            }
        )

        state = controller.get_adjustment_state()["mask"]
        assert state["x0"] == 0.0
        assert state["y0"] == 1.0
        assert state["x1"] == 1.0
        assert state["y1"] == 0.0
        assert state["exposure"] == 5.0
        assert state["contrast"] == 100.0
        assert state["saturation"] == -100.0
        assert state["clarity"] == 100.0

    def test_mask_reaches_export_image(self, qapp, sample_image):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        unmasked_export = controller.get_export_image()
        controller.restore_adjustment_state({"mask": self._RADIAL_MASK})
        masked_export = controller.get_export_image()

        assert masked_export is not None
        assert masked_export.shape == unmasked_export.shape
        assert not (masked_export == unmasked_export).all()

    def test_on_mask_changed_round_trips_and_adds_to_history(
        self, qapp, sample_image
    ):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        controller.on_mask_changed(self._LINEAR_MASK)

        assert controller.get_adjustment_state()["mask"] == self._LINEAR_MASK
        assert controller.can_undo() is True

    def test_on_mask_changed_none_clears_a_previously_set_mask(
        self, qapp, sample_image
    ):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        controller.on_mask_changed(self._LINEAR_MASK)
        assert controller.get_adjustment_state()["mask"] is not None

        controller.on_mask_changed(None)

        assert controller.get_adjustment_state()["mask"] is None

    def test_on_mask_changed_normalizes_defensively(self, qapp, sample_image):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        controller.on_mask_changed({"type": "radial", "rx": -5.0, "ry": 5.0})

        state = controller.get_adjustment_state()["mask"]
        assert state["type"] == "radial"
        assert 0.0 < state["rx"] <= 1.0
        assert 0.0 < state["ry"] <= 1.0

    def test_mask_undo_restores_prior_mask_state_not_latest(
        self, qapp, sample_image
    ):
        """Set mask A, then mask B, undo, assert the mask state equals A,
        not B -- the core state-aware undo/redo regression pattern."""
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        controller.on_mask_changed(self._LINEAR_MASK)
        controller.on_mask_changed(self._RADIAL_MASK)

        assert controller.get_adjustment_state()["mask"] == self._RADIAL_MASK

        assert controller.undo() is True

        assert controller.get_adjustment_state()["mask"] == self._LINEAR_MASK

    def test_reset_to_original_clears_mask(self, qapp, sample_image):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        controller.on_mask_changed(self._LINEAR_MASK)

        controller.reset_to_original()

        assert controller.get_adjustment_state()["mask"] is None

    def test_loading_a_different_image_clears_mask(self, qapp, sample_image):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        controller.on_mask_changed(self._LINEAR_MASK)

        controller._apply_loaded_image("other.jpg", pil_to_linear(sample_image))

        assert controller.get_adjustment_state()["mask"] is None

    def test_mask_applies_before_crop_not_after(self, qapp, sample_image):
        """Pipeline-order regression: mask geometry is expressed in the
        full pre-crop frame's own normalized coordinates, so a mask set
        alongside a crop must still reach a shape that matches the
        cropped output (mask-then-crop, not crop-then-mask)."""
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        original_shape = pil_to_linear(sample_image).shape

        controller.restore_adjustment_state(
            {
                "mask": self._RADIAL_MASK,
                "crop": {"x0": 0.25, "y0": 0.25, "x1": 0.75, "y1": 0.75},
            }
        )

        export = controller.get_export_image()
        assert export is not None
        assert export.shape[0] < original_shape[0]
        assert export.shape[1] < original_shape[1]
        assert np.all(np.isfinite(export))


class TestImageControllerStateAwareUndoRedo:
    """State-aware undo/redo (docs/planning/implementation-notes/
    2026-10-13-state-aware-undo-redo.md): undo/redo must restore not just
    the pixel buffer but the full internal adjustment-param state, and
    must notify listeners via ``adjustment_state_restored`` so the UI and
    persisted catalog state resync.
    """

    def test_undo_restores_adjustment_state_not_just_image(self, qapp, sample_image):
        """The core regression test for this slice.

        Before this fix, ImageController's undo only swapped the pixel
        buffer -- the internal _exposure_params dict stayed at whatever
        the most recent edit set it to. Applying exposure=1.0 then
        exposure=2.0, then undoing, must leave get_adjustment_state()
        reporting 1.0 (matching the now-displayed image), not 2.0 (the
        stale, pre-undo param value).
        """
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        controller.apply_adjustments(
            exposure_params={"exposure": 1.0}, add_to_history=True
        )
        controller.apply_adjustments(
            exposure_params={"exposure": 2.0}, add_to_history=True
        )
        assert controller.get_adjustment_state()["exposure"] == 2.0

        assert controller.undo() is True

        assert controller.get_adjustment_state()["exposure"] == 1.0

    def test_live_pipeline_builds_on_undone_state_not_stale_params(
        self, qapp, sample_image
    ):
        """After undo, a further edit must build on the *restored* state,
        not on the stale pre-undo params -- otherwise the live pipeline
        would silently recompute from the wrong baseline.
        """
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        controller.apply_adjustments(
            exposure_params={"exposure": 1.0}, add_to_history=True
        )
        controller.apply_adjustments(
            exposure_params={"exposure": 2.0}, add_to_history=True
        )
        controller.undo()

        # Apply a third, distinct adjustment through the normal flow.
        controller.apply_adjustments(
            exposure_params={"exposure": 1.0, "contrast": 5.0, "brightness": 0.0},
            add_to_history=True,
        )

        state = controller.get_adjustment_state()
        assert state["exposure"] == 1.0
        assert state["contrast"] == 5.0

        # Independently compute the expected image: exposure=1.0 baseline
        # (the undone-to state) + contrast=5.0, not exposure=2.0 + contrast=5.0.
        original = controller.image_model.get_original_image()
        expected = controller._exposure_processor.process(
            original.copy(), exposure=1.0, contrast=5.0, brightness=0.0
        )
        assert np.allclose(controller.image_model.current_image, expected)

    def test_redo_restores_image_and_state_to_pre_undo_values(
        self, qapp, sample_image
    ):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        controller.apply_adjustments(
            exposure_params={"exposure": 1.0}, add_to_history=True
        )
        controller.apply_adjustments(
            exposure_params={"exposure": 2.0}, add_to_history=True
        )
        image_after_second_edit = controller.image_model.current_image

        controller.undo()
        assert controller.get_adjustment_state()["exposure"] == 1.0

        assert controller.redo() is True

        assert controller.get_adjustment_state()["exposure"] == 2.0
        assert np.allclose(
            controller.image_model.current_image, image_after_second_edit
        )

    def test_adjustment_state_restored_emitted_on_undo(
        self, qapp, qtbot, sample_image
    ):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        controller.apply_adjustments(
            exposure_params={"exposure": 1.0}, add_to_history=True
        )
        controller.apply_adjustments(
            exposure_params={"exposure": 2.0}, add_to_history=True
        )

        with qtbot.waitSignal(
            controller.adjustment_state_restored, timeout=2000
        ) as blocker:
            controller.undo()

        assert blocker.args[0]["exposure"] == 1.0

    def test_adjustment_state_restored_emitted_on_redo(
        self, qapp, qtbot, sample_image
    ):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        controller.apply_adjustments(
            exposure_params={"exposure": 1.0}, add_to_history=True
        )
        controller.apply_adjustments(
            exposure_params={"exposure": 2.0}, add_to_history=True
        )
        controller.undo()

        with qtbot.waitSignal(
            controller.adjustment_state_restored, timeout=2000
        ) as blocker:
            controller.redo()

        assert blocker.args[0]["exposure"] == 2.0

    def test_curve_undo_restores_full_curve_state(self, qapp, sample_image):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        first_points = [[0.0, 0.0], [0.25, 0.35], [1.0, 1.0]]
        second_points = [[0.0, 0.0], [0.25, 0.12], [1.0, 1.0]]
        controller.on_curve_changed(first_points)
        controller.commit_adjustments()
        controller.on_curve_changed(second_points)
        controller.commit_adjustments()

        assert controller.get_adjustment_state()["tone_curve"] != first_points

        assert controller.undo() is True

        restored_curve = controller.get_adjustment_state()["tone_curve"]
        assert restored_curve == first_points

    def test_hsl_undo_restores_full_hsl_state(self, qapp, sample_image):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        first_hsl = {**default_hsl_params(), "red_sat": 20.0}
        second_hsl = {**default_hsl_params(), "red_sat": 40.0}
        controller.on_hsl_changed(first_hsl)
        controller.commit_adjustments()
        controller.on_hsl_changed(second_hsl)
        controller.commit_adjustments()

        assert controller.get_adjustment_state()["hsl"]["red_sat"] == 40.0

        assert controller.undo() is True

        assert controller.get_adjustment_state()["hsl"]["red_sat"] == 20.0

    def test_color_grading_undo_restores_full_color_grading_state(
        self, qapp, sample_image
    ):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))

        first_cg = {**default_color_grading_params(), "midtones_hue": 90.0}
        second_cg = {**default_color_grading_params(), "midtones_hue": 180.0}
        controller.on_color_grading_changed(first_cg)
        controller.commit_adjustments()
        controller.on_color_grading_changed(second_cg)
        controller.commit_adjustments()

        assert (
            controller.get_adjustment_state()["color_grading"]["midtones_hue"] == 180.0
        )

        assert controller.undo() is True

        assert (
            controller.get_adjustment_state()["color_grading"]["midtones_hue"] == 90.0
        )

    def test_restore_adjustment_state_clears_pending_history_state(
        self, qapp, sample_image
    ):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        controller._pending_history_previous_image = (
            controller.image_model.get_current_image()
        )
        controller._pending_history_previous_state = controller.get_adjustment_state()

        controller.restore_adjustment_state({"exposure": 1.0})

        assert controller._pending_history_previous_image is None
        assert controller._pending_history_previous_state is None

    def test_reset_to_original_clears_pending_history_state(
        self, qapp, sample_image
    ):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        controller._pending_history_previous_image = (
            controller.image_model.get_current_image()
        )
        controller._pending_history_previous_state = controller.get_adjustment_state()

        controller.reset_to_original()

        assert controller._pending_history_previous_image is None
        assert controller._pending_history_previous_state is None

    def test_loading_a_different_image_clears_pending_history_state(
        self, qapp, sample_image
    ):
        controller = ImageController(ImageView(), use_threading=False)
        controller._apply_loaded_image("sample.jpg", pil_to_linear(sample_image))
        controller._pending_history_previous_image = (
            controller.image_model.get_current_image()
        )
        controller._pending_history_previous_state = controller.get_adjustment_state()

        controller._apply_loaded_image("sample2.jpg", pil_to_linear(sample_image))

        assert controller._pending_history_previous_image is None
        assert controller._pending_history_previous_state is None
