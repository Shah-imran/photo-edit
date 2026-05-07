"""Tests for the PhotoEdit benchmark harness."""

from src.benchmarking.photo_performance import compare_reports, run_benchmarks


def test_smoke_benchmark_report_schema():
    """The benchmark harness should emit stable machine-readable reports."""
    report = run_benchmarks("smoke")

    assert report["schema_version"] == 1
    assert report["profile"] == "smoke"
    assert "created_at" in report
    assert "system" in report
    assert len(report["results"]) >= 6

    names = {item["name"] for item in report["results"]}
    assert "display_rgb_interactive" in names
    assert "apply_exposure_interactive" in names
    assert "apply_contrast_quality" in names

    for item in report["results"]:
        assert item["median_ms"] >= 0.0
        assert item["min_ms"] >= 0.0
        assert item["max_ms"] >= item["min_ms"]
        assert len(item["samples_ms"]) == item["repeats"]


def test_compare_reports_matches_named_benchmarks():
    """Reports can be compared across implementation phases."""
    baseline = {
        "results": [
            {"name": "display_rgb_interactive", "median_ms": 10.0},
            {"name": "apply_exposure_interactive", "median_ms": 5.0},
        ]
    }
    current = {
        "results": [
            {"name": "display_rgb_interactive", "median_ms": 2.5},
            {"name": "new_metric", "median_ms": 1.0},
        ]
    }

    comparison = compare_reports(current, baseline)

    assert comparison == [
        {
            "name": "display_rgb_interactive",
            "baseline_ms": 10.0,
            "current_ms": 2.5,
            "ratio": 0.25,
            "delta_ms": -7.5,
        }
    ]
