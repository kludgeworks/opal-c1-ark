# SPDX-License-Identifier: MIT
"""Telemetry logging, CSV/JSON export, terminal sparklines, and offline HTML chart generation."""

import csv
import json
import math
import pathlib
from dataclasses import asdict, dataclass


SPARKLINE_BARS = " ▂▃▄▅▆▇█"


def sparkline(values: list[float], length: int = 20) -> str:
    """Generate a Unicode terminal sparkline string from a series of numbers."""
    if not values:
        return " " * length

    # Resample or take latest `length` values
    if len(values) > length:
        step = len(values) / length
        sampled = [values[int(i * step)] for i in range(length)]
    else:
        sampled = values

    min_val = min(sampled)
    max_val = max(sampled)
    val_range = max_val - min_val

    if val_range == 0:
        return SPARKLINE_BARS[3] * len(sampled)

    chars = []
    for v in sampled:
        idx = int(((v - min_val) / val_range) * (len(SPARKLINE_BARS) - 1))
        idx = max(0, min(len(SPARKLINE_BARS) - 1, idx))
        chars.append(SPARKLINE_BARS[idx])

    return "".join(chars)


@dataclass
class TelemetrySample:
    timestamp_sec: float
    fps: float
    bitrate_mbps: float
    frame_size_kib: float
    is_keyframe: bool
    temp_avg_c: float
    temp_css_c: float
    temp_mss_c: float
    ddr_used_mib: float
    cmx_used_mib: float
    cpu_css_pct: float
    cpu_mss_pct: float


