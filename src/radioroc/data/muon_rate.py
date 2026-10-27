"""Muon rate per minute from a saved acquisition run. Pure Python, no Qt, no hardware.

Definitions
-----------
* Trigger events: every (batch, event) of the run's CURRENT segment.
* Accepted events: analysed events with ``EventAnalysis.coincidence`` True (a cluster in every layer of the
  layout). For a one-layer layout that means at least one hit above the detection threshold.
* Segments: ``events.csv`` of an append run holds the rows of several jobs, but ``metadata.json`` (and so the
  timing) only describes the latest one. The rate is therefore restricted to the manifest's batch range
  (``operation.acquisition.start_batch`` .. ``+batches``), i.e. the same rows the timing refers to, and a
  warning is set when the CSV holds other rows.
* Two time bases: (a) wall clock ``elapsed_seconds`` (created_at to finished_at, includes preparation and
  cleanup), (b) batch-completion time: events after the first batch divided by (last - first)
  ``batch_received_at``. (b) excludes start-up and is preferred; (a) is the fallback.
* Uncertainty is Poisson: sigma = sqrt(N) / T.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import math
from pathlib import Path
from typing import Iterable, Sequence

DRIFT_CHI2_PER_DOF = 2.0


@dataclass(frozen=True)
class RunTiming:
    directory: Path
    created_at: datetime | None
    finished_at: datetime | None
    elapsed_seconds: float | None
    batch_times: dict          # batch number -> datetime received (current segment only)
    events_per_batch: dict     # batch number -> distinct (batch, event) count in the current segment
    segment_start: int | None  # first batch of the current segment (None: no manifest, all rows used)
    segment_batches: int | None
    status: str = "unknown"
    execution_mode: str = "unknown"
    warnings: tuple = ()

    def in_segment(self, batch: int) -> bool:
        if self.segment_start is None or self.segment_batches is None:
            return True
        return self.segment_start <= batch < self.segment_start + self.segment_batches

    @property
    def total_events(self) -> int:
        return sum(self.events_per_batch.values())


@dataclass(frozen=True)
class RateResult:
    accepted: int
    trigger_events: int
    accepted_fraction: float
    wall_seconds: float | None
    wall_rate_per_min: float | None
    wall_sigma_per_min: float | None
    batch_seconds: float | None
    batch_rate_per_min: float | None
    batch_sigma_per_min: float | None
    basis: str                 # "batch" or "wall" or "none": which one rate_per_min uses
    rate_per_min: float | None
    sigma_per_min: float | None
    trigger_rate_per_min: float | None = None
    warnings: tuple = ()


@dataclass(frozen=True)
class NetRate:
    rate_per_min: float
    sigma_per_min: float
    signal_rate_per_min: float
    background_rate_per_min: float
    warnings: tuple = ()


@dataclass(frozen=True)
class BlockRate:
    first_batch: int
    last_batch: int
    events: int
    accepted: int
    seconds: float
    rate_per_min: float
    sigma_per_min: float


@dataclass(frozen=True)
class BlockResult:
    blocks: tuple
    chi2: float | None
    dof: int
    chi2_per_dof: float | None
    drift: bool
    message: str = ""


@dataclass(frozen=True)
class RunRate:
    timing: RunTiming
    result: RateResult
    blocks: BlockResult
    accepted_per_batch: dict = field(default_factory=dict)


# ------------------------------------------------------------------ timing --
def _parse_time(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _seconds_between(a: datetime, b: datetime) -> float | None:
    try:
        return (b - a).total_seconds()
    except TypeError:  # naive vs aware
        return None


def read_run_timing(path) -> RunTiming:
    """Timing of the CURRENT segment of a saved acquisition run (see the module docstring)."""
    from radioroc.data.acquisition_reader import read_acquisition_run

    saved = read_acquisition_run(Path(path))
    manifest = saved.manifest
    warnings: list[str] = []
    if not manifest:
        warnings.append("no metadata.json: run times are unknown")
        counts: dict[int, set] = {}
        for row in saved.rows:
            counts.setdefault(int(row["batch"]), set()).add(int(row["event"]))
        return RunTiming(saved.directory, None, None, None, {}, {b: len(s) for b, s in sorted(counts.items())},
                         None, None, saved.status, saved.execution_mode, tuple(warnings))

    acquisition = manifest["operation"]["acquisition"]
    start = acquisition.get("start_batch", 0)
    n_batches = acquisition["batches"]
    segment = range(start, start + n_batches)
    if len(saved.rows) != len(saved.current_segment_rows):
        warnings.append(
            f"events.csv also holds {len(saved.rows) - len(saved.current_segment_rows)} rows of earlier append "
            f"segments; the rate uses only the current segment (batches {start}..{start + n_batches - 1}), "
            "whose times metadata.json records")
    counts = {}
    for row in saved.current_segment_rows:
        counts.setdefault(int(row["batch"]), set()).add(int(row["event"]))
    events_per_batch = {b: len(s) for b, s in sorted(counts.items())}

    times: dict[int, datetime] = {}
    raw = manifest.get("batch_received_at")
    for item in raw if isinstance(raw, list) else ():
        if not isinstance(item, dict):
            continue
        batch, stamp = item.get("batch"), _parse_time(item.get("received_at"))
        if isinstance(batch, int) and not isinstance(batch, bool) and batch in segment and stamp is not None:
            times[batch] = stamp
    missing = [b for b in events_per_batch if b not in times]
    if events_per_batch and missing and len(missing) < len(events_per_batch):
        warnings.append(f"{len(missing)} batch(es) have no received time and are ignored for the batch-time rate")
    raw_counts = manifest.get("batch_counts")
    for item in raw_counts if isinstance(raw_counts, list) else ():
        if isinstance(item, dict) and item.get("batch") in events_per_batch and \
                isinstance(item.get("received"), int) and item["received"] != events_per_batch[item["batch"]]:
            warnings.append(f"batch {item['batch']}: manifest received {item['received']} events, "
                            f"CSV has {events_per_batch[item['batch']]}")
            break

    created, finished = _parse_time(manifest.get("created_at")), _parse_time(manifest.get("finished_at"))
    elapsed = manifest.get("elapsed_seconds")
    if not isinstance(elapsed, (int, float)) or isinstance(elapsed, bool) or not math.isfinite(elapsed) or elapsed <= 0:
        elapsed = _seconds_between(created, finished) if created and finished else None
        if elapsed is not None and elapsed <= 0:
            elapsed = None
    return RunTiming(saved.directory, created, finished, None if elapsed is None else float(elapsed), times,
                     events_per_batch, start, n_batches, saved.status, saved.execution_mode, tuple(warnings))


# -------------------------------------------------------------------- rate --
def _rate(count, seconds):
    if seconds is None or seconds <= 0 or count is None:
        return None, None
    return 60.0 * count / seconds, 60.0 * math.sqrt(count) / seconds


def compute_rate(accepted: int, trigger_events: int, live_seconds: float | None, *,
                 batch_seconds: float | None = None, accepted_after_first: int | None = None,
                 trigger_after_first: int | None = None, warnings: Iterable[str] = ()) -> RateResult:
    """Rates per minute with Poisson sigma = sqrt(N)/T on both time bases.

    ``live_seconds`` is the wall-clock time (created_at to finished_at). The batch-completion basis uses
    ``accepted_after_first`` events over ``batch_seconds``; when it is unavailable the wall-clock basis is
    used and a warning is added.
    """
    notes = list(warnings)
    accepted, trigger_events = int(accepted), int(trigger_events)
    fraction = accepted / trigger_events if trigger_events else 0.0
    wall_rate, wall_sigma = _rate(accepted, live_seconds)
    batch_rate, batch_sigma = (None, None)
    if batch_seconds is not None and accepted_after_first is not None:
        batch_rate, batch_sigma = _rate(accepted_after_first, batch_seconds)
    if batch_rate is not None:
        basis, rate, sigma = "batch", batch_rate, batch_sigma
        trig = _rate(trigger_after_first, batch_seconds)[0] if trigger_after_first is not None else None
    elif wall_rate is not None:
        basis, rate, sigma = "wall", wall_rate, wall_sigma
        trig = _rate(trigger_events, live_seconds)[0]
        notes.append("batch-completion time unavailable (fewer than 2 timed batches or missing timestamps): "
                     "using wall-clock time, which includes start-up and cleanup")
    else:
        basis, rate, sigma, trig = "none", None, None, None
        notes.append("no usable time information: no rate")
    return RateResult(accepted, trigger_events, fraction, live_seconds, wall_rate, wall_sigma, batch_seconds,
                      batch_rate, batch_sigma, basis, rate, sigma, trig, tuple(notes))


def segment_counts(timing: RunTiming, events, analyses) -> tuple[dict, dict]:
    """Per-batch (events, accepted) for the events inside the timing's segment. ``analyses[i]`` belongs to
    ``events[i]``; accepted = analysis.coincidence."""
    per_batch: dict[int, int] = {}
    accepted: dict[int, int] = {}
    for event, analysis in zip(events, analyses):
        if not timing.in_segment(event.batch):
            continue
        per_batch[event.batch] = per_batch.get(event.batch, 0) + 1
        accepted.setdefault(event.batch, 0)
        if analysis.coincidence:
            accepted[event.batch] += 1
    return dict(sorted(per_batch.items())), dict(sorted(accepted.items()))


def _timed_batches(timing: RunTiming, events_per_batch: dict) -> list:
    return sorted((b for b in events_per_batch if b in timing.batch_times), key=lambda b: timing.batch_times[b])


def rate_from_batches(timing: RunTiming, events_per_batch: dict, accepted_per_batch: dict) -> RateResult:
    trigger = sum(events_per_batch.values())
    accepted = sum(accepted_per_batch.values())
    timed = _timed_batches(timing, events_per_batch)
    batch_seconds = after_acc = after_trig = None
    if len(timed) >= 2:
        seconds = _seconds_between(timing.batch_times[timed[0]], timing.batch_times[timed[-1]])
        if seconds is not None and seconds > 0:
            batch_seconds = seconds
            after_acc = sum(accepted_per_batch.get(b, 0) for b in timed[1:])
            after_trig = sum(events_per_batch[b] for b in timed[1:])
    return compute_rate(accepted, trigger, timing.elapsed_seconds, batch_seconds=batch_seconds,
                        accepted_after_first=after_acc, trigger_after_first=after_trig, warnings=timing.warnings)


def block_rates(batch_times: dict, events_per_batch: dict, accepted_flags_by_batch: dict, k: int = 4) -> BlockResult:
    """Split the run into k blocks of equal batch count and test the rates for drift.

    The first batch only marks the start (its events arrived before the clock started), so the k blocks cover
    the remaining batches; block j runs from the receive time of the batch before it to that of its last
    batch. ``accepted_flags_by_batch`` maps batch -> accepted count (or a list of booleans). Chi-square uses
    the Poisson expectation mean_rate * T_j; ``drift`` is chi2/dof > 2.
    """
    timed = sorted((b for b in events_per_batch if b in batch_times), key=lambda b: batch_times[b])
    k = min(int(k), len(timed) - 1)
    if k < 2:
        return BlockResult((), None, 0, None, False, "too few batches for a drift check")
    rest = timed[1:]
    base, extra = divmod(len(rest), k)
    blocks, begin = [], 0
    for j in range(k):
        size = base + (1 if j < extra else 0)
        group = rest[begin:begin + size]
        previous = timed[begin]  # batch right before this group in time order
        begin += size
        seconds = _seconds_between(batch_times[previous], batch_times[group[-1]])
        if seconds is None or seconds <= 0:
            return BlockResult((), None, 0, None, False, "batch times not increasing: no drift check")
        events = sum(events_per_batch[b] for b in group)
        value = [accepted_flags_by_batch.get(b, 0) for b in group]
        acc = sum(sum(v) if isinstance(v, (list, tuple)) else v for v in value)
        rate, sigma = _rate(acc, seconds)
        blocks.append(BlockRate(group[0], group[-1], events, int(acc), seconds, rate, sigma))
    total_n = sum(b.accepted for b in blocks)
    total_t = sum(b.seconds for b in blocks)
    if total_n <= 0:
        return BlockResult(tuple(blocks), None, k - 1, None, False, "no accepted events: no drift check")
    mean = total_n / total_t
    chi2 = sum((b.accepted - mean * b.seconds) ** 2 / (mean * b.seconds) for b in blocks)
    dof = k - 1
    drift = chi2 / dof > DRIFT_CHI2_PER_DOF
    message = "drift: check bias, temperature, interference" if drift else "rate stable between blocks"
    return BlockResult(tuple(blocks), chi2, dof, chi2 / dof, drift, message)


def evaluate_run(timing: RunTiming, events, analyses, k: int = 4) -> RunRate:
    per_batch, accepted = segment_counts(timing, events, analyses)
    return RunRate(timing, rate_from_batches(timing, per_batch, accepted),
                   block_rates(timing.batch_times, per_batch, accepted, k), accepted)


def analyse_run(path, layout, threshold_counts: float, pedestals: dict | None = None, k: int = 4) -> RunRate:
    """Load a run, analyse it with the given settings (pedestals None -> per-channel median of that run) and
    evaluate its rate. Used for background runs and by the CLI."""
    from radioroc.data import muon_analysis

    events = muon_analysis.load_events(Path(path))
    if pedestals is None:
        pedestals = muon_analysis.estimate_pedestals(events)
    analyses = [muon_analysis.analyse_event(e, layout, pedestals, threshold_counts=float(threshold_counts),
                                            gain="hg") for e in events]
    return evaluate_run(read_run_timing(path), events, analyses, k)


def subtract_background(signal: RateResult, background: RateResult) -> NetRate:
    """Net = signal - background (preferred time bases), sigma = sqrt(s1^2 + s2^2)."""
    if signal.rate_per_min is None or background.rate_per_min is None:
        raise ValueError("signal or background rate is unavailable")
    notes = []
    if signal.basis != background.basis:
        notes.append(f"time bases differ (signal {signal.basis}, background {background.basis})")
    return NetRate(signal.rate_per_min - background.rate_per_min,
                   math.hypot(signal.sigma_per_min, background.sigma_per_min),
                   signal.rate_per_min, background.rate_per_min, tuple(notes))


# ---------------------------------------------------------------- geometry --
def _overlap_mm2(a, b) -> float:
    dx = min(a.x_mm + a.width_mm / 2, b.x_mm + b.width_mm / 2) - max(a.x_mm - a.width_mm / 2, b.x_mm - b.width_mm / 2)
    dy = min(a.y_mm + a.length_mm / 2, b.y_mm + b.length_mm / 2) - max(a.y_mm - a.length_mm / 2,
                                                                       b.y_mm - b.length_mm / 2)
    return max(dx, 0.0) * max(dy, 0.0)


def coincidence_area_cm2(layout) -> float | None:
    """Area (cm2) in which a muon crosses every layer: summed pairwise overlap of the layer-0 and layer-1
    plints (2 layers), or the plint area (1 layer). Plint coordinates are panel-local, so the two layers
    are assumed vertically aligned. None when it cannot be determined (or the overlap is zero)."""
    try:
        layers = layout.layers()
        plints = layout.effective_plints()
        if len(layers) == 1:
            area = sum(p.width_mm * p.length_mm for p in plints if p.layer == layers[0])
        elif len(layers) == 2:
            first = [p for p in plints if p.layer == layers[0]]
            second = [p for p in plints if p.layer == layers[1]]
            area = sum(_overlap_mm2(a, b) for a in first for b in second)
        else:
            return None
    except (AttributeError, TypeError, ValueError):
        return None
    return area / 100.0 if area > 0 and math.isfinite(area) else None


def flux_per_cm2(rate: float | None, sigma: float | None, area_cm2: float | None):
    """(flux, sigma) per cm2 per minute, or None without a rate or a positive area."""
    if rate is None or sigma is None or area_cm2 is None or not area_cm2 > 0:
        return None
    return rate / area_cm2, sigma / area_cm2


# -------------------------------------------------------------------- text --
def _fmt(rate, sigma, unit="/min") -> str:
    return "n/a" if rate is None else f"{rate:.2f} ± {sigma:.2f} {unit}"


def _when(value) -> str:
    return "unknown" if value is None else value.isoformat(timespec="seconds")


def format_summary(timing: RunTiming, result: RateResult, *, blocks: BlockResult | None = None,
                   background: RateResult | None = None, background_timing: RunTiming | None = None,
                   net: NetRate | None = None, area_cm2: float | None = None,
                   settings: Sequence[str] = ()) -> str:
    """Plain-text summary for the lab log."""
    lines = ["Muon rate summary", f"Run folder: {timing.directory}",
             f"Started: {_when(timing.created_at)}", f"Finished: {_when(timing.finished_at)}"]
    if timing.execution_mode != "unknown":
        lines.append(f"Execution mode: {timing.execution_mode}; status: {timing.status}")
    lines += list(settings)
    lines += [f"Trigger events: {result.trigger_events}",
              f"Accepted (coincidence in every layer): {result.accepted} ({result.accepted_fraction * 100:.1f}%)"]
    wall = "n/a" if result.wall_seconds is None else f"{result.wall_seconds:.1f} s"
    batch = "n/a" if result.batch_seconds is None else f"{result.batch_seconds:.1f} s"
    lines += [f"Wall-clock time: {wall} -> {_fmt(result.wall_rate_per_min, result.wall_sigma_per_min)}",
              f"Batch-completion time: {batch} -> {_fmt(result.batch_rate_per_min, result.batch_sigma_per_min)}",
              f"Muon rate ({result.basis} basis): {_fmt(result.rate_per_min, result.sigma_per_min)}"]
    if background is not None:
        bg_name = f" ({background_timing.directory})" if background_timing else ""
        lines.append(f"Background{bg_name}: {_fmt(background.rate_per_min, background.sigma_per_min)} "
                     f"({background.accepted} accepted of {background.trigger_events})")
    if net is not None:
        lines.append(f"Net rate: {_fmt(net.rate_per_min, net.sigma_per_min)}")
    if area_cm2:
        lines.append(f"Coincidence area: {area_cm2:.2f} cm2")
        rate_sigma = (net.rate_per_min, net.sigma_per_min) if net else (result.rate_per_min, result.sigma_per_min)
        flux = flux_per_cm2(*rate_sigma, area_cm2)
        if flux:
            lines.append(f"Flux{' (net)' if net else ''}: {flux[0]:.4f} ± {flux[1]:.4f} /cm2/min")
    if blocks is not None:
        if blocks.blocks:
            lines.append(f"Blocks ({len(blocks.blocks)}, equal batch count):")
            for i, b in enumerate(blocks.blocks, 1):
                lines.append(f"  {i}: batches {b.first_batch}-{b.last_batch}, {b.accepted} accepted, "
                             f"{_fmt(b.rate_per_min, b.sigma_per_min)}")
            if blocks.chi2_per_dof is not None:
                lines.append(f"  chi2/dof = {blocks.chi2:.2f}/{blocks.dof} = {blocks.chi2_per_dof:.2f}: "
                             f"{blocks.message}")
        elif blocks.message:
            lines.append(f"Blocks: {blocks.message}")
    for note in list(result.warnings) + (list(net.warnings) if net else []):
        lines.append(f"Warning: {note}")
    return "\n".join(lines) + "\n"


def is_inside(path, folder) -> bool:
    """True when ``path`` lies in (or is) ``folder``; summaries must never be written into run folders."""
    try:
        Path(path).resolve().relative_to(Path(folder).resolve())
        return True
    except (ValueError, OSError):
        return False
