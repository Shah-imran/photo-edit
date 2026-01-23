# PhotoEdit - UI/UX Design Guidelines
## Lightroom-like Professional Interface Design

---

## 1. Design Philosophy

### Core Principles
- **Professional & Clean**: Minimal, distraction-free interface
- **Dark Theme First**: Professional dark interface (Lightroom Classic style)
- **Efficient Workflow**: Everything accessible within 2-3 clicks
- **Visual Hierarchy**: Clear focus on the image being edited
- **Consistent Spacing**: Generous padding and consistent margins
- **Smooth Animations**: Subtle transitions for professional feel

---

## 2. Color Palette

### Dark Theme (Primary)
```
Background (Main):        #1a1a1a (Very dark gray)
Background (Panels):      #242424 (Dark gray)
Background (Cards):       #2d2d2d (Medium dark gray)
Border/Divider:           #3a3a3a (Medium gray)
Text (Primary):           #e0e0e0 (Light gray)
Text (Secondary):         #a0a0a0 (Medium gray)
Text (Disabled):          #606060 (Dark gray)

Accent (Primary):         #0078d4 (Blue - Lightroom-like)
Accent (Hover):           #0086f0 (Lighter blue)
Accent (Active):          #005a9e (Darker blue)

Success:                  #107c10 (Green)
Warning:                  #ffb900 (Yellow)
Error:                    #d13438 (Red)
```

### Light Theme (Optional)
```
Background (Main):        #f5f5f5 (Light gray)
Background (Panels):      #ffffff (White)
Background (Cards):       #fafafa (Off-white)
Border/Divider:           #e0e0e0 (Light gray)
Text (Primary):           #1a1a1a (Dark gray)
Text (Secondary):         #606060 (Medium gray)
Text (Disabled):          #a0a0a0 (Light gray)

Accent (Primary):         #0078d4 (Blue)
Accent (Hover):           #0086f0 (Lighter blue)
Accent (Active):          #005a9e (Darker blue)
```

---

## 3. Layout Structure

### Main Window Layout (Lightroom-like)

```
┌─────────────────────────────────────────────────────────────────┐
│ Menu Bar                                                         │
├──────────┬──────────────────────────────────────┬────────────────┤
│          │                                      │                │
│ Library  │         Image View Area              │  Tool Panels   │
│ Panel    │         (Main Canvas)                │  (Right Side)  │
│ (Left)   │                                      │                │
│          │                                      │                │
│ - Grid   │                                      │ - Basic        │
│ - Folders│                                      │ - Tone Curve   │
│ - Filters│                                      │ - Color        │
│          │                                      │ - Detail       │
│          │                                      │ - Effects      │
│          │                                      │                │
│          │                                      │                │
├──────────┴──────────────────────────────────────┴────────────────┤
│ Status Bar / Histogram                                            │
└─────────────────────────────────────────────────────────────────┘
```

### Panel Organization
- **Left Panel (Library)**: 250-300px width, collapsible
- **Center (Image View)**: Flexible, takes remaining space
- **Right Panel (Tools)**: 320-350px width, collapsible
- **Bottom (Histogram/Status)**: 100-120px height, collapsible

---

## 4. Typography

### Font Stack
```python
Primary Font: "Segoe UI" (Windows), "SF Pro Display" (macOS), "Roboto" (Linux)
Monospace: "Consolas", "Monaco", "Courier New"
```

### Font Sizes
- **Window Title**: 14px, Semi-bold
- **Panel Headers**: 13px, Semi-bold
- **Section Headers**: 12px, Medium
- **Body Text**: 11px, Regular
- **Labels**: 10px, Regular
- **Tooltips**: 10px, Regular

### Font Weights
- Regular: 400
- Medium: 500
- Semi-bold: 600
- Bold: 700

---

## 5. Component Design Specifications

### 5.1 Sliders (Adjustment Controls)

