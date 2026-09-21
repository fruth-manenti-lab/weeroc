"""Append-only compatible CSV data and atomically replaced run manifests."""

import csv
import json
import os
from pathlib import Path
import tempfile


class ScurveRunWriter:
    def __init__(self, directory: Path, channels: list[int], manifest: dict):
        self.directory = Path(directory)
        self.metadata_path = self.directory / "metadata.json"
        self.csv_path = self.directory / "scurve.csv"
        self.point_fields = ["DAC", *(f"ch{ch}" for ch in channels)]
        self.directory.mkdir(parents=True, exist_ok=True)
        for path in (self.metadata_path, self.csv_path):
            if path.exists():
                raise FileExistsError(f"refusing to overwrite run file: {path}")
        # Exclusive creation also reserves the directory against competing jobs.
        with self.metadata_path.open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2, allow_nan=False)
            self._sync(stream)
        self._header(self.csv_path, self.point_fields)
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
