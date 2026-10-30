"""Append-only compatible CSV data and atomically replaced run manifests."""

import csv
import json
import os
from pathlib import Path
import tempfile


class HoldRunWriter:
    def __init__(self, directory: Path, channels: list[int], manifest: dict, *, x_name: str):
        self.directory = Path(directory)
        self.metadata_path = self.directory / "metadata.json"
        self.csv_path = self.directory / "holdscan.csv"
        # Every individual ADC sample (one row per hold point, event, channel), so the
        # per-point mean/stdev in holdscan.csv can be re-plotted as raw points.
        self.samples_path = self.directory / "holdscan_samples.csv"
        self.sample_fields = [x_name, "event", "channel", "hg", "lg"]
        self.point_fields = [x_name, *(field for ch in channels for field in (
            f"ch{ch}_hg_mean", f"ch{ch}_hg_stdev", f"ch{ch}_lg_mean", f"ch{ch}_lg_stdev", f"ch{ch}_count")), "requested", "received"]
        self.directory.mkdir(parents=True, exist_ok=True)
        for path in (self.metadata_path, self.csv_path, self.samples_path):
            if path.exists():
                raise FileExistsError(f"refusing to overwrite run file: {path}")
        # Exclusive creation also reserves the directory against competing jobs.
        with self.metadata_path.open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2, allow_nan=False)
            self._sync(stream)
        self._header(self.csv_path, self.point_fields)
        self._header(self.samples_path, self.sample_fields)
        self._sync_directory()

    def _sync_directory(self):
        if os.name == "posix":
            descriptor = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    @staticmethod
    def _sync(stream):
        stream.flush()
        os.fsync(stream.fileno())

    def _header(self, path, fields):
        with path.open("x", newline="", encoding="utf-8") as stream:
            csv.DictWriter(stream, fieldnames=fields).writeheader()
            self._sync(stream)

    def append_point(self, row: dict) -> None:
        with self.csv_path.open("a", newline="", encoding="utf-8") as stream:
            csv.DictWriter(stream, fieldnames=self.point_fields).writerow(row)
            self._sync(stream)

    def append_samples(self, rows: list[dict]) -> None:
        with self.samples_path.open("a", newline="", encoding="utf-8") as stream:
            csv.DictWriter(stream, fieldnames=self.sample_fields).writerows(rows)
            self._sync(stream)

    def update(self, manifest: dict) -> None:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.directory,
                                             prefix=".metadata-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(manifest, stream, indent=2, allow_nan=False)
                self._sync(stream)
            os.replace(temporary, self.metadata_path)
            self._sync_directory()
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
