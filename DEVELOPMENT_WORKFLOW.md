# PhotoEdit - Development Workflow
## Feature Development & Git Workflow

---

## 🔄 Core Development Workflow

### For Every Feature:

```
1. Create Feature Branch
   ↓
2. Write Tests First (TDD)
   ↓
3. Implement Feature
   ↓
4. Ensure All Tests Pass
   ↓
5. Code Review & Refactor
   ↓
6. Commit Feature
   ↓
7. Push & Create PR (if applicable)
```

---

## 📝 Feature Development Process

### Step 1: Create Feature Branch

```bash
# Update main branch
git checkout main
git pull origin main

# Create feature branch
git checkout -b feature/feature-name

# Example:
git checkout -b feature/image-loading
git checkout -b feature/exposure-adjustment
git checkout -b feature/undo-redo
```

**Branch Naming Convention:**
- `feature/feature-name` - New features
- `fix/bug-description` - Bug fixes
- `refactor/component-name` - Code refactoring
- `test/test-description` - Test improvements

---

### Step 2: Write Tests First (TDD)

**Test-Driven Development Approach:**

1. **Write failing test** for the feature
2. **Run test** to confirm it fails (Red)
3. **Write minimal code** to make test pass (Green)
4. **Refactor** code while keeping tests passing (Refactor)

**Example:**
```python
# tests/unit/test_services/test_image_service.py

def test_load_image_valid_file():
    """Test loading a valid image file"""
    service = ImageService()
    image = service.load_image('test_image.jpg')
    assert image is not None
    assert image.width > 0
    assert image.height > 0

def test_load_image_invalid_file():
    """Test loading an invalid file raises error"""
    service = ImageService()
    with pytest.raises(FileNotFoundError):
        service.load_image('nonexistent.jpg')
```

**Test Requirements:**
- ✅ Unit tests for core logic
- ✅ Edge cases covered
- ✅ Error handling tested
- ✅ Integration tests if needed
- ✅ UI tests if user interaction involved

---

### Step 3: Implement Feature

**Implementation Guidelines:**

1. **Follow Architecture**: Use MVC + Service Layer pattern
2. **Follow Design Patterns**: Command, Observer, Strategy, etc.
3. **Follow UI Guidelines**: See UI_UX_DESIGN.md
4. **Write Clean Code**: PEP 8, type hints, docstrings
5. **Keep Tests Passing**: Run tests frequently during development

**Code Structure:**
```python
# src/services/image_service.py

from typing import Optional
from PIL import Image

class ImageService:
    """Service for image loading and processing operations."""
    
    def load_image(self, file_path: str) -> Optional[Image.Image]:
        """
        Load an image from file path.
        
        Args:
            file_path: Path to image file
            
        Returns:
            PIL Image object or None if loading fails
            
        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file is not a valid image
        """
        # Implementation
        pass
```

---

### Step 4: Ensure All Tests Pass

**Before committing, always:**

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=term

# Run specific test file (if working on specific feature)
pytest tests/unit/test_services/test_image_service.py -v

# Check for linting errors
# (Add linting tool if needed: flake8, pylint, black, etc.)
```

**Test Requirements:**
- ✅ All new tests pass
- ✅ All existing tests still pass
- ✅ Coverage meets targets (80%+ overall, 95%+ critical)
- ✅ No test warnings or errors

---

### Step 5: Code Review & Refactor

**Self-Review Checklist:**
- [ ] Code follows PEP 8 style guide
- [ ] Type hints added to all functions
- [ ] Docstrings for all classes and functions
- [ ] No commented-out code
- [ ] No debug print statements
- [ ] Error handling is comprehensive
- [ ] Code is DRY (Don't Repeat Yourself)
- [ ] Follows architecture patterns
- [ ] UI follows design guidelines (if applicable)

**Refactoring:**
- Clean up code while keeping tests green
- Extract common functionality
- Improve readability
- Optimize performance if needed

---

### Step 6: Commit Feature

**Commit Message Format:**

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `test`: Adding or updating tests
- `refactor`: Code refactoring
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `chore`: Maintenance tasks

**Examples:**

```bash
# Feature commit
git commit -m "feat(image-service): implement image loading