class TelemetryRecorder:
    """Collects streaming performance & silicon telemetry, exporting to CSV, JSON, and HTML."""

    def __init__(self):
        self.samples: list[TelemetrySample] = []

    def record(
        self,
        timestamp_sec: float,
        fps: float = 0.0,
        bitrate_mbps: float = 0.0,
        frame_size_kib: float = 0.0,
        is_keyframe: bool = False,
        temp_avg_c: float = 0.0,
        temp_css_c: float = 0.0,
        temp_mss_c: float = 0.0,
        ddr_used_mib: float = 0.0,
        cmx_used_mib: float = 0.0,
        cpu_css_pct: float = 0.0,
        cpu_mss_pct: float = 0.0,
    ) -> None:
        self.samples.append(
            TelemetrySample(
                timestamp_sec=round(timestamp_sec, 3),
                fps=round(fps, 2),
                bitrate_mbps=round(bitrate_mbps, 3),
                frame_size_kib=round(frame_size_kib, 2),
                is_keyframe=is_keyframe,
                temp_avg_c=round(temp_avg_c, 1),
                temp_css_c=round(temp_css_c, 1),
                temp_mss_c=round(temp_mss_c, 1),
                ddr_used_mib=round(ddr_used_mib, 1),
                cmx_used_mib=round(cmx_used_mib, 1),
                cpu_css_pct=round(cpu_css_pct, 1),
                cpu_mss_pct=round(cpu_mss_pct, 1),
            )
        )

    def export_csv(self, path: pathlib.Path | str) -> pathlib.Path:
        """Export all recorded samples to an RFC-4180 CSV file."""
        p = pathlib.Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)

        fieldnames = [
            "timestamp_sec",
            "fps",
            "bitrate_mbps",
            "frame_size_kib",
            "is_keyframe",
            "temp_avg_c",
            "temp_css_c",
            "temp_mss_c",
            "ddr_used_mib",
            "cmx_used_mib",
            "cpu_css_pct",
            "cpu_mss_pct",
        ]

        with open(p, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for s in self.samples:
                writer.writerow(asdict(s))

        return p

    def export_json(self, path: pathlib.Path | str) -> pathlib.Path:
        """Export samples and aggregated summary statistics to JSON."""
        p = pathlib.Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)

        summary = self.compute_summary()
        payload = {
            "summary": summary,
            "samples": [asdict(s) for s in self.samples],
        }

        with open(p, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        return p

    def compute_summary(self) -> dict:
        """Compute aggregated statistics over the recorded run."""
        if not self.samples:
            return {"sample_count": 0}

        fps_vals = [s.fps for s in self.samples if s.fps > 0]
        bps_vals = [s.bitrate_mbps for s in self.samples if s.bitrate_mbps > 0]
        temp_vals = [s.temp_avg_c for s in self.samples if s.temp_avg_c > 0]
        keyframes = sum(1 for s in self.samples if s.is_keyframe)

        return {
            "sample_count": len(self.samples),
            "duration_sec": round(self.samples[-1].timestamp_sec - self.samples[0].timestamp_sec, 2),
            "fps_avg": round(sum(fps_vals) / len(fps_vals), 2) if fps_vals else 0.0,
            "fps_min": round(min(fps_vals), 2) if fps_vals else 0.0,
            "fps_max": round(max(fps_vals), 2) if fps_vals else 0.0,
            "bitrate_avg_mbps": round(sum(bps_vals) / len(bps_vals), 2) if bps_vals else 0.0,
            "bitrate_min_mbps": round(min(bps_vals), 2) if bps_vals else 0.0,
            "bitrate_max_mbps": round(max(bps_vals), 2) if bps_vals else 0.0,
            "temp_avg_c": round(sum(temp_vals) / len(temp_vals), 1) if temp_vals else 0.0,
            "temp_max_c": round(max(temp_vals), 1) if temp_vals else 0.0,
            "keyframes_total": keyframes,
        }

    def generate_html_report(
        self, path: pathlib.Path | str, title: str = "Opal C1 Benchmark Telemetry Report"
    ) -> pathlib.Path:
        """Generate a completely self-contained, responsive, offline HTML visual report with SVG charts."""
        p = pathlib.Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)

        summary = self.compute_summary()

        # Helper to generate an SVG line chart
        def make_svg_chart(
            series_list: list[tuple[str, str, list[float]]],
            y_label: str,
            target_line: float | None = None,
            target_label: str = "",
            danger_line: float | None = None,
            danger_label: str = "",
            min_y: float | None = None,
            max_y: float | None = None,
        ) -> str:
            width = 600
            height = 200
            pad_l, pad_r, pad_t, pad_b = 50, 20, 20, 30
            plot_w = width - pad_l - pad_r
            plot_h = height - pad_t - pad_b

            all_vals = [v for _, _, s in series_list for v in s if not math.isnan(v)]
            if not all_vals:
                return "<div class='no-data'>No data available</div>"

            calc_min = min(all_vals) if min_y is None else min_y
            calc_max = max(all_vals) if max_y is None else max_y
            if target_line is not None:
                calc_max = max(calc_max, target_line * 1.1)
            if danger_line is not None:
                calc_max = max(calc_max, danger_line * 1.05)

            y_range = max(1e-5, calc_max - calc_min)

            def to_x(idx: int, total: int) -> float:
                if total <= 1:
                    return pad_l + plot_w / 2
                return pad_l + (idx / (total - 1)) * plot_w

            def to_y(val: float) -> float:
                return pad_t + plot_h - ((val - calc_min) / y_range) * plot_h

            svg = [
                f'<svg viewBox="0 0 {width} {height}" class="chart-svg" xmlns="http://www.w3.org/2000/svg">',
                # Gridlines & axes
                f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{pad_t + plot_h}" stroke="#334155" stroke-width="1"/>',
                f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{width - pad_r}" y2="{pad_t + plot_h}" stroke="#334155" stroke-width="1"/>',
            ]

            # Y axis labels
            svg.append(f'<text x="{pad_l - 6}" y="{to_y(calc_min)}" fill="#94a3b8" font-size="10" text-anchor="end">{calc_min:.1f}</text>')
            svg.append(f'<text x="{pad_l - 6}" y="{to_y(calc_max)}" fill="#94a3b8" font-size="10" text-anchor="end">{calc_max:.1f}</text>')
            mid_val = (calc_min + calc_max) / 2
            svg.append(f'<text x="{pad_l - 6}" y="{to_y(mid_val)}" fill="#94a3b8" font-size="10" text-anchor="end">{mid_val:.1f}</text>')

            # Target line
            if target_line is not None and calc_min <= target_line <= calc_max:
                ty = to_y(target_line)
                svg.append(f'<line x1="{pad_l}" y1="{ty}" x2="{width - pad_r}" y2="{ty}" stroke="#38bdf8" stroke-dasharray="4" stroke-width="1.5"/>')
                if target_label:
                    svg.append(f'<text x="{width - pad_r - 4}" y="{ty - 4}" fill="#38bdf8" font-size="9" text-anchor="end">{target_label}</text>')

            # Danger line
            if danger_line is not None and calc_min <= danger_line <= calc_max:
                dy = to_y(danger_line)
                svg.append(f'<line x1="{pad_l}" y1="{dy}" x2="{width - pad_r}" y2="{dy}" stroke="#ef4444" stroke-dasharray="4" stroke-width="1.5"/>')
                if danger_label:
                    svg.append(f'<text x="{width - pad_r - 4}" y="{dy - 4}" fill="#ef4444" font-size="9" text-anchor="end">{danger_label}</text>')

            # Polylines
            for name, color, series in series_list:
                if not series:
                    continue
                pts = [f"{to_x(i, len(series)):.1f},{to_y(v):.1f}" for i, v in enumerate(series)]
                svg.append(f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{" ".join(pts)}" stroke-linecap="round" stroke-linejoin="round"/>')

            # Legend
            leg_x = pad_l
            for name, color, _ in series_list:
                svg.append(f'<circle cx="{leg_x + 5}" cy="{height - 10}" r="4" fill="{color}"/>')
                svg.append(f'<text x="{leg_x + 14}" y="{height - 7}" fill="#e2e8f0" font-size="11">{name}</text>')
                leg_x += len(name) * 8 + 30

            svg.append('</svg>')
            return "\n".join(svg)

        # Extract series
        fps_series = [s.fps for s in self.samples]
        bps_series = [s.bitrate_mbps for s in self.samples]
        temp_avg_series = [s.temp_avg_c for s in self.samples]
        temp_css_series = [s.temp_css_c for s in self.samples]
        temp_mss_series = [s.temp_mss_c for s in self.samples]
        cpu_css_series = [s.cpu_css_pct for s in self.samples]
        cpu_mss_series = [s.cpu_mss_pct for s in self.samples]

        chart_fps = make_svg_chart(
            [("Framerate (FPS)", "#22c55e", fps_series)],
            y_label="FPS",
            target_line=30.0,
            target_label="Target 30 FPS",
            min_y=0.0,
            max_y=35.0,
        )

        chart_bitrate = make_svg_chart(
            [("Bitrate (Mbps)", "#38bdf8", bps_series)],
            y_label="Mbps",
            target_line=25.0,
            target_label="SLA 25 Mbps CBR",
            min_y=0.0,
            max_y=35.0,
        )

        chart_thermal = make_svg_chart(
            [
                ("Chip Average", "#f59e0b", temp_avg_series),
                ("CSS Core", "#ec4899", temp_css_series),
                ("MSS Core", "#8b5cf6", temp_mss_series),
            ],
            y_label="°C",
            target_line=55.0,
            target_label="55°C Nominal",
            danger_line=85.0,
            danger_label="85°C Throttle Limit",
            min_y=25.0,
            max_y=90.0,
        )

        chart_cpu = make_svg_chart(
            [
                ("Leon CSS CPU %", "#06b6d4", cpu_css_series),
                ("Leon MSS CPU %", "#a855f7", cpu_mss_series),
            ],
            y_label="%",
            min_y=0.0,
            max_y=100.0,
        )

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
    :root {{
      --bg: #0f172a;
      --card-bg: #1e293b;
      --border: #334155;
      --text: #f8fafc;
      --text-dim: #94a3b8;
      --accent: #38bdf8;
      --green: #22c55e;
      --orange: #f59e0b;
    }}
    body {{
      margin: 0;
      padding: 30px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
    }}
    .header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid var(--border);
      padding-bottom: 20px;
      margin-bottom: 30px;
    }}
    h1 {{ margin: 0; font-size: 24px; color: var(--accent); }}
    .meta {{ font-size: 13px; color: var(--text-dim); }}
    .grid-cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-bottom: 30px;
    }}
    .card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
    }}
    .card-title {{ font-size: 12px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.5px; }}
    .card-val {{ font-size: 28px; font-weight: bold; margin-top: 6px; }}
    .val-green {{ color: var(--green); }}
    .val-blue {{ color: var(--accent); }}
    .val-orange {{ color: var(--orange); }}
    .charts-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(480px, 1fr));
      gap: 20px;
    }}
    .chart-box {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 20px;
    }}
    .chart-box h3 {{ margin: 0 0 15px 0; font-size: 16px; }}
    .chart-svg {{ width: 100%; height: auto; display: block; }}
  </style>
