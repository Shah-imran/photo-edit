# PhotoEdit - Lightroom-like Application
## Architecture & Design Planning Document

---

## 1. Technology Stack Decision

### PyQt5 vs PyQt6

**Recommendation: PyQt6**

**Reasons:**
- **Future-proof**: PyQt6 is the current version with active development
- **Better performance**: Improved rendering and memory management
- **Modern features**: Better support for high-DPI displays, improved styling
- **Long-term support**: PyQt5 is in maintenance mode
- **Python 3.10+ compatibility**: Better integration with modern Python features
- **API improvements**: Cleaner API design and better type hints support

**Trade-offs:**
- Slightly less mature ecosystem (but stable enough for production)
- Some older tutorials/examples use PyQt5 (but migration is straightforward)

---

## 2. Core Architecture

### 2.1 High-Level Architecture Pattern

**Recommended: Model-View-Controller (MVC) with Service Layer**

```
┌─────────────────────────────────────────────────────────┐
│                    Presentation Layer                    │
│  (Views: MainWindow, ImageView, ToolPanels, etc.)       │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│                  Controller Layer                        │
│  (Event Handlers, View Controllers, Command Pattern)     │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│                   Service Layer                          │
│  (Image Processing, File Management, History, Export)   │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│                    Model Layer                           │
│  (Image Data, Metadata, Project State, Settings)        │
└─────────────────────────────────────────────────────────┘
```

### 2.2 Design Patterns to Implement

#### **1. Command Pattern** (Critical for Undo/Redo)
- Every edit operation becomes a command
- Enables full undo/redo functionality
- Essential for non-destructive editing

#### **2. Observer Pattern**
- Model changes notify views
- Real-time preview updates
- History tracking

#### **3. Strategy Pattern**
- Different image processing algorithms
- Export formats (JPEG, PNG, TIFF, etc.)
- Filter implementations

#### **4. Factory Pattern**
- Create different tool instances
- Export format handlers
- Image format loaders

#### **5. Singleton Pattern**
- Application settings
- Theme manager
- Resource manager

#### **6. Facade Pattern**
- Simplify complex image processing operations
- Unified API for different image libraries (PIL, OpenCV, etc.)

---

## 3. Project Structure

```
PhotoEdit/
├── src/
│   ├── main.py                 # Application entry point
│   │
│   ├── models/                 # Data models
│   │   ├── __init__.py
│   │   ├── image_model.py      # Image data structure
│   │   ├── project_model.py    # Project/workspace state
│   │   ├── metadata_model.py   # EXIF and custom metadata
│   │   └── settings_model.py   # User preferences
│   │
│   ├── views/                  # UI components
│   │   ├── __init__.py
│   │   ├── main_window.py      # Main application window
│   │   ├── image_view.py       # Image display widget
│   │   ├── library_view.py     # Photo library/import view
│   │   ├── tool_panel.py       # Adjustments panel
│   │   ├── histogram_widget.py # Histogram display
│   │   ├── preview_panel.py    # Before/after preview
│   │   └── widgets/            # Reusable UI widgets
│   │       ├── slider_widget.py
│   │       ├── color_picker.py
│   │       └── ...
│   │
│   ├── controllers/            # Business logic & event handling
│   │   ├── __init__.py
│   │   ├── main_controller.py  # Main window controller
│   │   ├── image_controller.py # Image operations controller
│   │   ├── library_controller.py
│   │   └── tool_controller.py
│   │
│   ├── services/               # Core services
│   │   ├── __init__.py
│   │   ├── image_service.py    # Image loading/processing
│   │   ├── file_service.py     # File I/O operations
│   │   ├── history_service.py  # Undo/redo management
│   │   ├── export_service.py   # Export operations
│   │   ├── metadata_service.py # Metadata handling
│   │   └── cache_service.py    # Thumbnail/preview caching
│   │
│   ├── commands/               # Command pattern implementations
│   │   ├── __init__.py
│   │   ├── base_command.py     # Abstract command class
│   │   ├── adjustment_commands.py
│   │   ├── filter_commands.py
│   │   └── transform_commands.py
│   │
│   ├── processors/             # Image processing algorithms
│   │   ├── __init__.py
│   │   ├── base_processor.py
│   │   ├── exposure_processor.py
│   │   ├── color_processor.py
│   │   ├── sharpening_processor.py
│   │   ├── noise_reduction.py
│   │   └── filters.py
│   │
│   ├── utils/                  # Utilities
│   │   ├── __init__.py
│   │   ├── image_utils.py      # Image helper functions
│   │   ├── color_utils.py      # Color space conversions
│   │   ├── file_utils.py       # File operations
│   │   └── validators.py       # Input validation
│   │
│   └── config/                 # Configuration
│       ├── __init__.py
│       ├── settings.py         # Application settings
│       └── constants.py        # Constants and enums
│
├── resources/                  # Resources
│   ├── icons/
│   ├── styles/
│   └── themes/
│
├── tests/                      # Comprehensive test suite
│   ├── __init__.py
│   ├── conftest.py             # Shared fixtures
│   ├── fixtures/               # Test data and fixtures
│   │   ├── test_images/        # Sample images
│   │   └── test_data.py
│   ├── unit/                   # Unit tests
│   │   ├── test_models/
│   │   ├── test_services/
│   │   ├── test_processors/
│   │   ├── test_commands/
│   │   ├── test_utils/
│   │   └── test_controllers/
│   ├── integration/            # Integration tests
│   └── ui/                     # UI tests (pytest-qt)
│
│
├── docs/                       # Documentation
│   ├── features.md
│   ├── architecture.md
│   └── api.md
│
├── Pipfile                     # Dependencies
├── README.md
└── docs/ARCHITECTURE.md        # This file
```

