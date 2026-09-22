"""Append-only compatible CSV data and atomically replaced run manifests.

Mirrors `radioroc.data.hold_scan.HoldRunWriter`'s atomic-replace `update()`
and fsync-per-write discipline, with two differences: the CSV schema is the
fixed `batch,event,channel,hg,lg` shape `scripts/plot_acquisition_spectrum.py`
already parses, and an `append` mode lets a run continue an existing
`events.csv`/`metadata.json` pair (used by `scripts/radioroc_acquire.py`'s
`--append` flag) instead of always refusing to overwrite.
"""

import csv
import json
import os
from pathlib import Path
import tempfile


class AcquisitionRunWriter:
    POINT_FIELDS = ["batch", "event", "channel", "hg", "lg"]

    def __init__(self, directory: Path, manifest: dict, *, append: bool = False):
        self.directory = Path(directory)
        self.metadata_path = self.directory / "metadata.json"
        self.csv_path = self.directory / "events.csv"
        self.append = append
        self.directory.mkdir(parents=True, exist_ok=True)
        csv_exists = self.csv_path.exists()
        metadata_exists = self.metadata_path.exists()
        if append and (csv_exists or metadata_exists):
            # Continuing a prior run: keep the existing CSV rows and replace
            # the manifest the same way update() always does. If only one of
            # the two files survived a prior run that was interrupted between
            # their own two exclusive-creates, still write whichever is
            # missing so the CSV always has its header and the manifest
            # always exists.
            if not csv_exists:
                self._header(self.csv_path, self.POINT_FIELDS)
            self.update(manifest)
        else:
            for path in (self.metadata_path, self.csv_path):
                if path.exists():
                    raise FileExistsError(f"refusing to overwrite run file: {path}")
            # Exclusive creation also reserves the directory against competing jobs.
            with self.metadata_path.open("x", encoding="utf-8") as stream:
                json.dump(manifest, stream, indent=2, allow_nan=False)
                self._sync(stream)
            self._header(self.csv_path, self.POINT_FIELDS)
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
            csv.DictWriter(stream, fieldnames=self.POINT_FIELDS).writerow(row)
            self._sync(stream)

    def append_events(self, rows: list[dict]) -> None:
        with self.csv_path.open("a", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=self.POINT_FIELDS)
            for row in rows:
                writer.writerow(row)
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
