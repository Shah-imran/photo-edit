# PhotoEdit - Lightroom-like Photo Editing Application

A professional photo editing application built with Python and PyQt6, inspired by Adobe Lightroom Classic.

## 📋 Project Status

**Planning Phase** - Architecture and design documents are complete. Ready to begin implementation.

## 📚 Documentation

### Planning Documents
- **[ARCHITECTURE_PLAN.md](ARCHITECTURE_PLAN.md)** - Complete architecture, design patterns, and project structure
- **[FEATURES_PLAN.md](FEATURES_PLAN.md)** - Comprehensive feature list organized by priority
- **[UI_UX_DESIGN.md](UI_UX_DESIGN.md)** - Professional Lightroom-like UI/UX design guidelines
- **[TESTING_STRATEGY.md](TESTING_STRATEGY.md)** - Complete testing strategy with unit test plan for all features

## 🏗️ Architecture Overview

### Technology Stack
- **PyQt6**: Modern GUI framework
- **Pillow (PIL)**: Image processing
- **NumPy**: Array operations
- **OpenCV**: Advanced image processing
- **rawpy**: RAW file support
- **pytest**: Testing framework

### Architecture Pattern
**MVC with Service Layer** - Clean separation of concerns:
- **Models**: Data structures and state
- **Views**: UI components
- **Controllers**: Business logic and event handling
- **Services**: Core operations (image processing, file I/O, etc.)

### Key Design Patterns
1. **Command Pattern** - For undo/redo functionality
2. **Observer Pattern** - For real-time UI updates
3. **Strategy Pattern** - For interchangeable algorithms
4. **Factory Pattern** - For tool and format handler creation
5. **Singleton Pattern** - For settings and resource management

## 🎨 UI/UX Design

### Design Philosophy
- **Professional & Clean**: Minimal, distraction-free interface
- **Dark Theme First**: Professional dark interface (Lightroom Classic style)
- **Efficient Workflow**: Everything accessible within 2-3 clicks
- **Visual Hierarchy**: Clear focus on the image being edited

### Key Features
- Lightroom-inspired layout with dockable panels
- Smooth animations and transitions
- Full keyboard navigation
- High DPI support for 4K displays
- Customizable interface

See [UI_UX_DESIGN.md](UI_UX_DESIGN.md) for complete design specifications.

## 🧪 Testing Strategy

### Testing Approach
- **Test-Driven Development (TDD)**: Write tests alongside code
- **Comprehensive Coverage**: Aim for 80%+ code coverage
- **Fast Execution**: Complete test suite runs in < 2 minutes

### Test Organization
- **Unit Tests**: Fast, isolated tests for all components
- **Integration Tests**: Test workflows and component interactions
- **UI Tests**: Test user interactions with pytest-qt

### Coverage Goals
- Overall: 80%+
- Critical Paths: 95%+ (services, processors, commands)
- UI Components: 70%+
- Utilities: 90%+

See [TESTING_STRATEGY.md](TESTING_STRATEGY.md) for complete test plan.

## 🚀 Planned Features

### Phase 1: MVP (Minimum Viable Product)
- Image import and viewing
- Basic adjustments (exposure, contrast, saturation)
- Undo/redo
- Image export
- Simple library view

### Phase 2: Core Editing
- Advanced adjustments (highlights, shadows, curves)
- Detail enhancement (sharpening, noise reduction)
- Transform tools (crop, rotate, straighten)
- Preset filters
- Project save/load

### Phase 3: Workflow Enhancement
- Batch operations
- Metadata management
- Organization tools (tags, ratings)
- Local adjustments (gradient, radial, brush)
- Lens corrections

### Phase 4: Advanced Features
- HDR processing
- Panorama stitching
- GPU acceleration
- Customizable UI
- Plugin system

See [FEATURES_PLAN.md](FEATURES_PLAN.md) for complete feature list.

## 📦 Installation

### Prerequisites
- Python 3.10+
- pipenv (recommended) or pip

### Setup
```bash
# Install dependencies
pipenv install

# Install dev dependencies
pipenv install --dev

# Activate virtual environment
pipenv shell
```

## 🧪 Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/unit/test_image_service.py

# Run with verbose output
pytest -v
```

## 📁 Project Structure

```
PhotoEdit/
├── src/                    # Source code
│   ├── models/            # Data models
│   ├── views/             # UI components
│   ├── controllers/       # Business logic
│   ├── services/          # Core services
│   ├── commands/          # Command pattern
│   ├── processors/        # Image processing
│   └── utils/             # Utilities
├── tests/                 # Test suite
│   ├── unit/             # Unit tests
│   ├── integration/      # Integration tests
│   └── ui/               # UI tests
├── resources/            # Resources (icons, styles, themes)
└── docs/                 # Documentation
```

## 🛠️ Development Guidelines

### Development Workflow
- **Test-Driven Development**: Write tests before or alongside code
- **Feature Commits**: Commit each feature when complete with tests
- **Atomic Commits**: One logical change per commit
- **Clear Messages**: Descriptive commit messages following conventional format

### Code Style
- Follow PEP 8
- Use type hints
- Document all public APIs
- Write tests for all features

### Commit Messages
- Use clear, descriptive messages
- Reference issue numbers when applicable
- Follow conventional commits format
- Include tests in commit message

**See [DEVELOPMENT_WORKFLOW.md](DEVELOPMENT_WORKFLOW.md) for complete workflow guidelines.**

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🤝 Contributing

[Contributing guidelines to be added]

## 📞 Contact

[Contact information to be added]

---

**Note**: This project is in the planning phase. Implementation will begin after architecture and design review.
