"""Shared types for the muon detector view (layout, events, analysis results).

Pure Python, no Qt. A detector is one or two layers of SiPMs. Each SiPM has a board
channel (0..63), a layer (0 or 1) and an (x, y) position in millimetres within its layer.
Layer 1 sits ``layer_spacing_mm`` above layer 0 along z.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import re
from pathlib import Path

SCHEMA_VERSION = 1
N_CHANNELS = 64


class LayoutError(ValueError):
    """The detector layout is invalid or a layout file cannot be read."""


def parse_channel_list(text: str) -> list[int]:
    """Parse '6', '6, 7, 9-12' or '0-31' into a list of channels in the order written.

    Raises LayoutError naming the problem (unreadable item, descending range, channel outside
    0..63, channel listed twice). An empty or blank string gives an empty list."""
    channels: list[int] = []
    seen: set[int] = set()
    for token in str(text).split(","):
        token = token.strip()
        if not token:
            continue
        match = re.fullmatch(r"(\d+)\s*(?:-\s*(\d+))?", token)
        if match is None:
            raise LayoutError(f'cannot read "{token}"')
        first = int(match.group(1))
        last = first if match.group(2) is None else int(match.group(2))
        if last < first:
            raise LayoutError(f'range "{token}" must go upwards')
        for channel in (first, last):
            if not 0 <= channel < N_CHANNELS:
                raise LayoutError(f"channel {channel} is outside 0..{N_CHANNELS - 1}")
        for channel in range(first, last + 1):
            if channel in seen:
                raise LayoutError(f"channel {channel} is listed twice")
            seen.add(channel)
            channels.append(channel)
    return channels


def format_channel_list(channels) -> str:
    """Compact text for a set of channels, e.g. [0, 1, 2, 3, 6] -> '0-3, 6' (the inverse of parse_channel_list)."""
    values = sorted(set(channels))
    parts = []
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and values[j + 1] == values[j] + 1:
            j += 1
        if j - i >= 1:
            parts.append(f"{values[i]}-{values[j]}")
        else:
            parts.append(str(values[i]))
        i = j + 1
    return ", ".join(parts)


@dataclass(frozen=True)
class SiPMPlacement:
    channel: int
    layer: int
    x_mm: float
    y_mm: float


@dataclass(frozen=True)
class PlintSpec:
    """A scintillator bar (plint): centre (x, y) within its layer panel; x extent = width, y extent = length."""
    layer: int
    x_mm: float
    y_mm: float
    width_mm: float
    length_mm: float
    thickness_mm: float = 10.0


AUTO_PLINT_MARGIN_MM = 5.0
AUTO_PLINT_THICKNESS_MM = 10.0


@dataclass
class DetectorLayout:
    sipms: list[SiPMPlacement] = field(default_factory=list)
    layer_spacing_mm: float = 100.0
    sipm_size_mm: float = 6.0
    name: str = "layout"
    plints: list[PlintSpec] = field(default_factory=list)

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

    def effective_plints(self) -> list[PlintSpec]:
        """Explicit plints if any, else one auto plint per layer: SiPM bounding box + 5 mm each side."""
        if self.plints:
            return list(self.plints)
        auto = []
        for layer in self.layers():
            xs = [s.x_mm for s in self.in_layer(layer)]
            ys = [s.y_mm for s in self.in_layer(layer)]
            m = AUTO_PLINT_MARGIN_MM
            auto.append(PlintSpec(layer, (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2,
                                  max(xs) - min(xs) + 2 * m, max(ys) - min(ys) + 2 * m, AUTO_PLINT_THICKNESS_MM))
        return auto

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
        for p in self.plints:
            if p.layer not in (0, 1):
                raise LayoutError(f"plint layer {p.layer!r} must be 0 or 1")
            for value in (p.x_mm, p.y_mm):
                if not isinstance(value, (int, float)) or value != value or abs(value) > 1e5:
                    raise LayoutError(f"plint position {value!r} is not a usable number of millimetres")
            for value in (p.width_mm, p.length_mm, p.thickness_mm):
                if not isinstance(value, (int, float)) or not 0 < value < 1e5:
                    raise LayoutError(f"plint size {value!r} must be between 0 and 100000 mm")
        if not self.layer_spacing_mm > 0:
            raise LayoutError("layer_spacing_mm must be positive")
        if not self.sipm_size_mm > 0:
            raise LayoutError("sipm_size_mm must be positive")

    # -- construction -------------------------------------------------------
    @classmethod
    def grid(cls, rows: int, cols: int, pitch_mm: float = 10.0, layers: int = 1, first_channel: int = 0,
             layer_spacing_mm: float = 100.0, sipm_size_mm: float = 6.0, name: str = "grid",
             plint_width_mm: float | None = None, plint_length_mm: float | None = None,
             plint_thickness_mm: float | None = None) -> "DetectorLayout":
        """A rows x cols grid per layer, centred on (0, 0); channels run on across layers.

        If any plint size is given, one explicit plint per layer is added, centred on the layer grid
        (missing sizes default to the auto plint size / 10 mm thickness)."""
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
        if any(v is not None for v in (plint_width_mm, plint_length_mm, plint_thickness_mm)):
            auto = layout.effective_plints()
            for p in auto:
                layout.plints.append(PlintSpec(
                    p.layer, 0.0, 0.0,
                    p.width_mm if plint_width_mm is None else float(plint_width_mm),
                    p.length_mm if plint_length_mm is None else float(plint_length_mm),
                    p.thickness_mm if plint_thickness_mm is None else float(plint_thickness_mm)))
        layout.validate()
        return layout

    @classmethod
    def from_channel_lists(cls, layer_channels: dict, columns: int, pitch_mm: float = 10.0,
                           layer_spacing_mm: float = 100.0, sipm_size_mm: float = 6.0,
                           name: str = "channels") -> "DetectorLayout":
        """Layers defined by board channel lists. Each layer's channels (in the order given) fill
        rows of ``columns`` SiPMs (clipped to the channel count), row-major from the bottom-left,
        the block centred on (0, 0) like grid()."""
        if not isinstance(columns, int) or columns < 1:
            raise LayoutError("columns must be a whole number of at least 1")
        sipms = []
        used: dict[int, int] = {}
        for layer in sorted(layer_channels):
            if layer not in (0, 1):
                raise LayoutError(f"layer {layer!r} must be 0 or 1")
            channels = list(layer_channels[layer])
            for channel in channels:
                if channel in used:
                    where = "twice in layer %d" % layer if used[channel] == layer else f"in layers {used[channel]} and {layer}"
                    raise LayoutError(f"channel {channel} is listed {where}")
                used[channel] = layer
            if not channels:
                continue
            cols = min(columns, len(channels))
            rows = math.ceil(len(channels) / cols)
            for i, channel in enumerate(channels):
                r, c = divmod(i, cols)
                sipms.append(SiPMPlacement(channel, layer, (c - (cols - 1) / 2) * pitch_mm,
                                           (r - (rows - 1) / 2) * pitch_mm))
        if not sipms:
            raise LayoutError("no channels given")
        layout = cls(sipms, layer_spacing_mm, sipm_size_mm, name)
        layout.validate()
        return layout

    # -- json ---------------------------------------------------------------
    def to_dict(self) -> dict:
        data = {"schema_version": SCHEMA_VERSION, "name": self.name,
                "layer_spacing_mm": self.layer_spacing_mm, "sipm_size_mm": self.sipm_size_mm,
                "sipms": [{"channel": s.channel, "layer": s.layer, "x_mm": s.x_mm, "y_mm": s.y_mm}
                          for s in sorted(self.sipms, key=lambda s: s.channel)]}
        if self.plints:
            data["plints"] = [{"layer": p.layer, "x_mm": p.x_mm, "y_mm": p.y_mm, "width_mm": p.width_mm,
                               "length_mm": p.length_mm, "thickness_mm": p.thickness_mm} for p in self.plints]
        return data

    @classmethod
    def from_dict(cls, data) -> "DetectorLayout":
        if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
            raise LayoutError("not a detector layout file (schema_version 1 expected)")
        try:
            sipms = [SiPMPlacement(int(s["channel"]), int(s["layer"]), float(s["x_mm"]), float(s["y_mm"]))
                     for s in data["sipms"]]
            plints = [PlintSpec(int(p["layer"]), float(p["x_mm"]), float(p["y_mm"]), float(p["width_mm"]),
                                float(p["length_mm"]), float(p["thickness_mm"]))
                      for p in data.get("plints") or []]
            layout = cls(sipms, float(data["layer_spacing_mm"]), float(data["sipm_size_mm"]),
                         str(data.get("name", "layout")), plints)
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
