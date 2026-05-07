"""Repeatable benchmark harness for the photo rendering pipeline."""

from __future__ import annotations

import argparse
import json
import platform
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Callable, Dict, Iterable, Optional

import numpy as np

from src.processing.display_frame import DisplayFrame, linear_to_display_rgb
from src.processing.processing_worker import ProcessingWorker


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "logs" / "benchmarks"


@dataclass(frozen=True)
class BenchmarkProfile:
    """Benchmark profile sizing and repetition policy."""

    name: str
    interactive_size: tuple[int, int]
    quality_size: tuple[int, int]
    full_size: Optional[tuple[int, int]]
    repeats: int
    warmups: int
    include_view: bool


PROFILES: Dict[str, BenchmarkProfile] = {
    "smoke": BenchmarkProfile(
        name="smoke",
        interactive_size=(120, 80),
        quality_size=(240, 160),
        full_size=None,
        repeats=1,
        warmups=0,
        include_view=False,
    ),
    "quick": BenchmarkProfile(
        name="quick",
        interactive_size=(600, 400),
        quality_size=(1400, 934),
        full_size=None,
        repeats=5,
        warmups=1,
        include_view=True,
    ),
    "full": BenchmarkProfile(
        name="full",
        interactive_size=(600, 400),
        quality_size=(1400, 934),
        full_size=(6264, 4180),
        repeats=3,
        warmups=1,
        include_view=True,
    ),
}


def gradient_linear(width: int, height: int) -> np.ndarray:
    """Create a deterministic linear-light RGB gradient image."""
    x = np.linspace(0.02, 0.92, width, dtype=np.float32)
    y = np.linspace(0.08, 0.85, height, dtype=np.float32)
    xx, yy = np.meshgrid(x, y)
    return np.stack(
        [
            xx,
            yy,
            np.clip((xx * 0.55) + (yy * 0.45), 0.0, 1.0),
        ],
        axis=-1,
    ).astype(np.float32, copy=False)


def measure_ms(
    name: str,
    func: Callable[[], object],
    *,
    repeats: int,
    warmups: int,
) -> dict:
    """Measure one benchmark callable and return timing statistics."""
    for _ in range(warmups):
        func()

    samples = []
    for _ in range(repeats):
        start = perf_counter()
        func()
        samples.append((perf_counter() - start) * 1000.0)

    return {
        "name": name,
        "samples_ms": samples,
        "median_ms": median(samples),
        "min_ms": min(samples),
        "max_ms": max(samples),
        "repeats": repeats,
        "warmups": warmups,
    }


def run_benchmarks(profile: str = "quick") -> dict:
    """Run a benchmark profile and return a JSON-serializable report."""
    if profile not in PROFILES:
        raise ValueError(
            f"Unknown profile '{profile}'. Expected one of: {', '.join(PROFILES)}"
        )

    bench_profile = PROFILES[profile]
    worker = ProcessingWorker()

    results = []
    images = {
        "interactive": gradient_linear(*bench_profile.interactive_size),
        "quality": gradient_linear(*bench_profile.quality_size),
    }
    if bench_profile.full_size is not None:
        images["full"] = gradient_linear(*bench_profile.full_size)

    for tier, image in images.items():
        repeats = 1 if tier == "full" else bench_profile.repeats
        warmups = 0 if tier == "full" else bench_profile.warmups
        results.append(
            measure_ms(
                f"display_rgb_{tier}",
                lambda image=image: linear_to_display_rgb(image),
                repeats=repeats,
                warmups=warmups,
            )
        )
        results.append(
            measure_ms(
                f"apply_exposure_{tier}",
                lambda image=image: worker._apply_adjustments(
                    image,
                    {"exposure": 1.0, "contrast": 0.0, "brightness": 0.0},
                    {"saturation": 0.0, "vibrance": 0.0},
                ),
                repeats=repeats,
                warmups=warmups,
            )
        )
        results.append(
            measure_ms(
                f"apply_contrast_{tier}",
                lambda image=image: worker._apply_adjustments(
                    image,
                    {"exposure": 0.0, "contrast": 40.0, "brightness": 0.0},
                    {"saturation": 0.0, "vibrance": 0.0},
                ),
                repeats=repeats,
                warmups=warmups,
            )
        )

    if bench_profile.include_view:
        results.extend(_run_view_benchmarks(images, bench_profile))

    return {
        "schema_version": 1,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "profile": bench_profile.name,
        "system": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor(),
        },
        "results": results,
    }


