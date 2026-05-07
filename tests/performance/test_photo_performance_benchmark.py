"""Executable performance checks for the modern rendering pipeline."""

from src.benchmarking.photo_performance import run_benchmarks


def _result_by_name(report):
    return {item["name"]: item for item in report["results"]}


class TestPhotoPerformanceBenchmark:
    """Smoke-level performance checks that guard benchmark wiring."""

    def test_smoke_profile_has_reasonable_display_cost(self):
        report = run_benchmarks("smoke")
        results = _result_by_name(report)

        assert results["display_rgb_interactive"]["median_ms"] < 10.0
        assert results["apply_exposure_interactive"]["median_ms"] < 10.0

    def test_smoke_profile_tracks_contrast_separately(self):
        report = run_benchmarks("smoke")
        results = _result_by_name(report)

        assert "apply_contrast_interactive" in results
        assert "apply_contrast_quality" in results
        assert results["apply_contrast_interactive"]["median_ms"] >= 0.0
