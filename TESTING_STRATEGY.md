# PhotoEdit - Testing Strategy & Unit Test Plan
## Comprehensive Test Coverage for All Features

---

## 1. Testing Philosophy

### Core Principles
- **Test-Driven Development (TDD)**: Write tests before or alongside code
- **Comprehensive Coverage**: Aim for 80%+ code coverage
- **Isolated Tests**: Each test is independent and can run in any order
- **Fast Execution**: Unit tests should run in seconds, not minutes
- **Clear Assertions**: Tests should clearly indicate what failed and why

### Testing Pyramid
```
        /\
       /  \      E2E Tests (Few)
      /____\
     /      \    Integration Tests (Some)
    /________\
   /          \  Unit Tests (Many)
  /____________\
```

---

## 2. Testing Framework & Tools

### Primary Framework
- **pytest**: Main testing framework
- **pytest-qt**: PyQt6 testing utilities
- **pytest-cov**: Code coverage reporting
- **pytest-mock**: Mocking utilities

### Additional Tools
- **unittest.mock**: Standard library mocking
- **hypothesis**: Property-based testing for algorithms
- **faker**: Generate test data
- **Pillow**: Create test images programmatically

### Dependencies
```toml
[dev-packages]
pytest = "*"
pytest-qt = "*"
pytest-cov = "*"
pytest-mock = "*"
hypothesis = "*"
faker = "*"
```

---

## 3. Test Organization

### Directory Structure
```
tests/
├── __init__.py
├── conftest.py              # Shared fixtures
├── fixtures/                # Test data and fixtures
│   ├── __init__.py
│   ├── test_images/         # Sample images for testing
│   └── test_data.py         # Test data generators
│
├── unit/                    # Unit tests
│   ├── __init__.py
│   ├── test_models/
│   │   ├── __init__.py
│   │   ├── test_image_model.py
│   │   ├── test_project_model.py
│   │   ├── test_metadata_model.py
│   │   └── test_settings_model.py
│   │
│   ├── test_services/
│   │   ├── __init__.py
│   │   ├── test_image_service.py
│   │   ├── test_file_service.py
│   │   ├── test_history_service.py
│   │   ├── test_export_service.py
│   │   ├── test_metadata_service.py
│   │   └── test_cache_service.py
│   │
│   ├── test_processors/
│   │   ├── __init__.py
│   │   ├── test_exposure_processor.py
│   │   ├── test_color_processor.py
│   │   ├── test_sharpening_processor.py
│   │   ├── test_noise_reduction.py
│   │   └── test_filters.py
│   │
│   ├── test_commands/
│   │   ├── __init__.py
│   │   ├── test_base_command.py
│   │   ├── test_adjustment_commands.py
│   │   ├── test_filter_commands.py
│   │   └── test_transform_commands.py
│   │
│   ├── test_utils/
│   │   ├── __init__.py
│   │   ├── test_image_utils.py
│   │   ├── test_color_utils.py
│   │   ├── test_file_utils.py
│   │   └── test_validators.py
│   │
│   └── test_controllers/
│       ├── __init__.py
│       ├── test_main_controller.py
│       ├── test_image_controller.py
│       ├── test_library_controller.py
│       └── test_tool_controller.py
│
├── integration/             # Integration tests
│   ├── __init__.py
│   ├── test_image_workflow.py
│   ├── test_undo_redo_workflow.py
│   ├── test_export_workflow.py
│   └── test_batch_operations.py
│
└── ui/                      # UI tests (with pytest-qt)
    ├── __init__.py
    ├── test_main_window.py
    ├── test_image_view.py
    ├── test_library_view.py
    ├── test_tool_panel.py
    └── test_widgets.py
```

---

## 4. Test Coverage by Feature

### 4.1 Image Management

#### Image Import
- [ ] **test_import_single_image**
  - Import JPEG file
  - Import PNG file
  - Import TIFF file
  - Import RAW file (if supported)
  - Handle invalid file
  - Handle non-image file
  - Handle corrupted image
  - Handle missing file

- [ ] **test_import_multiple_images**
  - Import multiple files
  - Import folder
  - Handle mixed formats
  - Handle duplicates
  - Progress tracking