**Design:**
- Height: 24px
- Track: 2px height, rounded
- Thumb: 12px diameter circle
- Active area: Full width clickable
- Value display: Right-aligned, 60px width, 11px font

**Behavior:**
- Smooth dragging with visual feedback
- Double-click to reset to default
- Right-click for context menu (reset, copy, paste)
- Keyboard: Arrow keys for fine adjustment (1 unit), Shift+Arrow for coarse (10 units)

**Visual States:**
- Normal: Gray track, blue thumb
- Hover: Slightly brighter thumb
- Active: Brighter blue thumb, track highlight
- Disabled: 50% opacity

### 5.2 Buttons

**Primary Button:**
- Height: 32px
- Padding: 12px horizontal
- Border radius: 4px
- Background: Accent color
- Text: White, 11px, Medium weight

**Secondary Button:**
- Height: 32px
- Padding: 12px horizontal
- Border radius: 4px
- Background: Transparent
- Border: 1px solid border color
- Text: Primary text color

**Icon Button:**
- Size: 32x32px
- Border radius: 4px
- Icon: 16x16px, centered
- Hover: Background highlight

### 5.3 Panels

**Panel Structure:**
```
┌─────────────────────────────┐
│ Panel Header (Collapsible)   │ ← 36px height
├─────────────────────────────┤
│                             │
│ Panel Content               │
│ (Scrollable if needed)      │
│                             │
└─────────────────────────────┘
```

**Panel Header:**
- Height: 36px
- Padding: 12px horizontal, 8px vertical
- Background: Slightly lighter than panel
- Border bottom: 1px divider
- Collapse icon: Right-aligned chevron

**Panel Content:**
- Padding: 12px all sides
- Spacing between sections: 16px
- Section divider: 1px border, 8px margin top/bottom

### 5.4 Image View

**Canvas:**
- Background: Checkerboard pattern (for transparency) or solid dark
- Smooth zoom with mouse wheel
- Pan with middle mouse button or space+drag
- Zoom indicators: Percentage display in status bar

**View Modes:**
- Fit to Window: Default
- 100%: Actual pixels
- Fit to Width: Full width
- Fit to Height: Full height

**Before/After:**
- Split view: Vertical or horizontal divider
- Toggle: Y key (Lightroom standard)
- Side-by-side: Two images side by side

### 5.5 Library View

**Grid View:**
- Thumbnail size: Configurable (small: 100px, medium: 150px, large: 200px)
- Spacing: 8px between thumbnails
- Selection: Blue border, 2px width
- Hover: Slight brightness increase

**List View:**
- Row height: 48px
- Columns: Thumbnail (64px), Name, Date, Size, Rating
- Alternating row colors for readability

### 5.6 Histogram

**Design:**
- Height: 80px
- Background: Dark with subtle grid
- Channels: RGB overlay (Red, Green, Blue)
- Luminance: White overlay
- Clipping indicators: Red (highlights), Blue (shadows)

---

## 6. Iconography

### Icon Style
- **Style**: Outline/minimal icons (similar to Lightroom)
- **Size**: 16x16px (standard), 24x24px (large)
- **Color**: Inherit text color, or accent color for active states

### Key Icons Needed
- Import/Export
- Undo/Redo
- Zoom (in/out/fit)
- Rotate/Flip
- Crop
- Before/After toggle
- Panel collapse/expand
- Settings/Preferences

---

## 7. Animations & Transitions

### Principles
- **Subtle**: Don't distract from content
- **Fast**: 150-300ms duration
- **Easing**: Ease-in-out for natural feel

### Specific Animations
- **Panel Toggle**: 200ms slide animation
- **Button Hover**: 150ms color transition
- **Slider Drag**: Immediate, no animation
- **Image Zoom**: Smooth interpolation, 300ms
- **Tooltip**: Fade in 200ms, fade out 150ms
- **Modal Dialogs**: Fade + scale, 250ms

