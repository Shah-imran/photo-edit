"""Unit tests for ImageView widget."""

import pytest
import numpy as np
from PIL import Image
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from src.processing.display_frame import DisplayFrame
from src.views.image_view import ImageView


@pytest.fixture(scope="module")
def qapp():
    """Create QApplication for Qt tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestImageView:
    """Test cases for ImageView widget."""

    def test_image_view_initialization(self, qapp):
        """Test ImageView can be initialized."""
        view = ImageView()
        assert view is not None
        assert view.has_image() is False
        assert view.get_zoom_factor() == 1.0

    def test_set_image(self, qapp, sample_image):
        """Test setting an image."""
        view = ImageView()
        view.set_image(sample_image)
        assert view.has_image() is True

    def test_set_display_frame(self, qapp):
        """Worker display frames should be presentable without linear conversion."""
        view = ImageView()
        frame = DisplayFrame(
            request_id=1,
            tier="interactive",
            adjustment_signature=(),
            rgb=np.full((20, 30, 3), 128, dtype=np.uint8),
        )

        view.set_display_frame(frame)

        assert view.has_image() is True

    def test_clear_image(self, qapp, sample_image):
        """Test clearing an image."""
        view = ImageView()
        view.set_image(sample_image)
        view.clear_image()
        assert view.has_image() is False

    def test_zoom_factor_default(self, qapp):
        """Test default zoom factor is 1.0."""
        view = ImageView()
        assert view.get_zoom_factor() == 1.0

    def test_set_zoom_factor(self, qapp, sample_image):
        """Test setting zoom factor."""
        view = ImageView()
        view.set_image(sample_image)
        view.set_zoom_factor(2.0)
        assert view.get_zoom_factor() == 2.0

    def test_zoom_factor_min_limit(self, qapp, sample_image):
        """Test zoom factor respects minimum limit."""
        view = ImageView()
        view.set_image(sample_image)
        view.set_zoom_factor(0.01)  # Below minimum
        assert view.get_zoom_factor() == view.MIN_ZOOM

    def test_zoom_factor_max_limit(self, qapp, sample_image):
        """Test zoom factor respects maximum limit."""
        view = ImageView()
        view.set_image(sample_image)
        view.set_zoom_factor(100.0)  # Above maximum
        assert view.get_zoom_factor() == view.MAX_ZOOM

    def test_zoom_in(self, qapp, sample_image):
        """Test zoom in functionality."""
        view = ImageView()
        view.set_image(sample_image)
        initial_zoom = view.get_zoom_factor()
        view.zoom_in()
        assert view.get_zoom_factor() > initial_zoom

    def test_zoom_out(self, qapp, sample_image):
        """Test zoom out functionality."""
        view = ImageView()
        view.set_image(sample_image)
        view.set_zoom_factor(2.0)
        view.zoom_out()
        assert view.get_zoom_factor() < 2.0

    def test_view_100_percent(self, qapp, sample_image):
        """Test 100% view functionality."""
        view = ImageView()
        view.set_image(sample_image)
        view.set_zoom_factor(2.0)
        view.view_100_percent()
        assert view.get_zoom_factor() == 1.0

    def test_fit_to_window_no_image(self, qapp):
        """Test fit to window with no image doesn't crash."""
        view = ImageView()
        view.fit_to_window()  # Should not raise

    def test_image_loaded_signal(self, qapp, sample_image):
        """Test image_loaded signal is emitted."""
        view = ImageView()
        signal_received = []
        view.image_loaded.connect(lambda: signal_received.append(True))
        view.set_image(sample_image)
        assert len(signal_received) == 1

    def test_zoom_changed_signal(self, qapp, sample_image):
        """Test zoom_changed signal is emitted."""
        view = ImageView()
        view.set_image(sample_image)
        zoom_values = []
        view.zoom_changed.connect(lambda z: zoom_values.append(z))
        view.set_zoom_factor(2.0)
        assert len(zoom_values) == 1
        assert zoom_values[0] == 2.0
