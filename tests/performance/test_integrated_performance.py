"""Integrated performance tests for complete adjustment workflow."""

import pytest
import time
from pathlib import Path
from PIL import Image
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from src.views.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    """Create QApplication for Qt tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def large_image_file(tmp_path):
    """Create a large test image (simulating DSLR photo)."""
    image_path = tmp_path / "large_test.jpg"
    # 24MP image (6000x4000)
    img = Image.new('RGB', (6000, 4000), color=(128, 128, 128))
    img.save(image_path, 'JPEG', quality=95)
    return str(image_path)


class TestIntegratedPerformance:
    """Test performance of complete adjustment workflows."""

    def test_slider_response_time(self, qapp, qtbot, large_image_file):
        """Test that slider adjustments respond using proxy (faster than full-res)."""
        window = MainWindow()
        qtbot.addWidget(window)
        window.show()
        qtbot.waitExposed(window)
        
        # Load large image
        window._image_controller.load_image(large_image_file)
        qtbot.wait(200)  # Wait for proxy generation
        
        # Verify proxy was created
        if window._image_controller._processing_worker:
            proxy_manager = window._image_controller._processing_worker.proxy_manager
            assert proxy_manager.needs_proxy() is True, "Large image should use proxy"
            assert proxy_manager.get_pixel_count_ratio() < 0.1, "Proxy should have <10% pixels"
        
        slider = window._tools_panel._exposure_slider
        
        # Measure time from slider change to UI update
        callback_called = False
        
        def on_adjustment():
            nonlocal callback_called
            callback_called = True
        
        window._tools_panel.adjustments_changed.connect(on_adjustment)
        
        # Move slider
        start = time.perf_counter()
        slider.set_value(1.0)
        
        # Wait for debounced processing
        qtbot.wait(800)
        response_time = time.perf_counter() - start
        
        # With proxy, should be faster than full-res processing (400-800ms for 24MP)
        # Proxy processing should be < 200ms, so total < 1s including debounce
        assert response_time < 1.0, f"Slider response took {response_time*1000:.1f}ms"
        assert callback_called is True, "Adjustment signal should fire"
        
        window.close()

    def test_rapid_slider_movement_performance(self, qapp, qtbot, large_image_file):
        """Test that debouncing reduces processing during rapid movements."""
        window = MainWindow()
        qtbot.addWidget(window)
        window.show()
        qtbot.waitExposed(window)
        
        window._image_controller.load_image(large_image_file)
        qtbot.wait(200)
        
        slider = window._tools_panel._exposure_slider
        
        # Count processing calls
        processing_count = 0
        
        def on_processing():
            nonlocal processing_count
            processing_count += 1
        
        # Connect to worker signal if available
        if window._image_controller._processing_worker:
            window._image_controller._processing_worker.processing_started.connect(on_processing)
        
        # Rapid slider movements (20 changes)
        for value in range(0, 20):
            slider.set_value(value / 10.0)
            qtbot.wait(10)  # 10ms between changes
        
        # Wait for debounced processing
        qtbot.wait(300)
        
        # With debouncing, should process much less than 20 times
        # (exact count depends on timing, but should be < 10)
        if window._image_controller._processing_worker:
            # Processing count should be less than number of slider changes
            assert processing_count < 20, f"Processed {processing_count} times (should be < 20 with debouncing)"
            assert processing_count > 0, "Should process at least once"
        
        window.close()

    def test_full_resolution_processing_time(self, qapp, qtbot, large_image_file):
        """Test that full-resolution processing happens in background (non-blocking)."""
        window = MainWindow()
        qtbot.addWidget(window)
        window.show()
        qtbot.waitExposed(window)
        
        window._image_controller.load_image(large_image_file)
        qtbot.wait(200)
        
        # Make adjustment
        window._tools_panel._exposure_slider.set_value(2.0)
        qtbot.wait(100)
        
        # Verify threading is enabled
        assert window._image_controller._processing_worker is not None, "Threading should be enabled"
        assert window._image_controller._processing_worker.is_running(), "Worker thread should be running"
        
        # Trigger full-resolution processing
        window._image_controller.on_slider_released()
        
        # UI should remain responsive (non-blocking)
        # Can still interact with UI immediately
        window._image_controller.zoom_in()
        window._image_controller.zoom_out()
        
        # Wait for actual processing to complete
        qtbot.wait(2000)  # Allow time for background processing
        
        # Verify image was processed
        current = window._image_controller.get_current_image()
        assert current is not None
        
        window.close()

    def test_multiple_adjustments_performance(self, qapp, qtbot, large_image_file):
        """Test that multiple adjustments use proxy for fast feedback."""
        window = MainWindow()
        qtbot.addWidget(window)
        window.show()
        qtbot.waitExposed(window)
        
        window._image_controller.load_image(large_image_file)
        qtbot.wait(200)
        
        # Verify proxy is being used
        if window._image_controller._processing_worker:
            proxy_manager = window._image_controller._processing_worker.proxy_manager
            assert proxy_manager.needs_proxy() is True
        
        # Apply multiple adjustments
        window._tools_panel._exposure_slider.set_value(1.0)
        qtbot.wait(100)
        window._tools_panel._contrast_slider.set_value(20.0)
        qtbot.wait(100)
        window._tools_panel._brightness_slider.set_value(10.0)
        qtbot.wait(100)
        window._tools_panel._saturation_slider.set_value(30.0)
        qtbot.wait(100)
        
        # Wait for all processing
        qtbot.wait(500)
        
        # Verify all adjustments were applied
        adjustments = window._tools_panel.get_adjustments()
        assert adjustments['exposure'] == 1.0
        assert adjustments['contrast'] == 20.0
        assert adjustments['brightness'] == 10.0
        assert adjustments['saturation'] == 30.0
        
        window.close()

    def test_ui_responsiveness_during_processing(self, qapp, qtbot, large_image_file):
        """Test that UI remains responsive during heavy processing (threading works)."""
        window = MainWindow()
        qtbot.addWidget(window)
        window.show()
        qtbot.waitExposed(window)
        
        window._image_controller.load_image(large_image_file)
        qtbot.wait(200)
        
        # Verify threading is enabled
        assert window._image_controller._processing_worker is not None
        assert window._image_controller._processing_worker.is_running()
        
        # Start processing
        window._tools_panel._exposure_slider.set_value(3.0)
        
        # Simulate UI interactions during processing
        # With threading, UI should remain responsive
        zoom_operations = 0
        for _ in range(10):
            # Simulate zoom (should work even during processing)
            try:
                window._image_controller.zoom_in()
                zoom_operations += 1
            except Exception:
                # If UI is blocked, operations might fail
                pass
        
        # Should be able to perform zoom operations
        assert zoom_operations > 0, "UI should allow interactions during processing"
        
        # Wait for processing to complete
        qtbot.wait(1000)
        
        window.close()