---

## 4. Core Components Design

### 4.1 Image Model
- **Purpose**: Store image data and state
- **Responsibilities**:
  - Hold original and modified image data
  - Track modification history
  - Manage metadata
  - Handle memory efficiently (lazy loading for large images)

### 4.2 Image Service
- **Purpose**: Core image operations
- **Responsibilities**:
  - Load/save images (multiple formats)
  - Apply non-destructive edits
  - Generate previews/thumbnails
  - Handle color space conversions
  - Memory management for large images

### 4.3 History Service
- **Purpose**: Undo/Redo functionality
- **Responsibilities**:
  - Store command history
  - Execute undo/redo operations
  - Manage history stack size
  - Save/load history for projects

### 4.4 Command System
- **Purpose**: Encapsulate all edit operations
- **Structure**:
  ```python
  class BaseCommand:
      def execute() -> None
      def undo() -> None
      def redo() -> None
      def can_undo() -> bool
  ```

---

## 5. Key Technical Considerations

### 5.1 Performance Optimization
- **Lazy Loading**: Load full-resolution images only when needed
- **Thumbnail Caching**: Cache thumbnails for library view
- **Preview Generation**: Generate lower-res previews for real-time editing
- **Threading**: Use QThread for heavy image processing
- **Memory Management**: Implement image pooling for large batches

### 5.2 Non-Destructive Editing
- **Layer-based approach**: Store edits as operations, not pixel changes
- **Original preservation**: Always keep original image intact
- **Virtual image**: Render final result from original + operations
- **History preservation**: Full edit history for undo/redo

### 5.3 Image Processing Libraries
- **Primary**: Pillow (PIL) - Python Imaging Library
- **Advanced**: OpenCV - For complex operations
- **Color Science**: colorspacious - Color space conversions
- **RAW Support**: rawpy - For RAW file support

### 5.4 UI/UX Considerations
- **Professional Design**: Lightroom-like dark theme interface
- **Responsive UI**: Use QThread to prevent UI freezing
- **Progress Indicators**: Show progress for long operations
- **Keyboard Shortcuts**: Full keyboard navigation (Lightroom-inspired)
- **Customizable Layout**: Dockable panels with saveable layouts
- **High DPI Support**: Proper scaling for 4K displays
- **Smooth Animations**: Subtle transitions for professional feel
- **Visual Hierarchy**: Clear focus on image being edited
- **See [UI_UX.md](UI_UX.md) for detailed design specifications**

