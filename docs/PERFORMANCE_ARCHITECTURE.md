# Performance Architecture

This document describes the technical architecture for achieving smooth, responsive image processing in PhotoEdit.

## Problem Statement

**Issue**: Slider adjustments feel sluggish - the UI lags and effects appear late.

**Root Cause**: Image processing happens synchronously on the main UI thread. Every slider value change triggers full-resolution image processing, blocking the UI until complete.

**Impact on Large Images**:

| Image Size | Pixels | Approx. Processing Time (CPU) |
|------------|--------|-------------------------------|
| 1080p | 2MP | ~50ms |
| 4K | 8MP | ~150ms |
| 24MP (DSLR) | 24MP | ~400-800ms |
| 50MP (High-end) | 50MP | ~1-2 seconds |

At 24MP, even a fast CPU cannot provide smooth 60fps (16ms) or even 30fps (33ms) feedback.

---

## Solution: Background Threading with Proxy Images

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Main UI Thread                               │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐   │
│  │   Slider     │───▶│  Debouncer   │───▶│  Processing Request  │   │
│  │  Movement    │    │  (50-100ms)  │    │       Queue          │   │
│  └──────────────┘    └──────────────┘    └──────────┬───────────┘   │
│                                                      │               │
│  ┌──────────────┐                                   │               │
│  │   Display    │◀──────────────────────────────────┼───────────┐   │
│  │   Update     │    (Signal: processing_complete)  │           │   │
│  └──────────────┘                                   │           │   │
└─────────────────────────────────────────────────────┼───────────┼───┘
                                                      │           │
┌─────────────────────────────────────────────────────┼───────────┼───┐
│                      Worker Thread                   │           │   │
│                                                      ▼           │   │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐   │   │
│  │ Proxy Image  │───▶│  Processor   │───▶│  Result Cache    │───┘   │
│  │   Cache      │    │  (Fast)      │    │                  │       │
│  └──────────────┘    └──────────────┘    └──────────────────┘       │
└─────────────────────────────────────────────────────────────────────┘
```

### Key Components

#### 1. Debouncer (`src/utils/debouncer.py`)
- Delays processing until slider movement pauses (50-100ms)
- Prevents flooding the queue with requests
- Uses QTimer for Qt integration
- Configurable delay time

#### 2. Proxy Image System (`src/processing/proxy_manager.py`)
- Maintains a low-resolution copy (1000-1500px wide)
- ~35x fewer pixels = ~35x faster processing
- Automatically created when image is loaded
- Full-resolution processing on slider release

#### 3. Processing Worker (`src/processing/processing_worker.py`)
- QThread-based background processing
- Receives requests via thread-safe queue
- Communicates results via Qt signals
- Supports request cancellation

#### 4. Processing Queue (`src/processing/processing_queue.py`)
- Thread-safe queue for processing requests
- Supports request cancellation (discard outdated requests)
- Priority handling (latest request takes precedence)
- Request versioning to detect stale requests

---

## Signal Flow

### During Slider Movement (Live Preview)

1. User moves slider continuously
2. Each tick triggers debouncer (resets timer)
3. After 50ms pause, debouncer fires
4. Request queued for **proxy image** processing
5. Worker processes proxy (fast, ~20-50ms)
6. Signal emitted with preview result
7. UI updates with preview

### On Slider Release (Final Render)

1. User releases slider
2. Request queued for **full resolution** processing
3. Worker processes full image (background)
4. Signal emitted with final result
5. UI updates with high-quality result

---

## Threading Rules

1. **Never modify QWidget from worker thread** - Always use signals
2. **PIL Images are not thread-safe for writes** - Copy before processing
3. **NumPy arrays can be shared** - But careful with concurrent writes
4. **Cancel stale requests** - Check request validity before processing

---

## Directory Structure

```
src/
  processing/
    __init__.py
    processing_worker.py      # QThread-based worker
    processing_queue.py       # Request queue with cancellation
    proxy_manager.py          # Proxy image creation/caching
  utils/
    __init__.py
    debouncer.py              # QTimer-based debouncer