- [ ] **test_drag_drop_import**
  - Drag single file
  - Drag multiple files
  - Drag folder
  - Invalid drag data

#### Image Library View
- [ ] **test_library_grid_view**
  - Display thumbnails
  - Thumbnail generation
  - Thumbnail caching
  - Grid layout calculation
  - Scroll behavior

- [ ] **test_library_selection**
  - Single selection
  - Multiple selection
  - Select all
  - Deselect all
  - Selection persistence

- [ ] **test_library_sorting**
  - Sort by name
  - Sort by date
  - Sort by size
  - Sort ascending/descending

- [ ] **test_library_filtering**
  - Filter by format
  - Filter by date range
  - Filter by rating
  - Search by name

#### Image Viewing
- [ ] **test_image_display**
  - Display loaded image
  - Fit to window
  - 100% zoom
  - Fit to width
  - Fit to height

- [ ] **test_image_zoom**
  - Zoom in
  - Zoom out
  - Zoom limits
  - Zoom with mouse wheel
  - Zoom with buttons

- [ ] **test_image_pan**
  - Pan when zoomed
  - Pan boundaries
  - Pan with mouse
  - Pan with keyboard

- [ ] **test_before_after_view**
  - Toggle before/after
  - Split view (vertical)
  - Split view (horizontal)
  - Side-by-side view

---

### 4.2 Basic Adjustments

#### Exposure Controls
- [ ] **test_exposure_adjustment**
  - Adjust exposure value
  - Valid range (-5 to +5)
  - Default value (0)
  - Reset functionality
  - Undo/redo

- [ ] **test_contrast_adjustment**
  - Adjust contrast
  - Valid range
  - Default value
  - Reset functionality

- [ ] **test_highlights_adjustment**
  - Adjust highlights
  - Valid range
  - Clipping detection

- [ ] **test_shadows_adjustment**
  - Adjust shadows
  - Valid range
  - Clipping detection

- [ ] **test_whites_blacks_adjustment**
  - Adjust whites
  - Adjust blacks
  - Valid ranges

#### Color Adjustments
- [ ] **test_saturation_adjustment**
  - Adjust saturation
  - Valid range (-100 to +100)
  - Zero saturation (grayscale)

- [ ] **test_vibrance_adjustment**
  - Adjust vibrance
  - Valid range
  - Difference from saturation

- [ ] **test_white_balance**
  - Adjust temperature
  - Adjust tint
  - Valid ranges
  - Auto white balance

- [ ] **test_color_grading**
  - Adjust shadow color
  - Adjust midtone color
  - Adjust highlight color
  - Color picker integration

#### Tone Curve
- [ ] **test_tone_curve_basic**
  - Create curve point
  - Move curve point
  - Delete curve point
  - Reset curve

- [ ] **test_tone_curve_channels**
  - RGB curve
  - Red channel curve
  - Green channel curve
  - Blue channel curve

- [ ] **test_tone_curve_presets**
  - Apply preset
  - Save preset
  - Load preset
  - Delete preset

---

### 4.3 Essential Tools

#### Undo/Redo
- [ ] **test_undo_redo_basic**
  - Single undo
  - Multiple undo
  - Single redo
  - Multiple redo
  - Undo limit

- [ ] **test_undo_redo_with_commands**
  - Undo adjustment command
  - Redo adjustment command
  - Undo filter command
  - Redo filter command

- [ ] **test_history_service**
  - Add command to history
  - Clear history
  - History size limit
  - History persistence

- [ ] **test_history_panel**
  - Display history
  - Select history item
  - Jump to history state

#### Image Export
- [ ] **test_export_jpeg**
  - Export to JPEG
  - Quality settings
  - File size validation
  - Metadata preservation

- [ ] **test_export_png**
  - Export to PNG
  - Compression settings
  - Transparency support

- [ ] **test_export_tiff**
  - Export to TIFF
  - Compression options
  - Bit depth options

- [ ] **test_export_options**
  - Resize on export
  - Quality settings
  - Metadata inclusion
  - Color space conversion

