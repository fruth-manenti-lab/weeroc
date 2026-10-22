"""Offline analysis for the muon view: pedestals, clusters, coincidence, angle. Pure Python."""

from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import median

from radioroc.data.muon_types import ClusterHit, DetectorLayout, EventAnalysis, MuonEvent

SATURATED_RAW = 4000.0


def events_from_rows(rows, *, channels=None) -> list[MuonEvent]:
    """Group events.csv rows (dicts with batch, event, channel, hg, lg) into MuonEvents, in file order.

    Values may be str or float; rows with non-numeric or non-finite values are skipped. Events are keyed by
    (batch, event) in first-seen order; ``channels`` (optional) keeps only those channels.
    """
    wanted = None if channels is None else {int(c) for c in channels}
    groups: dict[tuple[int, int], tuple[dict, dict]] = {}
    for row in rows:
        try:
            batch, event, channel = int(float(row["batch"])), int(float(row["event"])), int(float(row["channel"]))
            hg, lg = float(row["hg"]), float(row["lg"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (math.isfinite(hg) and math.isfinite(lg)):
            continue
        if wanted is not None and channel not in wanted:
            continue
        hg_map, lg_map = groups.setdefault((batch, event), ({}, {}))
        hg_map[channel] = hg
        lg_map[channel] = lg
    return [MuonEvent(i, b, e, hg, lg) for i, ((b, e), (hg, lg)) in enumerate(groups.items())]


def load_events(path: Path) -> list[MuonEvent]:
    """Read an acquisition run directory / events.csv with radioroc.data.acquisition_reader and group it.

    All rows of the CSV are used (every append segment), not only the manifest's current segment.
    """
    from radioroc.data.acquisition_reader import read_acquisition_run

    saved = read_acquisition_run(Path(path))
    events = events_from_rows(saved.rows)
    if not events:
        raise ValueError(f"no events found in acquisition run {path}")
    return events


def estimate_pedestals(events: list[MuonEvent], *, gain: str = "hg") -> dict[int, float]:
    """Per-channel pedestal = median over the events (robust against the few bright events)."""
    values: dict[int, list[float]] = {}
    for event in events:
        for ch, v in (event.hg if gain == "hg" else event.lg).items():
            values.setdefault(ch, []).append(v)
    return {ch: float(median(v)) for ch, v in sorted(values.items())}


def load_pedestals(path, *, gain: str = "hg") -> dict[int, float]:
    """Pedestals from a JSON file ({"schema_version":1,"gain":"hg","pedestals":{"6":92.0}}) or from a saved
    acquisition run directory (per-channel median of that run's events). Raises ValueError with a clear text."""
    path = Path(path)
    if path.is_dir():
        try:
            events = load_events(path)
        except (OSError, ValueError) as exc:
            raise ValueError(f"cannot use {path} as a pedestal run: {exc}") from exc
        return estimate_pedestals(events, gain=gain)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read pedestal file {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("pedestals"), dict):
        raise ValueError(f"{path} is not a pedestal file (schema_version 1 with a 'pedestals' object expected)")
    if data.get("gain", "hg") != gain:
        raise ValueError(f"pedestal file is for gain {data.get('gain')!r}, expected {gain!r}")
    result = {}
    try:
        for key, value in data["pedestals"].items():
            channel, value = int(key), float(value)
            if not 0 <= channel < 64 or not math.isfinite(value):
                raise ValueError(key)
            result[channel] = value
    except (TypeError, ValueError) as exc:
        raise ValueError(f"pedestal file {path} has an invalid channel or value") from exc
    if not result:
        raise ValueError(f"pedestal file {path} contains no pedestals")
    return dict(sorted(result.items()))


def save_pedestals(path, pedestals: dict[int, float], gain: str = "hg") -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"schema_version": 1, "gain": gain,
            "pedestals": {str(int(ch)): float(v) for ch, v in sorted(pedestals.items())}}
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def pedestals_look_biased(events: list[MuonEvent], pedestals: dict[int, float], threshold_counts: float, *,
                          gain: str = "hg") -> list[int]:
    """Channels whose pedestal exceeds the 10th percentile of that channel's values by more than
    threshold_counts (probably a median estimate that contains muon signal). A warning heuristic only."""
    values: dict[int, list[float]] = {}
    for event in events:
        for ch, v in (event.hg if gain == "hg" else event.lg).items():
            values.setdefault(ch, []).append(v)
    biased = []
    for ch, vals in sorted(values.items()):
        if ch not in pedestals:
            continue
        vals.sort()
        p10 = vals[int(0.1 * (len(vals) - 1))]
        if pedestals[ch] - p10 > threshold_counts:
            biased.append(ch)
    return biased


def _pitch(layout: DetectorLayout, layer: int) -> float:
    sipms = layout.in_layer(layer)
    nearest = []
    for s in sipms:
        others = [math.hypot(s.x_mm - o.x_mm, s.y_mm - o.y_mm) for o in sipms if o is not s]
        others = [d for d in others if d > 0]
        if others:
            nearest.append(min(others))
    return float(median(nearest)) if nearest else 3.0 * layout.sipm_size_mm


def _amplitudes(event: MuonEvent, layout: DetectorLayout, pedestals: dict[int, float], gain: str) -> dict[int, float]:
    values = event.hg if gain == "hg" else event.lg
    amps = {ch: values[ch] - pedestals.get(ch, 0.0) for ch in layout.channels() if ch in values}
    if gain == "hg":
        saturated = [ch for ch in amps if event.hg[ch] >= SATURATED_RAW and ch in event.lg]
        if saturated:
            # No lg pedestals are supplied, so the lg baseline is the median lg of this event's channels
            # (most are at pedestal). Saturated hg is replaced by lg_amp * median(hg_amp / lg_amp) over the
            # unsaturated SiPMs of the event; without a usable ratio the saturated value is kept.
            lg_base = median(event.lg[ch] for ch in event.lg)
            ratios = []
            for ch in amps:
                if ch in saturated or ch not in event.lg or event.hg[ch] >= SATURATED_RAW:
                    continue
                lg_amp = event.lg[ch] - lg_base
                if lg_amp > 2.0 and amps[ch] > 0:
                    ratios.append(amps[ch] / lg_amp)
            if ratios:
                ratio = median(ratios)
                for ch in saturated:
                    amps[ch] = max(amps[ch], ratio * (event.lg[ch] - lg_base))
    return amps


def analyse_event(event: MuonEvent, layout: DetectorLayout, pedestals: dict[int, float], *,
                  threshold_counts: float = 40.0, neighbour_fraction: float = 0.1,
                  gain: str = "hg") -> EventAnalysis:
    """Cluster each layer around its brightest SiPM above threshold, centroid, coincidence, angle.

    Amplitude = value - pedestal for each layout channel present in the event (missing -> 0, negatives
    kept). Cluster = seed (brightest SiPM of the layer, must reach ``threshold_counts``) plus SiPMs with
    amplitude >= neighbour_fraction * seed and >= 0.25 * threshold within 2.5 nearest-neighbour pitches of
    the seed. Saturated hg (>= 4000 raw) is replaced by the lg amplitude scaled by the event's median
    hg/lg ratio when available (see _amplitudes), else the saturated value is used. The angle is the zenith
    of the line through the two layer centroids.
    """
    amps = _amplitudes(event, layout, pedestals, gain)
    layers = layout.layers()
    hits: dict[int, ClusterHit | None] = {}
    for layer in layers:
        sipms = layout.in_layer(layer)
        seed = max(sipms, key=lambda s: amps.get(s.channel, 0.0))
        seed_amp = amps.get(seed.channel, 0.0)
        if seed_amp < threshold_counts:
            hits[layer] = None
            continue
        radius = 2.5 * _pitch(layout, layer)
        members = [s for s in sipms
                   if s is seed or (amps.get(s.channel, 0.0) >= neighbour_fraction * seed_amp
                                    and amps.get(s.channel, 0.0) >= 0.25 * threshold_counts
                                    and math.hypot(s.x_mm - seed.x_mm, s.y_mm - seed.y_mm) <= radius)]
        members.sort(key=lambda s: amps.get(s.channel, 0.0), reverse=True)
        charge = sum(amps.get(s.channel, 0.0) for s in members)
        if charge > 0:
            x = sum(amps.get(s.channel, 0.0) * s.x_mm for s in members) / charge
            y = sum(amps.get(s.channel, 0.0) * s.y_mm for s in members) / charge
        else:
            x, y = seed.x_mm, seed.y_mm
        hits[layer] = ClusterHit(layer, tuple(s.channel for s in members), x, y, charge)
    coincidence = bool(layers) and all(hits[l] is not None for l in layers)
    angle = None
    if len(layers) == 2 and coincidence:
        a, b = hits[layers[0]], hits[layers[1]]
        angle = math.degrees(math.atan(math.hypot(b.x_mm - a.x_mm, b.y_mm - a.y_mm) / layout.layer_spacing_mm))
    return EventAnalysis(event.index, amps, hits, coincidence, angle)