def _run_view_benchmarks(
    images: Dict[str, np.ndarray],
    bench_profile: BenchmarkProfile,
) -> list[dict]:
    """Benchmark the GUI-thread display handoff."""
    from PyQt6.QtWidgets import QApplication

    from src.views.image_view import ImageView

    app = QApplication.instance() or QApplication([])
    view = ImageView()
    results = []

    for tier in ("interactive", "quality"):
        image = images[tier]
        frame = DisplayFrame.from_linear(0, tier, (), image)

        def present(frame=frame, view=view):
            view.set_display_frame(frame, preserve_view_scale=True)
            app.processEvents()

        results.append(
            measure_ms(
                f"view_present_{tier}",
                present,
                repeats=bench_profile.repeats,
                warmups=bench_profile.warmups,
            )
        )

    view.close()
    return results


def write_report(report: dict, output_dir: Path = DEFAULT_OUTPUT_DIR) -> Path:
    """Write a benchmark report to disk and return the path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    created = report["created_at"].replace(":", "").replace("-", "")
    path = output_dir / f"photo_performance_{report['profile']}_{created}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    latest = output_dir / f"latest_{report['profile']}.json"
    latest.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def compare_reports(current: dict, baseline: dict) -> list[dict]:
    """Compare benchmark medians by name."""
    baseline_by_name = {item["name"]: item for item in baseline.get("results", [])}
    comparisons = []
    for current_item in current.get("results", []):
        baseline_item = baseline_by_name.get(current_item["name"])
        if baseline_item is None:
            continue
        baseline_ms = float(baseline_item["median_ms"])
        current_ms = float(current_item["median_ms"])
        ratio = current_ms / baseline_ms if baseline_ms > 0 else None
        comparisons.append(
            {
                "name": current_item["name"],
                "baseline_ms": baseline_ms,
                "current_ms": current_ms,
                "ratio": ratio,
                "delta_ms": current_ms - baseline_ms,
            }
        )
    return comparisons


def _print_summary(report: dict, comparisons: Optional[Iterable[dict]] = None) -> None:
    print(f"PhotoEdit benchmark profile={report['profile']}")
    for item in report["results"]:
        print(
            f"{item['name']}: median={item['median_ms']:.2f}ms "
            f"min={item['min_ms']:.2f}ms max={item['max_ms']:.2f}ms"
        )
    if comparisons is not None:
        print("\nComparison")
        for item in comparisons:
            ratio = item["ratio"]
            ratio_text = "n/a" if ratio is None else f"{ratio:.2f}x"
            print(
                f"{item['name']}: baseline={item['baseline_ms']:.2f}ms "
                f"current={item['current_ms']:.2f}ms ratio={ratio_text}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES),
        default="quick",
        help="Benchmark size/repetition profile.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for JSON benchmark reports.",
    )
    parser.add_argument(
        "--compare-to",
        type=Path,
        default=None,
        help="Optional previous JSON report to compare against.",
    )
    args = parser.parse_args()

    baseline = None
    if args.compare_to is not None:
        baseline = json.loads(args.compare_to.read_text(encoding="utf-8"))
    report = run_benchmarks(args.profile)
    path = write_report(report, args.output_dir)
    comparisons = None
    if baseline is not None:
        comparisons = compare_reports(report, baseline)
    _print_summary(report, comparisons)
    print(f"\nWrote {path}")


if __name__ == "__main__":
    main()