</head>
<body>
  <div class="header">
    <div>
      <h1>{title}</h1>
      <div class="meta">Opal C1 Hardware Telemetry • Dual-Stream 4K H.265 + 1080p UVC Benchmark</div>
    </div>
    <div class="meta">
      Duration: <strong>{summary.get('duration_sec', 0)}s</strong> | Samples: <strong>{summary.get('sample_count', 0)}</strong>
    </div>
  </div>

  <div class="grid-cards">
    <div class="card">
      <div class="card-title">Average Framerate</div>
      <div class="card-val val-green">{summary.get('fps_avg', 0.0)} <span style="font-size:16px;">FPS</span></div>
      <div class="meta">Min: {summary.get('fps_min', 0.0)} | Max: {summary.get('fps_max', 0.0)}</div>
    </div>
    <div class="card">
      <div class="card-title">Average Bitrate</div>
      <div class="card-val val-blue">{summary.get('bitrate_avg_mbps', 0.0)} <span style="font-size:16px;">Mbps</span></div>
      <div class="meta">Target: 25.0 Mbps CBR (±25%)</div>
    </div>
    <div class="card">
      <div class="card-title">Average Silicon Temp</div>
      <div class="card-val val-orange">{summary.get('temp_avg_c', 0.0)} <span style="font-size:16px;">°C</span></div>
      <div class="meta">Max: {summary.get('temp_max_c', 0.0)}°C (Ceiling: 85°C)</div>
    </div>
    <div class="card">
      <div class="card-title">Keyframe Frequency</div>
      <div class="card-val val-green">{summary.get('keyframes_total', 0)} <span style="font-size:16px;">IDRs</span></div>
      <div class="meta">Cadence: ~1 IDR / second (GOP 30)</div>
    </div>
  </div>

  <div class="charts-grid">
    <div class="chart-box">
      <h3>1. Framerate Stability (FPS vs Time)</h3>
      {chart_fps}
    </div>
    <div class="chart-box">
      <h3>2. 4K H.265 Bitrate (Mbps vs Time)</h3>
      {chart_bitrate}
    </div>
    <div class="chart-box">
      <h3>3. Silicon Thermal Curves (°C vs Time)</h3>
      {chart_thermal}
    </div>
    <div class="chart-box">
      <h3>4. Myriad X Leon CPU Load (% vs Time)</h3>
      {chart_cpu}
    </div>
  </div>
</body>
</html>
"""
        with open(p, "w", encoding="utf-8") as f:
            f.write(html)

        return p
