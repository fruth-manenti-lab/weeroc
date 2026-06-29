"""Plotting and CSV analysis helpers for RADIOROC runs.

This module owns file parsing, latest-run discovery, simple scan summaries, and
plot rendering. It deliberately does not talk to hardware.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
import math
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/radioroc-matplotlib")


DEFAULT_RUNS_DIR: Path = Path("radioroc_runs")


@dataclass
class ThresholdScanData:
    """Parsed threshold scan CSV data.

    **Attributes**
    - `path` (`Path`): Source CSV path.
    - `dacs` (`list[float]`): Threshold DAC points.
    - `series` (`dict[str, list[float]]`): Trigger-rate series by channel
      name, such as `"ch4"`.
    """

    path: Path
    dacs: list[float]
    series: dict[str, list[float]]


@dataclass
class HoldScanData:
    """Parsed hold scan CSV data.

    **Attributes**
    - `path` (`Path`): Source CSV path.
    - `x_column` (`str`): `"hold_code"` or `"hold_delay_ns"`.
    - `x_values` (`list[float]`): Hold codes or external hold delays.
    - `series` (`dict[str, list[float]]`): ADC summary series by CSV column.
    """

    path: Path
    x_column: str
    x_values: list[float]
    series: dict[str, list[float]]


@dataclass
class ThresholdChannelSummary:
    """Simple landmarks for one threshold scan channel.

    **Attributes**
    - `channel` (`str`): Channel column name.
    - `peak_dac` (`float | None`): DAC at maximum finite rate.
    - `peak_hz` (`float | None`): Maximum finite trigger rate.
    - `first_nonzero_dac` (`float | None`): First DAC with rate above zero.
    - `last_above_1khz_dac` (`float | None`): Last DAC with rate at least
      `1000 Hz`.
    """

    channel: str
    peak_dac: float | None
    peak_hz: float | None
    first_nonzero_dac: float | None
    last_above_1khz_dac: float | None


@dataclass
class HoldChannelSummary:
    """Simple landmarks for one hold scan channel/gain.

    **Attributes**
    - `channel` (`int`): Channel number.
    - `gain` (`str`): `"hg"` or `"lg"`.
    - `peak_x` (`float | None`): Hold code/delay at maximum finite amplitude.
    - `peak_value` (`float | None`): Maximum finite amplitude.
    - `plateau_start_x` (`float | None`): First point above 90 percent of peak.
    - `plateau_end_x` (`float | None`): Last point above 90 percent of peak.
    """

    channel: int
    gain: str
    peak_x: float | None
    peak_value: float | None
    plateau_start_x: float | None
    plateau_end_x: float | None


def find_latest_scan(root: Path, filename: str) -> Path:
    """Find the newest scan CSV by filename.

    **Inputs**
    - `root` (`Path`): Directory tree to search.
    - `filename` (`str`): Scan CSV basename, for example
      `"thresholdscan.csv"`.

    **Returns**
    - `Path`: Most recently modified matching file.
    """

    candidates: list[Path] = [path for path in root.rglob(filename) if path.is_file()]
    if not candidates:
        raise FileNotFoundError(f"no {filename} files found under {root}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def read_threshold_csv(path: Path) -> ThresholdScanData:
    """Read a threshold scan CSV.

    **Inputs**
    - `path` (`Path`): Input `thresholdscan.csv`.

    **Returns**
    - `ThresholdScanData`: Parsed DAC points and channel series.
    """

    with path.open(newline="") as fp:
        reader = csv.DictReader(fp)
        if reader.fieldnames is None or "DAC" not in reader.fieldnames:
            raise ValueError(f"{path} does not look like a threshold scan CSV")
        channels: list[str] = [name for name in reader.fieldnames if name != "DAC"]
        dacs: list[float] = []
        series: dict[str, list[float]] = {channel: [] for channel in channels}
        for row in reader:
            dacs.append(float(row["DAC"]))
            for channel in channels:
                value: str | None = row.get(channel)
                series[channel].append(float(value) if value not in ("", None) else math.nan)
    return ThresholdScanData(path=path, dacs=dacs, series=series)


def read_hold_csv(path: Path) -> HoldScanData:
    """Read a hold scan CSV.

    **Inputs**
    - `path` (`Path`): Input `holdscan.csv`.

    **Returns**
    - `HoldScanData`: Parsed hold axis and ADC summary series.
    """

    with path.open(newline="") as fp:
        reader = csv.DictReader(fp)
        if not reader.fieldnames:
            raise ValueError(f"{path} does not look like a hold scan CSV")
        x_column: str = "hold_code" if "hold_code" in reader.fieldnames else "hold_delay_ns"
        if x_column not in reader.fieldnames:
            raise ValueError(f"{path} does not look like a hold scan CSV")
        x_values: list[float] = []
        series: dict[str, list[float]] = {name: [] for name in reader.fieldnames if name != x_column}
        for row in reader:
            x_values.append(float(row[x_column]))
            for name in series:
                value = row.get(name, "")
                series[name].append(float(value) if value not in ("", None) else math.nan)
    return HoldScanData(path=path, x_column=x_column, x_values=x_values, series=series)


def parse_threshold_channels(value: str | None, available: list[str]) -> list[str]:
    """Parse threshold plot channel selection.

    **Inputs**
    - `value` (`str | None`): User channel expression, such as `"4"` or
      `"ch4,ch5"`.
    - `available` (`list[str]`): Channel columns present in the CSV.

    **Returns**
    - `list[str]`: Selected channel column names.
    """

    if not value:
        return available
    selected: list[str] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        name: str = part if part.startswith("ch") else f"ch{int(part)}"
        if name not in available:
            raise ValueError(f"{name} not present in CSV; available: {', '.join(available)}")
        selected.append(name)
    return selected


def parse_hold_channels(value: str | None, series: dict[str, list[float]]) -> list[int]:
    """Parse hold plot channel selection.

    **Inputs**
    - `value` (`str | None`): User expression, such as `"4"` or `"0-3"`.
    - `series` (`dict[str, list[float]]`): Hold scan series columns.

    **Returns**
    - `list[int]`: Selected channel numbers.
    """

    if value:
        channels: set[int] = set()
        for part in value.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                lo, hi = [int(text) for text in part.split("-", 1)]
                if hi < lo:
                    raise ValueError("channel ranges must be ascending")
                channels.update(range(lo, hi + 1))
            else:
                channels.add(int(part))
        return sorted(channels)

    channels = set()
    for name in series:
        if name.startswith("ch") and name.endswith("_hg_mean"):
            channels.add(int(name[2:].split("_", 1)[0]))
    return sorted(channels)


def filter_hold_data(data: HoldScanData, *, exclude_zero: bool = False, x_min: float | None = None) -> HoldScanData:
    """Filter hold scan points by x-axis value.

    **Inputs**
    - `data` (`HoldScanData`): Parsed hold scan.
    - `exclude_zero` (`bool`): Drop x value `0`.
    - `x_min` (`float | None`): Drop points below this value.

    **Returns**
    - `HoldScanData`: Filtered copy.
    """

    keep: list[bool] = [True] * len(data.x_values)
    if exclude_zero:
        keep = [ok and value != 0 for ok, value in zip(keep, data.x_values)]
    if x_min is not None:
        keep = [ok and value >= x_min for ok, value in zip(keep, data.x_values)]
    return HoldScanData(
        path=data.path,
        x_column=data.x_column,
        x_values=[value for value, ok in zip(data.x_values, keep) if ok],
        series={name: [value for value, ok in zip(values, keep) if ok] for name, values in data.series.items()},
    )


def summarize_threshold(data: ThresholdScanData) -> list[ThresholdChannelSummary]:
    """Extract simple threshold scan landmarks.

    **Inputs**
    - `data` (`ThresholdScanData`): Parsed threshold scan.

    **Returns**
    - `list[ThresholdChannelSummary]`: One summary per channel.
    """

    summaries: list[ThresholdChannelSummary] = []
    for channel, values in data.series.items():
        pairs: list[tuple[float, float]] = [
            (dac, value) for dac, value in zip(data.dacs, values) if math.isfinite(value)
        ]
        if not pairs:
            summaries.append(ThresholdChannelSummary(channel, None, None, None, None))
            continue
        peak_dac, peak_hz = max(pairs, key=lambda pair: pair[1])
        first_nonzero = next((dac for dac, value in pairs if value > 0), None)
        last_above_1khz = next((dac for dac, value in reversed(pairs) if value >= 1000), None)
        summaries.append(ThresholdChannelSummary(channel, peak_dac, peak_hz, first_nonzero, last_above_1khz))
    return summaries


def summarize_hold(data: HoldScanData, channels: list[int] | None = None, gains: tuple[str, ...] = ("hg", "lg")) -> list[HoldChannelSummary]:
    """Extract simple hold scan peak and plateau landmarks.

    **Inputs**
    - `data` (`HoldScanData`): Parsed hold scan.
    - `channels` (`list[int] | None`): Channels to summarize. Defaults to all.
    - `gains` (`tuple[str, ...]`): Gains to summarize, usually `"hg"` and/or
      `"lg"`.

    **Returns**
    - `list[HoldChannelSummary]`: One summary per available channel/gain.
    """

    selected_channels: list[int] = channels or parse_hold_channels(None, data.series)
    summaries: list[HoldChannelSummary] = []
    for channel in selected_channels:
        for gain in gains:
            column = f"ch{channel}_{gain}_mean"
            if column not in data.series:
                continue
            pairs = [(x, value) for x, value in zip(data.x_values, data.series[column]) if math.isfinite(value)]
            if not pairs:
                summaries.append(HoldChannelSummary(channel, gain, None, None, None, None))
                continue
            peak_x, peak_value = max(pairs, key=lambda pair: pair[1])
            threshold = 0.9 * peak_value
            plateau = [x for x, value in pairs if value >= threshold]
            summaries.append(
                HoldChannelSummary(
                    channel=channel,
                    gain=gain,
                    peak_x=peak_x,
                    peak_value=peak_value,
                    plateau_start_x=plateau[0] if plateau else None,
                    plateau_end_x=plateau[-1] if plateau else None,
                )
            )
    return summaries


def has_invalid_internal_zero_point(data: HoldScanData) -> bool:
    """Detect the known internal-hold zero-code outlier condition.

    **Inputs**
    - `data` (`HoldScanData`): Parsed hold scan.

    **Returns**
    - `bool`: True when this is an internal hold scan containing x value `0`.
    """

    return data.x_column == "hold_code" and any(value == 0 for value in data.x_values)


def plot_threshold_scan(
    data: ThresholdScanData,
    *,
    channels: list[str],
    out: Path,
    yscale: str = "symlog",
    steps: bool = False,
    title: str = "RADIOROC threshold scan",
) -> Path:
    """Render a threshold scan plot.

    **Inputs**
    - `data` (`ThresholdScanData`): Parsed threshold data.
    - `channels` (`list[str]`): Channel column names to draw.
    - `out` (`Path`): Output PNG path.
    - `yscale` (`str`): Matplotlib y-axis scale.
    - `steps` (`bool`): Draw staircase lines when true.
    - `title` (`str`): Plot title.

    **Returns**
    - `Path`: Written PNG path.
    """

    import matplotlib.pyplot as plt

    out.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 5), constrained_layout=True)
    drawstyle = "steps-post" if steps else "default"
    for channel in channels:
        ax.plot(data.dacs, data.series[channel], marker="o", linewidth=1.3, markersize=3, drawstyle=drawstyle, label=channel)
    ax.set_title(title)
    ax.set_xlabel("Threshold DAC code")
    ax.set_ylabel("Trigger frequency (Hz)")
    ax.set_yscale(yscale)
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(loc="best")
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return out


def plot_hold_scan(
    data: HoldScanData,
    *,
    channels: list[int],
    gain: str,
    out: Path,
    title: str = "RADIOROC hold scan",
) -> Path:
    """Render a hold scan plot.

    **Inputs**
    - `data` (`HoldScanData`): Parsed hold data.
    - `channels` (`list[int]`): Channels to draw.
    - `gain` (`str`): `"hg"`, `"lg"`, or `"both"`.
    - `out` (`Path`): Output PNG path.
    - `title` (`str`): Plot title.

    **Returns**
    - `Path`: Written PNG path.
    """

    import matplotlib.pyplot as plt

    out.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=150)
    for channel in channels:
        if gain in {"hg", "both"} and f"ch{channel}_hg_mean" in data.series:
            ax.plot(data.x_values, data.series[f"ch{channel}_hg_mean"], marker="o", linewidth=1.4, label=f"ch{channel} HG")
        if gain in {"lg", "both"} and f"ch{channel}_lg_mean" in data.series:
            ax.plot(data.x_values, data.series[f"ch{channel}_lg_mean"], marker="s", linewidth=1.4, label=f"ch{channel} LG")
    ax.set_title(title)
    ax.set_xlabel("Internal hold delay code" if data.x_column == "hold_code" else "External hold delay (ns)")
    ax.set_ylabel("ADC amplitude (mV equivalent, vendor scale 0.25/code)")
    ax.grid(True, alpha=0.35)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return out


def plot_hold_comparison(
    scans: list[HoldScanData],
    *,
    channel: int,
    gain: str,
    out: Path,
    title: str = "RADIOROC hold scan comparison",
) -> Path:
    """Render multiple hold scans on one plot.

    **Inputs**
    - `scans` (`list[HoldScanData]`): Parsed hold scans to compare.
    - `channel` (`int`): Channel to draw.
    - `gain` (`str`): `"hg"` or `"lg"`.
    - `out` (`Path`): Output PNG path.
    - `title` (`str`): Plot title.

    **Returns**
    - `Path`: Written PNG path.
    """

    import matplotlib.pyplot as plt

    out.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=150)
    column = f"ch{channel}_{gain}_mean"
    for scan in scans:
        if column not in scan.series:
            continue
        ax.plot(scan.x_values, scan.series[column], marker="o", linewidth=1.3, label=scan.path.parent.name)
    ax.set_title(title)
    ax.set_xlabel("Internal hold delay code" if scans and scans[0].x_column == "hold_code" else "External hold delay (ns)")
    ax.set_ylabel(f"Channel {channel} {gain.upper()} ADC amplitude")
    ax.grid(True, alpha=0.35)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return out