```

---

## Performance Targets

| Scenario | Before | After (Threading) |
|----------|--------|-------------------|
| 24MP slider feedback | 400-800ms | 20-50ms (proxy) |
| 24MP final render | 400-800ms (blocking) | 400-800ms (background) |
| UI responsiveness | Blocked | Smooth |

---

## Future: GPU Acceleration

The architecture is designed to support GPU acceleration in the future:

1. **Abstract processor interface** - BaseProcessor pattern already exists
2. **NumPy-based pipeline** - GPU libraries work well with arrays
3. **Batch operations** - Process multiple adjustments in one GPU call

### GPU Options

| Library | Platform | Notes |
|---------|----------|-------|
| OpenCV CUDA | NVIDIA | Well-documented |
| CuPy | NVIDIA | NumPy-compatible API |
| PyOpenCL | Cross-platform | Lower-level |
| Metal (PyObjC) | macOS | Native performance |

### GPU Integration Point

The `ProcessingWorker` can be extended to detect GPU availability and route to appropriate processor:

```
ProcessingRouter
    ├── GPU available? → GPUProcessor
    └── Fallback → CPUProcessor (current)
```

This allows transparent GPU acceleration without changing the rest of the architecture.

---

## GPU Abstraction Layer Design

When GPU acceleration is needed, the following abstraction layer enables seamless switching between CPU and GPU processing.

### Interface Design

```python
from abc import ABC, abstractmethod
from PIL import Image
from typing import Dict, Any

class IProcessingBackend(ABC):
    """Abstract interface for processing backends (CPU/GPU)."""
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if this backend is available."""
        pass
    
    @abstractmethod
    def get_name(self) -> str:
        """Get backend name for logging/display."""
        pass
    
    @abstractmethod
    def process_exposure(
        self,
        image: Image.Image,
        exposure: float = 0.0,
        contrast: float = 0.0,
        brightness: float = 0.0
    ) -> Image.Image:
        """Apply exposure adjustments."""
        pass
    
    @abstractmethod
    def process_color(
        self,
        image: Image.Image,
        saturation: float = 0.0,
        vibrance: float = 0.0
    ) -> Image.Image:
        """Apply color adjustments."""
        pass
```

### Backend Implementations

```python
class CPUBackend(IProcessingBackend):
    """CPU-based processing using PIL/NumPy."""
    
    def is_available(self) -> bool:
        return True  # Always available
    
    def get_name(self) -> str:
        return "CPU (NumPy/PIL)"
    
    # ... implementation using existing processors

class CUDABackend(IProcessingBackend):
    """GPU-based processing using OpenCV CUDA."""
    
    def is_available(self) -> bool:
        try:
            import cv2
            return cv2.cuda.getCudaEnabledDeviceCount() > 0
        except:
            return False
    
    def get_name(self) -> str:
        return "GPU (CUDA)"
    
    # ... implementation using cv2.cuda

class OpenCLBackend(IProcessingBackend):
    """GPU-based processing using PyOpenCL."""
    
    def is_available(self) -> bool:
        try:
            import pyopencl as cl
            platforms = cl.get_platforms()
            return len(platforms) > 0
        except:
            return False
    
    def get_name(self) -> str:
        return "GPU (OpenCL)"
    
    # ... implementation using PyOpenCL
```

### Processing Router

```python
class ProcessingRouter:
    """Routes processing to best available backend."""
    
    def __init__(self):
        self._backends = [
            CUDABackend(),      # Prefer CUDA if available
            OpenCLBackend(),    # Then OpenCL
            CPUBackend(),       # Fallback to CPU
        ]
        self._active_backend = self._select_backend()
    
    def _select_backend(self) -> IProcessingBackend:
        for backend in self._backends:
            if backend.is_available():
                print(f"Using processing backend: {backend.get_name()}")
                return backend
        raise RuntimeError("No processing backend available")
    
    @property
    def backend(self) -> IProcessingBackend:
        return self._active_backend
    
    def process_exposure(self, image, **params):
        return self._active_backend.process_exposure(image, **params)
    
    def process_color(self, image, **params):
        return self._active_backend.process_color(image, **params)
```

### Integration Points

1. **ProcessingWorker**: Replace direct processor calls with router
2. **Settings**: Allow user to override backend selection
3. **Status Bar**: Show active backend in UI
4. **Benchmarking**: Auto-select based on image size and benchmarks

### GPU Memory Considerations

- Texture memory limits for large images
- Batch multiple adjustments to reduce transfers
- Keep proxy on GPU, transfer only for display
- Async transfer overlap with computation
