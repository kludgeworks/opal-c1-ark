# SPDX-License-Identifier: MIT
"""Unit tests for the telemetry logger, terminal sparklines, and visual HTML/SVG report generator."""

import csv
import json
import pathlib
import pytest
from tools.test_harness.telemetry import (
    TelemetryRecorder,
    sparkline,
)


@pytest.mark.offline
def test_sparkline_generator():
    """Sparkline must handle empty, flat, ascending, and descending data correctly."""
    assert sparkline([], length=10) == " " * 10

    flat = sparkline([5.0, 5.0, 5.0, 5.0], length=4)
    assert len(flat) == 4

    asc = sparkline([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0], length=8)
    assert len(asc) == 8
    assert asc[0] == " "
    assert asc[-1] == "█"


@pytest.mark.offline
def test_telemetry_csv_export(tmp_path: pathlib.Path):
    """TelemetryRecorder must export valid RFC-4180 CSV with all required metric columns."""
    recorder = TelemetryRecorder()
    for i in range(10):
        recorder.record(
            timestamp_sec=i * 0.033,
            fps=30.0,
            bitrate_mbps=24.8,
            frame_size_kib=102.4,
            is_keyframe=(i % 30 == 0),
            temp_avg_c=48.5,
            temp_css_c=49.0,
            temp_mss_c=48.0,
            ddr_used_mib=52.0,
            cmx_used_mib=1.2,
            cpu_css_pct=15.0,
            cpu_mss_pct=10.0,
        )

    csv_file = tmp_path / "test_telemetry.csv"
    exported = recorder.export_csv(csv_file)
    assert exported.exists()

    with open(csv_file, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 10
    assert "timestamp_sec" in rows[0]
    assert "fps" in rows[0]
    assert "bitrate_mbps" in rows[0]
    assert "temp_avg_c" in rows[0]
    assert float(rows[0]["fps"]) == 30.0


@pytest.mark.offline
def test_telemetry_json_summary_export(tmp_path: pathlib.Path):
    """TelemetryRecorder must compute accurate min/max/avg summary in JSON."""
    recorder = TelemetryRecorder()
    recorder.record(timestamp_sec=0.0, fps=28.0, bitrate_mbps=20.0, temp_avg_c=45.0)
    recorder.record(timestamp_sec=1.0, fps=30.0, bitrate_mbps=25.0, temp_avg_c=50.0)
    recorder.record(timestamp_sec=2.0, fps=32.0, bitrate_mbps=30.0, temp_avg_c=55.0)

    json_file = tmp_path / "test_telemetry.json"
    exported = recorder.export_json(json_file)
    assert exported.exists()

    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    summary = data["summary"]
    assert summary["sample_count"] == 3
    assert summary["fps_avg"] == 30.0
    assert summary["fps_min"] == 28.0
    assert summary["fps_max"] == 32.0
    assert summary["bitrate_avg_mbps"] == 25.0
    assert summary["temp_avg_c"] == 50.0
    assert len(data["samples"]) == 3


@pytest.mark.offline
def test_telemetry_html_report_generation(tmp_path: pathlib.Path):
    """TelemetryRecorder must generate standalone, valid HTML with embedded SVG charts."""
    recorder = TelemetryRecorder()
    for i in range(20):
        recorder.record(
            timestamp_sec=i * 0.1,
            fps=29.5 + (i % 2) * 0.5,
            bitrate_mbps=24.5 + (i % 3) * 0.3,
            temp_avg_c=48.0 + i * 0.1,
            cpu_css_pct=15.0 + i * 0.2,
        )

    html_file = tmp_path / "test_report.html"
    exported = recorder.generate_html_report(html_file, title="Test Benchmark Run")
    assert exported.exists()

    content = exported.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content
    assert "<svg" in content
    assert "Framerate Stability" in content
    assert "4K H.265 Bitrate" in content
    assert "Silicon Thermal Curves" in content
    assert "Test Benchmark Run" in content
