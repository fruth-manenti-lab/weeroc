"""Pedestal (zero-signal ADC baseline) results: compute, save and load. Pure Python, no Qt.

A pedestal run is a forced-trigger acquisition with no input pulses. The per-channel
median is the baseline that muon analysis subtracts. The spread is a ROBUST sd
(1.4826 x median absolute deviation): a stray pulse in a few events (a real muon hitting
during a forced trigger) does not inflate it, while a channel that is noisy or has
pulses in many events still gives a large value, which is the "pulses present?" indicator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics

PEDESTALS_FILENAME = "pedestals.json"
SCHEMA_VERSION = 1
MIN_EVENTS = 5
N_CHANNELS = 64


@dataclass(frozen=True)
class ChannelPedestal:
    channel: int
    hg_median: float
    hg_sd: float
    lg_median: float
    lg_sd: float
    n: int


@dataclass(frozen=True)
class PedestalSet:
    channels: dict[int, ChannelPedestal]
    created_at: str
    source_run: str | None = None
    settings: dict = field(default_factory=dict)

    def hg(self) -> dict[int, float]:
        return {ch: p.hg_median for ch, p in sorted(self.channels.items())}

    def lg(self) -> dict[int, float]:
        return {ch: p.lg_median for ch, p in sorted(self.channels.items())}

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "pedestals",
            "created_at": self.created_at,
            "source_run": self.source_run,
            "settings": dict(self.settings),
            "channels": {
                str(ch): {"hg_median": p.hg_median, "hg_sd": p.hg_sd,
                          "lg_median": p.lg_median, "lg_sd": p.lg_sd, "n": p.n}
                for ch, p in sorted(self.channels.items())},
        }

    @classmethod
    def from_dict(cls, d) -> "PedestalSet":
        if not isinstance(d, dict) or d.get("schema_version") != SCHEMA_VERSION \
                or not isinstance(d.get("channels"), dict):
            raise ValueError("not a pedestal set (schema_version 1 with a 'channels' object expected)")
        channels = {}
        try:
            for key, entry in d["channels"].items():
                ch = int(key)
                if not 0 <= ch < N_CHANNELS:
                    raise ValueError(f"channel {ch} outside 0..{N_CHANNELS - 1}")
                values = {name: float(entry[name]) for name in ("hg_median", "hg_sd", "lg_median", "lg_sd")}
                if not all(math.isfinite(v) for v in values.values()):
                    raise ValueError(f"non-finite value for channel {ch}")
                channels[ch] = ChannelPedestal(ch, n=int(entry["n"]), **values)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid pedestal set: {exc}") from exc
        source = d.get("source_run")
        settings = d.get("settings")
        return cls(channels, str(d.get("created_at", "")),
                   None if source is None else str(source),
                   dict(settings) if isinstance(settings, dict) else {})


def _sd(values, median_unused=None) -> float:
    """Robust sd: 1.4826 x median absolute deviation (falls back to the plain sd if the MAD is 0)."""
    if len(values) < 2:
        return 0.0
    median = statistics.median(values)
    mad = statistics.median(abs(v - median) for v in values)
    return 1.4826 * mad if mad > 0 else statistics.pstdev(values)


def compute_pedestals(rows, channels=None, *, settings=None, source_run=None) -> PedestalSet:
    """Median and population sd per channel from rows of dicts with channel/hg/lg.

    Channels with fewer than 5 events are rejected (left out). `channels` restricts the set."""
    wanted = None if channels is None else {int(c) for c in channels}
    hg: dict[int, list[float]] = {}
    lg: dict[int, list[float]] = {}
    for row in rows:
        ch = int(row["channel"])
        if wanted is not None and ch not in wanted:
            continue
        h, l = float(row["hg"]), float(row["lg"])
        if not (math.isfinite(h) and math.isfinite(l)):
            continue
        hg.setdefault(ch, []).append(h)
        lg.setdefault(ch, []).append(l)
    result = {}
    for ch in sorted(hg):
        if len(hg[ch]) < MIN_EVENTS:
            continue
        result[ch] = ChannelPedestal(ch, statistics.median(hg[ch]), _sd(hg[ch]),
                                     statistics.median(lg[ch]), _sd(lg[ch]), len(hg[ch]))
    return PedestalSet(result, datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       None if source_run is None else str(source_run), dict(settings or {}))


def to_muon_pedestals(ps: PedestalSet) -> dict[int, float]:
    """High-gain medians as ``radioroc.data.muon_analysis`` expects them."""
    return ps.hg()


def save_pedestals_json(path, ps: PedestalSet) -> Path:
    """Write the schema-1 file. It also carries ``gain`` and ``pedestals`` (HG medians) so
    ``muon_analysis.load_pedestals`` reads the same file directly."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = ps.to_dict()
    data["gain"] = "hg"
    data["pedestals"] = {str(ch): v for ch, v in ps.hg().items()}
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return path


def load_pedestals_json(path) -> PedestalSet:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read pedestal file {path}: {exc}") from exc
    return PedestalSet.from_dict(data)


def find_pedestals_for_run(run_dir) -> PedestalSet | None:
    """``run_dir/pedestals.json`` as a PedestalSet, or None when absent or unreadable."""
    try:
        return load_pedestals_json(Path(run_dir) / PEDESTALS_FILENAME)
    except (ValueError, OSError, TypeError):
        return None