- [ ] **test_batch_export**
  - Export multiple images
  - Naming patterns
  - Progress tracking
  - Error handling

#### Project Management
- [ ] **test_save_project**
  - Save project file
  - Include image references
  - Include edit history
  - Include metadata

- [ ] **test_load_project**
  - Load project file
  - Restore image state
  - Restore edit history
  - Handle missing images

- [ ] **test_auto_save**
  - Auto-save interval
  - Auto-save on changes
  - Auto-save recovery

---

### 4.4 Advanced Adjustments

#### Detail Enhancement
- [ ] **test_sharpening**
  - Amount adjustment
  - Radius adjustment
  - Detail adjustment
  - Masking adjustment

- [ ] **test_noise_reduction**
  - Luminance noise reduction
  - Color noise reduction
  - Preserve detail
  - Valid ranges

- [ ] **test_clarity_adjustment**
  - Clarity adjustment
  - Valid range
  - Effect on image

#### Lens Corrections
- [ ] **test_distortion_correction**
  - Apply distortion correction
  - Manual adjustment
  - Profile-based correction

- [ ] **test_chromatic_aberration**
  - Remove chromatic aberration
  - Manual adjustment

- [ ] **test_vignette_correction**
  - Remove vignette
  - Add vignette
  - Amount and midpoint

#### Transform Tools
- [ ] **test_rotation**
  - Rotate 90 degrees
  - Rotate 180 degrees
  - Rotate custom angle
  - Crop after rotation

- [ ] **test_flip**
  - Flip horizontal
  - Flip vertical
  - Undo flip

- [ ] **test_crop**
  - Crop selection
  - Aspect ratio presets
  - Free crop
  - Crop constraints

- [ ] **test_straighten**
  - Straighten tool
  - Angle calculation
  - Auto-crop after straighten

#### Local Adjustments
- [ ] **test_gradient_filter**
  - Create gradient
  - Adjust gradient position
  - Apply adjustments to gradient
  - Multiple gradients

- [ ] **test_radial_filter**
  - Create radial filter
  - Adjust size and position
  - Apply adjustments
  - Feather adjustment

- [ ] **test_brush_tool**
  - Brush painting
  - Brush size
  - Brush hardness
  - Brush flow
  - Mask visualization

---

### 4.5 Filters & Effects

#### Preset Filters
- [ ] **test_preset_application**
  - Apply preset
  - Apply to multiple images
  - Preset preview

- [ ] **test_preset_management**
  - Create preset
  - Save preset
  - Load preset
  - Delete preset
  - Preset categories

#### Creative Effects
- [ ] **test_vignette_effect**
  - Add vignette
  - Adjust amount
  - Adjust midpoint
  - Adjust roundness

- [ ] **test_grain_effect**
  - Add grain
  - Adjust amount
  - Adjust size
  - Adjust roughness

- [ ] **test_split_toning**
  - Highlight hue/saturation
  - Shadow hue/saturation
  - Balance adjustment

---

### 4.6 Metadata & Organization

#### Metadata Viewing
- [ ] **test_exif_display**
  - Display EXIF data
  - Camera settings
  - GPS data
  - Custom metadata

- [ ] **test_metadata_editing**
  - Edit metadata
  - Save metadata
  - Metadata validation

#### Organization Tools
- [ ] **test_keywords**
  - Add keyword
  - Remove keyword
  - Search by keyword
  - Keyword suggestions

- [ ] **test_ratings**
  - Set rating (1-5 stars)
  - Filter by rating
  - Batch rating

- [ ] **test_color_labels**
  - Set color label
  - Filter by label
  - Multiple labels

- [ ] **test_collections**
  - Create collection
  - Add to collection
  - Remove from collection
  - Collection hierarchy

---

## 5. Test Fixtures & Utilities

### Common Fixtures (conftest.py)