- Add ImageService.load_image() method
- Support JPEG, PNG, TIFF formats
- Add error handling for invalid files
- Include unit tests with 95% coverage

Closes #123"

# Test commit
git commit -m "test(image-service): add tests for image loading

- Test valid image loading
- Test invalid file handling
- Test unsupported format handling
- Achieve 100% coverage for load_image()"

# Fix commit
git commit -m "fix(image-view): fix zoom calculation bug

- Correct zoom factor calculation
- Fix boundary conditions
- Add test for edge cases

Fixes #124"
```

**Commit Best Practices:**
- ✅ One feature per commit
- ✅ Clear, descriptive commit message
- ✅ Include tests in same commit (or separate test commit first)
- ✅ Reference issue numbers if applicable
- ✅ Keep commits atomic (one logical change)

---

### Step 7: Push & Create PR (if applicable)

**For Feature Branches:**

```bash
# Push feature branch
git push origin feature/feature-name

# Create Pull Request (if using PR workflow)
# - Title: Clear feature description
# - Description: What was implemented, tests added, etc.
# - Link to related issues
```

**For Direct Commits to Main (if working solo):**

```bash
# Push directly to main (if appropriate)
git push origin main
```

---

## 🧪 Testing Workflow

### Test-First Development

**Always write tests before or alongside code:**

1. **Red Phase**: Write failing test
   ```python
   def test_exposure_adjustment():
       processor = ExposureProcessor()
       result = processor.adjust_exposure(image, 1.0)
       assert result.mean_brightness() > image.mean_brightness()
   ```

2. **Green Phase**: Write minimal code to pass
   ```python
   def adjust_exposure(self, image, value):
       # Minimal implementation
       return image  # Will fail test, need real implementation
   ```

3. **Refactor Phase**: Improve code while keeping tests green
   ```python
   def adjust_exposure(self, image, value):
       # Proper implementation with optimization
       # ... actual code ...
   ```

### Test Organization

**Tests should mirror source structure:**
```
src/services/image_service.py
  ↓
tests/unit/test_services/test_image_service.py
```

**Test Naming:**
- `test_<method>_<scenario>_<expected_result>`
- Example: `test_load_image_valid_file_returns_image`

### Running Tests During Development

```bash
# Watch mode (if available)
pytest-watch  # Auto-rerun tests on file changes

# Run specific test
pytest tests/unit/test_services/test_image_service.py::test_load_image -v

# Run with coverage for specific file
pytest tests/unit/test_services/test_image_service.py --cov=src.services.image_service
```

---

## 📦 Feature Completion Checklist

Before committing a feature:

### Code Quality
- [ ] Code follows PEP 8
- [ ] Type hints added
- [ ] Docstrings added
- [ ] No linting errors
- [ ] No warnings

### Testing
- [ ] Unit tests written and passing
- [ ] Integration tests (if applicable)
- [ ] UI tests (if applicable)
- [ ] Edge cases covered
- [ ] Error handling tested
- [ ] Coverage meets targets

### Functionality
- [ ] Feature works as expected
- [ ] Follows architecture patterns
- [ ] UI follows design guidelines (if applicable)
- [ ] Error messages are user-friendly
- [ ] Performance is acceptable

### Documentation
- [ ] Code is documented
- [ ] README updated (if needed)
- [ ] Architecture docs updated (if needed)
- [ ] Commit message is clear

### Git
- [ ] All changes staged
- [ ] Commit message follows format
- [ ] No unnecessary files committed
- [ ] .gitignore is up to date

---

## 🔀 Git Workflow Examples

### Example 1: Simple Feature

```bash
# 1. Create branch
git checkout -b feature/basic-slider

# 2. Write tests
# ... write test_slider_widget.py ...

# 3. Run tests (should fail)
pytest tests/unit/test_widgets/test_slider_widget.py