---

## 6. Data Flow Example

### Editing an Image:
1. User adjusts exposure slider
2. Controller receives signal
3. Controller creates `AdjustExposureCommand`
4. Command executed through Image Service
5. Image Service applies adjustment (non-destructively)
6. Model updated with new state
7. View notified via Observer pattern
8. Image View updates display
9. Command added to History Service

### Undo Operation:
1. User presses Ctrl+Z
2. Controller requests undo from History Service
3. History Service retrieves last command
4. Command's `undo()` method called
5. Image Service reverts change
6. Model updated
7. View refreshed

---

## 7. Dependency Recommendations

```toml
[packages]
PyQt6 = "*"                    # Main GUI framework
PyQt6-Qt6 = "*"                # Qt6 bindings
Pillow = "*"                   # Image processing
numpy = "*"                    # Array operations
opencv-python = "*"            # Advanced image processing
rawpy = "*"                    # RAW file support
piexif = "*"                   # EXIF metadata
colorspacious = "*"            # Color space conversions

[dev-packages]
pytest = "*"                   # Testing framework
pytest-qt = "*"                # PyQt6 testing utilities
pytest-cov = "*"               # Code coverage
pytest-mock = "*"              # Mocking utilities
hypothesis = "*"               # Property-based testing
faker = "*"                    # Test data generation
```

---

## 8. Development Phases

### Phase 1: Foundation
- Project structure setup
- Basic window and image display
- Image loading/saving
- Basic MVC architecture

### Phase 2: Core Editing
- Command pattern implementation
- Basic adjustments (exposure, contrast, saturation)
- Undo/redo system
- History management

### Phase 3: Advanced Features
- Library/import view
- Multiple image support
- Batch operations
- Export functionality

### Phase 4: Polish
- UI/UX improvements
- Performance optimization
- Advanced filters
- Metadata management

---

## 9. Testing Strategy

### Testing Approach
- **Test-Driven Development (TDD)**: Write tests alongside or before code
- **Comprehensive Coverage**: Aim for 80%+ code coverage
- **Test Pyramid**: Many unit tests, some integration tests, few E2E tests
- **Fast Execution**: Complete test suite should run in < 2 minutes

### Test Organization
- **Unit Tests**: Fast, isolated tests for all components
- **Integration Tests**: Test workflows and component interactions
- **UI Tests**: Test user interactions with pytest-qt
- **See [TESTING.md](TESTING.md) for comprehensive test plan**

### Testing Tools
- **pytest**: Main testing framework
- **pytest-qt**: PyQt6 testing utilities
- **pytest-cov**: Code coverage reporting
- **hypothesis**: Property-based testing

---

## 10. Best Practices

1. **Separation of Concerns**: Keep UI, logic, and data separate
2. **Testability**: Write unit tests for all features (see [TESTING.md](TESTING.md))
3. **Documentation**: Document all public APIs
4. **Error Handling**: Comprehensive error handling and user feedback
5. **Logging**: Implement logging for debugging
6. **Configuration**: Externalize settings and preferences
7. **Internationalization**: Plan for i18n from the start (QTranslator)
8. **UI Consistency**: Follow Lightroom-like design guidelines (see [UI_UX.md](UI_UX.md))

---

## 11. Next Steps

1. ✅ Architecture planning (this document)
2. ✅ Feature specification ([planning/PRODUCT_ROADMAP.md](planning/PRODUCT_ROADMAP.md#part-2-feature-planning-catalog))
3. ✅ UI/UX design guidelines ([UI_UX.md](UI_UX.md))
4. ✅ Testing strategy ([TESTING.md](TESTING.md))
5. ⏭️ Detailed technical specifications for Phase 1
6. ⏭️ UI mockups/wireframes for core views
7. ⏭️ Development timeline
8. ⏭️ Begin Phase 1 implementation with tests

---

## Notes

- This architecture is designed to be scalable and maintainable
- Patterns can be added/removed as needed during development
- Consider using a state machine pattern for complex workflows
- May need to add a plugin system for extensibility later
