# PhotoEdit - Lightroom-like Photo Editing Application

A professional photo editing application built with Python and PyQt6, inspired by Adobe Lightroom Classic.

## 📋 Project Status

**Active development** — Architecture and planning docs live under [`docs/`](docs/README.md).

## 📚 Documentation

| Doc | Purpose |
|-----|---------|
| **[docs/README.md](docs/README.md)** | Index of all documentation |
| **[docs/planning/PRODUCT_ROADMAP.md](docs/planning/PRODUCT_ROADMAP.md)** | Lightroom-aligned phases, full feature catalog, and delivery milestones (single merged roadmap) |
| **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** | Architecture, patterns, project structure |
| **[docs/UI_UX.md](docs/UI_UX.md)** | UI/UX guidelines |
| **[docs/TESTING.md](docs/TESTING.md)** | Testing strategy |
| **[docs/DEVELOPMENT_WORKFLOW.md](docs/DEVELOPMENT_WORKFLOW.md)** | Git and TDD workflow |
| **[docs/PERFORMANCE.md](docs/PERFORMANCE.md)** | Performance architecture notes |
| **[docs/planning/INCREMENTAL_WORKFLOW.md](docs/planning/INCREMENTAL_WORKFLOW.md)** | Phase dependencies; **mandatory detailed pre-implementation plan (section 4)**; test gates; persistence (6); professional shell (6.1); logging |

## Run the application

From the **repository root** (`PhotoEdit/`), with dependencies installed:

```bash
pipenv run python -m src.main
```

If you already activated the virtual environment (`pipenv shell`):

```bash
python -m src.main
```

**Windows (PowerShell):** use the same commands from the project root. The Qt window must run on a machine with a display (not headless).

**What you should see:** the main window with Library (left), image area (center), and Adjustments (right). Use **File → Open Image** to load a JPEG or PNG.

---

## First development steps (recommended order)

Aligned with [docs/planning/INCREMENTAL_WORKFLOW.md](docs/planning/INCREMENTAL_WORKFLOW.md):

1. **Smoke run** -- Run the app and open a sample image; confirm sliders and undo work.
2. **Run tests** -- `pipenv run pytest` (fix any failures before new work).
3. **Optional early slice:** **App settings** (`QSettings` + `SettingsService`) for last open/export paths and window state -- see [INCREMENTAL_WORKFLOW.md](docs/planning/INCREMENTAL_WORKFLOW.md) section 6; style and layout stay swappable per section 5.1 in that doc. **Write the full detailed plan (section 4) and approve it before coding.**
4. **K0 (first real slice)** -- Add an **approved** implementation note under `docs/planning/implementation-notes/` for the **versioned adjustment / project JSON schema** (contract only, minimal code if any), following **section 4.1** depth in the workflow doc.
5. **Validate K0** -- Review the note; agree on field names and `version` before **Phase B / K** persistence or copy-paste settings.
6. **Next smallest feature** -- e.g. one library improvement from Phase A (sort by name) or RAW open dialog (Phase C), each with its own note + tests before merge.

See [docs/planning/PRODUCT_ROADMAP.md](docs/planning/PRODUCT_ROADMAP.md) Part 1 for the full phase list.

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

See [docs/UI_UX.md](docs/UI_UX.md) for complete design specifications.

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

See [docs/TESTING.md](docs/TESTING.md) for complete test plan.

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

See [docs/planning/PRODUCT_ROADMAP.md](docs/planning/PRODUCT_ROADMAP.md#part-2-feature-planning-catalog) for the full feature catalog.

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

The **Run the application** section above describes how to start the GUI after this setup.

## 🧪 Running Tests

```bash
# Run all tests (from repo root; same environment as the app)
pipenv run pytest

# Run with coverage
pipenv run pytest --cov=src --cov-report=html

# Run specific test file
pipenv run pytest tests/unit/test_image_service.py

# Run with verbose output
pipenv run pytest -v
```

If you are already inside `pipenv shell`, you can run `pytest` without the `pipenv run` prefix.

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
└── docs/                 # All documentation (see docs/README.md)
    ├── planning/         # Product roadmap (merged feature + Lightroom phases)
    ├── ARCHITECTURE.md
    ├── UI_UX.md
    ├── TESTING.md
    ├── DEVELOPMENT_WORKFLOW.md
    └── PERFORMANCE.md
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

**See [docs/DEVELOPMENT_WORKFLOW.md](docs/DEVELOPMENT_WORKFLOW.md) for complete workflow guidelines.**

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🤝 Contributing

[Contributing guidelines to be added]

## 📞 Contact

[Contact information to be added]

---

**Note**: Planning and roadmap documents are under [`docs/`](docs/README.md); the app is under active development in `src/`.