---

## 8. Responsive Behavior

### Window Resizing
- **Minimum Width**: 1200px
- **Minimum Height**: 800px
- **Panel Collapse**: Auto-collapse side panels below 1400px width
- **Flexible Layout**: Image view adapts to available space

### High DPI Support
- **Scaling**: Automatic Qt scaling for 4K displays
- **Icons**: Provide @2x versions for retina displays
- **Fonts**: Use device pixel ratio for crisp text

---

## 9. Keyboard Shortcuts

### Standard Shortcuts (Lightroom-inspired)
```
File Operations:
  Ctrl+O          Open image
  Ctrl+Shift+O    Import images
  Ctrl+S          Save project
  Ctrl+E          Export
  Ctrl+W          Close image

Editing:
  Ctrl+Z          Undo
  Ctrl+Shift+Z    Redo
  Ctrl+R          Reset adjustments
  Ctrl+D          Duplicate

View:
  Space           Pan (when zoomed)
  + / -           Zoom in/out
  0               Fit to window
  1               100% view
  Y               Before/After toggle
  F               Fullscreen toggle
  Tab             Toggle panels

Navigation:
  ← →             Previous/Next image
  Home            First image
  End             Last image
```

---

## 10. UI Components Library

### Custom Widgets to Create

1. **AdjustmentSlider**
   - Custom slider with value display
   - Reset button
   - Keyboard navigation

2. **CollapsiblePanel**
   - Animated collapse/expand
   - Header with title and icon
   - Content area

3. **ImageThumbnail**
   - Thumbnail with selection state
   - Loading indicator
   - Rating overlay

4. **HistogramWidget**
   - Real-time histogram display
   - Channel toggles
   - Clipping indicators

5. **BeforeAfterView**
   - Split view widget
   - Draggable divider
   - Toggle modes

6. **ToneCurveWidget**
   - Interactive curve editor
   - Channel selection
   - Preset buttons

---

## 11. Styling Implementation

### PyQt6 Stylesheet Approach

**Base Stylesheet Structure:**
```python
STYLESHEET = """
QMainWindow {
    background-color: #1a1a1a;
    color: #e0e0e0;
}

QPanel {
    background-color: #242424;
    border: none;
}

QSlider::groove:horizontal {
    height: 2px;
    background: #3a3a3a;
    border-radius: 1px;
}

QSlider::handle:horizontal {
    width: 12px;
    height: 12px;
    background: #0078d4;
    border-radius: 6px;
    margin: -5px 0;
}
"""
```

### Theme Manager
- Centralized theme management
- Support for multiple themes
- Runtime theme switching
- User preference storage

---

## 12. Accessibility

### Requirements
- **Keyboard Navigation**: Full keyboard support
- **High Contrast**: Support for high contrast mode
- **Screen Readers**: Proper widget labels and roles
- **Focus Indicators**: Clear focus rectangles
- **Color Blind**: Don't rely solely on color for information

---

## 13. Implementation Priority

### Phase 1: Core UI
- Main window layout
- Basic panels (Library, Tools, Image View)
- Dark theme
- Basic controls (sliders, buttons)

### Phase 2: Polish
- Animations
- Custom widgets
- Histogram
- Before/After view

### Phase 3: Advanced
- Light theme
- Customizable layout
- Advanced widgets (tone curve, etc.)
- Full keyboard shortcuts

---

## 14. Design Resources

### Reference Applications
- Adobe Lightroom Classic (primary reference)
- Capture One (alternative reference)
- Darktable (open-source reference)

### Tools
- Qt Designer for initial layouts
- Figma/Sketch for mockups (optional)
- Color picker tools for palette

---

## Notes

- All measurements in pixels
- Design for 1920x1080 minimum, scale up gracefully
- Test on multiple screen sizes and DPI settings
- Gather user feedback early and iterate
- Maintain consistency across all views
