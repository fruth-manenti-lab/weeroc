"""Shared types for the muon detector view (layout, events, analysis results).

Pure Python, no Qt. A detector is one or two layers of SiPMs. Each SiPM has a board
channel (0..63), a layer (0 or 1) and an (x, y) position in millimetres within its layer.
Layer 1 sits ``layer_spacing_mm`` above layer 0 along z.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path

SCHEMA_VERSION = 1
N_CHANNELS = 64


class LayoutError(ValueError):
    """The detector layout is invalid or a layout file cannot be read."""


@dataclass(frozen=True)
class SiPMPlacement:
    channel: int
    layer: int
    x_mm: float
    y_mm: float


@dataclass
class DetectorLayout:
    sipms: list[SiPMPlacement] = field(default_factory=list)
    layer_spacing_mm: float = 100.0
    sipm_size_mm: float = 6.0
    name: str = "layout"

    # -- queries ------------------------------------------------------------
    def channels(self) -> list[int]:
        return sorted(s.channel for s in self.sipms)

    def layers(self) -> list[int]:
        return sorted({s.layer for s in self.sipms})

    def in_layer(self, layer: int) -> list[SiPMPlacement]:
        return [s for s in self.sipms if s.layer == layer]

    def placement(self, channel: int) -> SiPMPlacement:
        for s in self.sipms:
            if s.channel == channel:
                return s
        raise KeyError(channel)

    # -- validation ---------------------------------------------------------
    def validate(self) -> None:
        seen = set()
        for s in self.sipms:
            if not isinstance(s.channel, int) or not 0 <= s.channel < N_CHANNELS:
                raise LayoutError(f"channel {s.channel!r} must be a whole number 0..{N_CHANNELS - 1}")
            if s.channel in seen:
                raise LayoutError(f"channel {s.channel} is used by more than one SiPM")
            seen.add(s.channel)
            if s.layer not in (0, 1):
                raise LayoutError(f"layer {s.layer!r} must be 0 or 1")
            for value in (s.x_mm, s.y_mm):
                if not isinstance(value, (int, float)) or value != value or abs(value) > 1e5:
                    raise LayoutError(f"position {value!r} is not a usable number of millimetres")
        if not self.layer_spacing_mm > 0:
            raise LayoutError("layer_spacing_mm must be positive")
        if not self.sipm_size_mm > 0:
            raise LayoutError("sipm_size_mm must be positive")

    # -- construction -------------------------------------------------------
    @classmethod
    def grid(cls, rows: int, cols: int, pitch_mm: float = 10.0, layers: int = 1, first_channel: int = 0,
             layer_spacing_mm: float = 100.0, sipm_size_mm: float = 6.0, name: str = "grid") -> "DetectorLayout":
        """A rows x cols grid per layer, centred on (0, 0); channels run on across layers."""
        if layers not in (1, 2):
            raise LayoutError("layers must be 1 or 2")
        sipms = []
        channel = first_channel
        for layer in range(layers):
            for r in range(rows):
                for c in range(cols):
                    x = (c - (cols - 1) / 2) * pitch_mm
                    y = (r - (rows - 1) / 2) * pitch_mm
                    sipms.append(SiPMPlacement(channel, layer, x, y))
                    channel += 1
        layout = cls(sipms, layer_spacing_mm, sipm_size_mm, name)
        layout.validate()
        return layout

    # -- json ---------------------------------------------------------------
    def to_dict(self) -> dict:
        return {"schema_version": SCHEMA_VERSION, "name": self.name,
                "layer_spacing_mm": self.layer_spacing_mm, "sipm_size_mm": self.sipm_size_mm,
                "sipms": [{"channel": s.channel, "layer": s.layer, "x_mm": s.x_mm, "y_mm": s.y_mm}
                          for s in sorted(self.sipms, key=lambda s: s.channel)]}

    @classmethod
    def from_dict(cls, data) -> "DetectorLayout":
        if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
            raise LayoutError("not a detector layout file (schema_version 1 expected)")
        try:
            sipms = [SiPMPlacement(int(s["channel"]), int(s["layer"]), float(s["x_mm"]), float(s["y_mm"]))
                     for s in data["sipms"]]
            layout = cls(sipms, float(data["layer_spacing_mm"]), float(data["sipm_size_mm"]),
                         str(data.get("name", "layout")))
        except (KeyError, TypeError, ValueError) as exc:
            raise LayoutError(f"layout file is incomplete or malformed: {exc}") from exc
        layout.validate()
        return layout

    def save_json(self, path) -> Path:
        self.validate()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        return path

    @classmethod
    def load_json(cls, path) -> "DetectorLayout":
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise LayoutError(f"cannot read layout file: {exc}") from exc
        return cls.from_dict(data)


@dataclass(frozen=True)
class MuonEvent:
    """One triggered event: raw ADC values per channel (as stored in events.csv)."""
    index: int                      # running index in the replay list
    batch: int
    event: int
    hg: dict[int, float]            # channel -> high-gain ADC counts
    lg: dict[int, float]            # channel -> low-gain ADC counts
    truth: dict | None = None       # simulator only: {"hit_xy": {layer: (x, y)}, "angle_deg": float, "is_muon": bool}


@dataclass(frozen=True)
class ClusterHit:
    layer: int
    channels: tuple[int, ...]       # SiPMs in the cluster, brightest first
    x_mm: float                     # charge-weighted centroid
    y_mm: float
    charge: float                   # summed pedestal-subtracted counts


@dataclass(frozen=True)
class EventAnalysis:
    event_index: int
    amplitudes: dict[int, float]    # channel -> pedestal-subtracted counts (negative values kept)
    hits: dict[int, ClusterHit | None]   # layer -> cluster or None
    coincidence: bool               # a cluster in every layer of the layout
    angle_deg: float | None         # zenith angle of the line through the layer centroids, if two layers hit