```python
import pytest
from PIL import Image
import numpy as np
from PyQt6.QtWidgets import QApplication

@pytest.fixture(scope="session")
def qapp():
    """Create QApplication for Qt tests"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app

@pytest.fixture
def sample_image():
    """Create a sample test image"""
    img = Image.new('RGB', (100, 100), color='red')
    return img

@pytest.fixture
def sample_image_path(tmp_path):
    """Create a temporary image file"""
    img = Image.new('RGB', (100, 100), color='blue')
    path = tmp_path / "test_image.jpg"
    img.save(path)
    return str(path)

@pytest.fixture
def image_model():
    """Create a test image model"""
    from src.models.image_model import ImageModel
    return ImageModel()

@pytest.fixture
def history_service():
    """Create a test history service"""
    from src.services.history_service import HistoryService
    return HistoryService()
```

---

## 6. Test Execution

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/unit/test_image_service.py

# Run specific test
pytest tests/unit/test_image_service.py::test_load_image

# Run with verbose output
pytest -v

# Run with output
pytest -s

# Run only fast tests
pytest -m "not slow"

# Run in parallel
pytest -n auto
```

### Continuous Integration

```yaml
# Example GitHub Actions workflow
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
      - run: pip install -r requirements.txt
      - run: pip install pytest pytest-cov pytest-qt
      - run: pytest --cov=src --cov-report=xml
      - uses: codecov/codecov-action@v2
```

---

## 7. Test Quality Metrics

### Coverage Goals
- **Overall Coverage**: 80%+
- **Critical Paths**: 95%+ (services, processors, commands)
- **UI Components**: 70%+ (focus on logic, not rendering)
- **Utilities**: 90%+

### Test Categories
- **Unit Tests**: Fast (< 1 second each), isolated
- **Integration Tests**: Medium speed (< 5 seconds each)
- **UI Tests**: Slower (< 10 seconds each), require QApplication

### Performance Benchmarks
- **Test Suite**: Complete run < 2 minutes
- **Unit Tests**: < 30 seconds total
- **Integration Tests**: < 1 minute total
- **UI Tests**: < 30 seconds total

---

## 8. Mocking Strategy

### When to Mock
- **File I/O**: Mock file operations for speed
- **External Libraries**: Mock heavy operations (OpenCV, rawpy)
- **Qt Signals**: Use pytest-qt for signal testing
- **Time-dependent**: Mock time for consistent tests

### Example Mocks
```python
from unittest.mock import Mock, patch, MagicMock

def test_image_loading(mocker):
    """Test image loading with mocked file operation"""
    mock_open = mocker.patch('builtins.open')
    mock_image = Mock()
    mocker.patch('PIL.Image.open', return_value=mock_image)
    
    service = ImageService()
    result = service.load_image('test.jpg')
    
    assert result is not None
    mock_image.verify()
```

---

## 9. Property-Based Testing

### Using Hypothesis
```python
from hypothesis import given, strategies as st

@given(
    exposure=st.floats(min_value=-5.0, max_value=5.0),
    contrast=st.floats(min_value=-100.0, max_value=100.0)
)
def test_adjustment_combinations(exposure, contrast):
    """Test various adjustment combinations"""
    processor = ExposureProcessor()
    result = processor.apply_adjustments(exposure, contrast)
    assert result is not None
    # Additional assertions
```

---

## 10. Test Maintenance

### Best Practices
- **Keep tests updated**: Update tests when code changes
- **Remove obsolete tests**: Delete tests for removed features
- **Refactor tests**: Keep tests DRY (Don't Repeat Yourself)
- **Document complex tests**: Add comments for non-obvious tests
- **Review test failures**: Investigate and fix flaky tests

### Test Naming Convention
```
test_<feature>_<scenario>_<expected_result>

Examples:
- test_load_image_valid_file_returns_image
- test_adjust_exposure_negative_value_darkens_image
- test_export_jpeg_high_quality_produces_large_file
```

---

## 11. Test Checklist per Feature

For each new feature, ensure:
- [ ] Unit tests for core logic
- [ ] Integration tests for workflows
- [ ] UI tests for user interactions (if applicable)
- [ ] Edge case tests
- [ ] Error handling tests
- [ ] Performance tests (if critical)
- [ ] Documentation of test coverage

---

## Notes

- Tests should be written alongside code, not after
- Aim for fast feedback loop
- Use fixtures to reduce duplication
- Mock external dependencies
- Test behavior, not implementation
- Keep tests independent and isolated