# 4. Implement feature
# ... implement SliderWidget ...

# 5. Run tests (should pass)
pytest tests/unit/test_widgets/test_slider_widget.py

# 6. Run all tests
pytest

# 7. Commit
git add .
git commit -m "feat(widgets): implement basic slider widget

- Add SliderWidget class with value display
- Support keyboard navigation
- Add reset functionality
- Include unit tests with 100% coverage"

# 8. Push
git push origin feature/basic-slider
```

### Example 2: Feature with Multiple Commits

```bash
# 1. Create branch
git checkout -b feature/exposure-adjustment

# 2. Write tests first
# ... write tests ...

# 3. Commit tests
git add tests/unit/test_processors/test_exposure_processor.py
git commit -m "test(exposure): add tests for exposure adjustment

- Test positive exposure adjustment
- Test negative exposure adjustment
- Test edge cases (min/max values)
- Test error handling"

# 4. Implement feature
# ... implement ExposureProcessor ...

# 5. Commit implementation
git add src/processors/exposure_processor.py
git commit -m "feat(processors): implement exposure adjustment

- Add ExposureProcessor class
- Support -5 to +5 stop range
- Non-destructive processing
- Real-time preview support"

# 6. Add UI component
# ... implement exposure slider ...

# 7. Commit UI
git add src/views/widgets/exposure_slider.py
git commit -m "feat(ui): add exposure adjustment slider

- Add ExposureSlider widget
- Connect to ExposureProcessor
- Real-time preview updates
- Include UI tests"

# 8. Run all tests
pytest

# 9. Push
git push origin feature/exposure-adjustment
```

---

## 🚫 What NOT to Commit

**Never commit:**
- ❌ Test images or large binary files
- ❌ Personal configuration files
- ❌ IDE-specific files (.idea/, .vscode/, etc.)
- ❌ Temporary files
- ❌ Debug code or print statements
- ❌ Commented-out code
- ❌ Secrets or API keys
- ❌ Generated files (unless necessary)

**Use .gitignore:**
```
# Python
__pycache__/
*.py[cod]
*.so
.Python
env/
venv/
.venv/

# IDE
.idea/
.vscode/
*.swp
*.swo

# Testing
.pytest_cache/
.coverage
htmlcov/

# Project specific
test_images/
*.tmp
*.log
```

---

## 📊 Progress Tracking

### Feature Status

Track feature development status:

- 🔴 **Not Started**: Feature not yet begun
- 🟡 **In Progress**: Feature being developed
- 🟢 **Complete**: Feature implemented, tested, and committed
- 🔵 **In Review**: Feature complete, awaiting review

### Example Feature Tracker

```markdown
## Phase 1 Features

- [x] Image loading (feat/image-loading) - 🟢 Complete
- [x] Basic slider widget (feat/basic-slider) - 🟢 Complete
- [ ] Exposure adjustment (feat/exposure-adjustment) - 🟡 In Progress
- [ ] Undo/redo system (feat/undo-redo) - 🔴 Not Started
```

---

## 🎯 Summary

**For Every Feature:**
1. ✅ Write tests first (TDD)
2. ✅ Implement feature
3. ✅ Ensure all tests pass
4. ✅ Code review and refactor
5. ✅ Commit with clear message
6. ✅ Push to repository

**Key Principles:**
- **Test-Driven**: Tests written before or alongside code
- **Atomic Commits**: One logical change per commit
- **Clear Messages**: Descriptive commit messages
- **Quality First**: All tests pass, code reviewed
- **Incremental**: Small, frequent commits

---

## 📚 Related Documents

- [TESTING_STRATEGY.md](TESTING_STRATEGY.md) - Complete testing approach
- [ARCHITECTURE_PLAN.md](ARCHITECTURE_PLAN.md) - Architecture guidelines
- [PROJECT_ROADMAP.md](PROJECT_ROADMAP.md) - Project phases and milestones

---

**Remember**: Tests and code go together. Every feature includes tests, and every feature gets committed when complete! 🚀
