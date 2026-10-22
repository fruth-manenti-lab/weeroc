"""Synthetic muon events for a DetectorLayout (demo / simulation mode). Pure Python (stdlib only)."""

from __future__ import annotations

import math
import random

from radioroc.data.muon_types import DetectorLayout, MuonEvent

ADC_MAX = 4095.0
LG_RATIO = 8.0          # low-gain amplitude is the high-gain amplitude / LG_RATIO
MAX_ZENITH_DEG = 60.0
_MAX_TRACK_TRIES = 200


def _zenith(rng: random.Random) -> float:
    """Zenith angle (radians) for intensity cos^2(theta) per solid angle, limited to 0..60 degrees."""
    c60 = math.cos(math.radians(MAX_ZENITH_DEG))
    cos_t = (1.0 - rng.random() * (1.0 - c60 ** 3)) ** (1.0 / 3.0)
    return math.acos(cos_t)


def _track(layout: DetectorLayout, layers: list[int], rng: random.Random):
    """Pick a straight track entering over the first layer's plint footprint(s) (area weighted); only tracks
    that cross a plint of every layer are kept (a coincidence trigger would never record the others).
    Falls back to a vertical track."""
    plints = layout.effective_plints()
    by_layer = {layer: [p for p in plints if p.layer == layer] for layer in layers}
    first = by_layer[layers[0]]
    weights = [p.width_mm * p.length_mm for p in first]
    for _ in range(_MAX_TRACK_TRIES):
        p0 = rng.choices(first, weights)[0] if len(first) > 1 else first[0]
        x0 = rng.uniform(p0.x_mm - p0.width_mm / 2, p0.x_mm + p0.width_mm / 2)
        y0 = rng.uniform(p0.y_mm - p0.length_mm / 2, p0.y_mm + p0.length_mm / 2)
        theta, phi = _zenith(rng), rng.uniform(0.0, 2.0 * math.pi)
        hits = {}
        for layer in layers:
            z = layout.layer_spacing_mm * layer
            hits[layer] = (x0 + math.tan(theta) * math.cos(phi) * z, y0 + math.tan(theta) * math.sin(phi) * z)
        if all(any(abs(hits[l][0] - p.x_mm) <= p.width_mm / 2 and abs(hits[l][1] - p.y_mm) <= p.length_mm / 2
                   for p in by_layer[l]) for l in layers):
            return hits, theta
    return {layer: (x0, y0) for layer in layers}, 0.0


def simulate_events(layout: DetectorLayout, n_events: int, *, seed: int = 1, muon_fraction: float = 0.8,
                    pedestal_hg: float = 95.0, pedestal_lg: float = 90.0, noise_counts: float = 3.0,
                    peak_counts: float = 600.0, sharing_length_mm: float = 8.0,
                    dark_hit_probability: float = 0.005) -> tuple[list[MuonEvent], dict[int, float]]:
    """Return (events, pedestals_hg). Deterministic for a given seed.

    Every event holds all channels of the layout. Muon tracks are restricted to those that enter over the first
    layer's plint(s) and cross a plint of every layer. Non-muon events carry dark-count bumps (30..80 counts, hg only),
    at least one per event. Only the high-gain pedestals are returned (the analysis input).
    """
    layout.validate()
    rng = random.Random(seed)
    layers = layout.layers()
    channels = layout.channels()
    pedestals = {ch: pedestal_hg for ch in channels}
    events = []
    for index in range(n_events):
        hg_amp = {ch: 0.0 for ch in channels}
        truth: dict
        if layers and rng.random() < muon_fraction:
            hits, theta = _track(layout, layers, rng)
            for layer in layers:
                hx, hy = hits[layer]
                fluct = rng.lognormvariate(0.0, 0.25)
                for s in layout.in_layer(layer):
                    d = math.hypot(s.x_mm - hx, s.y_mm - hy)
                    hg_amp[s.channel] += peak_counts * math.exp(-d / sharing_length_mm) * fluct
            truth = {"hit_xy": {layer: hits[layer] for layer in layers},
                     "angle_deg": math.degrees(theta), "is_muon": True}
        else:
            bumped = [ch for ch in channels if rng.random() < dark_hit_probability]
            if not bumped and channels:
                bumped = [rng.choice(channels)]
            for ch in bumped:
                hg_amp[ch] = rng.uniform(30.0, 80.0)
            truth = {"is_muon": False}
        hg, lg = {}, {}
        for ch in channels:
            hg[ch] = min(ADC_MAX, max(0.0, pedestal_hg + hg_amp[ch] + rng.gauss(0.0, noise_counts)))
            lg[ch] = min(ADC_MAX, max(0.0, pedestal_lg + hg_amp[ch] / LG_RATIO + rng.gauss(0.0, noise_counts / 2)))
        events.append(MuonEvent(index, index // 10, index % 10, hg, lg, truth))
    return events, pedestals
