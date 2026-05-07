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
