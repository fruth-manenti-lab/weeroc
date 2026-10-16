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

# Per-segment manifest fields. metadata.json's top-level fields always describe
# the latest segment (so pre-segments readers keep working); `segments` holds
# one slim record per append segment so earlier configs are never lost.
SEGMENT_KEYS = ("operation", "created_at", "finished_at", "status", "execution_mode",
                "completed_points", "total_points", "verification", "cleanup", "warnings", "error")


def segment_batch_range(segment: dict) -> tuple[int, int] | None:
    """Return the (start, stop) batch range a segment manifest claims, or None if unknown."""
    try:
        acquisition = segment["operation"]["acquisition"]
        start = acquisition.get("start_batch", 0)
        stop = start + acquisition["batches"]
    except (KeyError, TypeError, AttributeError):
        return None
    if isinstance(start, bool) or isinstance(stop, bool) or not isinstance(start, int) or not isinstance(stop, int):
        return None
    return start, stop


def _segment_record(manifest: dict, segment_id: int) -> dict:
    record = {key: json.loads(json.dumps(manifest[key])) for key in SEGMENT_KEYS if key in manifest}
    record["segment_id"] = segment_id
    return record


class AcquisitionRunWriter:
    POINT_FIELDS = ["batch", "event", "channel", "hg", "lg"]

    def __init__(self, directory: Path, manifest: dict, *, append: bool = False):
        self.directory = Path(directory)
        self.metadata_path = self.directory / "metadata.json"
        self.csv_path = self.directory / "events.csv"
        self.append = append
        self._prior_segments: list[dict] = []
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
            self._prior_segments = self._load_prior_segments(manifest)
            if not csv_exists:
                self._header(self.csv_path, self.POINT_FIELDS)
            self.update(manifest)
        else:
            for path in (self.metadata_path, self.csv_path):
                if path.exists():
                    raise FileExistsError(f"refusing to overwrite run file: {path}")
            # Exclusive creation also reserves the directory against competing jobs.
            with self.metadata_path.open("x", encoding="utf-8") as stream:
                json.dump(self._with_segments(manifest), stream, indent=2, allow_nan=False)
                self._sync(stream)
            self._header(self.csv_path, self.POINT_FIELDS)
        self._sync_directory()

    def _load_prior_segments(self, manifest: dict) -> list[dict]:
        """Existing segment manifests (an old single-segment file becomes segment 0).

        Raises ValueError if the new segment's batch range overlaps an earlier one,
        because (batch, event, channel) must stay unique across the whole run.
        """
        if not self.metadata_path.exists():
            return []
        try:
            existing = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot append: unreadable existing manifest {self.metadata_path}: {exc}") from exc
        if not isinstance(existing, dict):
            raise ValueError("cannot append: existing manifest is not a JSON object")
        segments = existing.get("segments")
        if isinstance(segments, list) and all(isinstance(item, dict) for item in segments):
            prior = [dict(item) for item in segments]
        else:
            prior = [_segment_record(existing, 0)]
        for index, item in enumerate(prior):
            item["segment_id"] = index
        new_range = segment_batch_range(manifest)
        for item in prior:
            old_range = segment_batch_range(item)
            if new_range and old_range and new_range[0] < old_range[1] and old_range[0] < new_range[1]:
                next_free = max(r[1] for r in map(segment_batch_range, prior) if r)
                raise ValueError(
                    f"cannot append: batches {new_range[0]}..{new_range[1] - 1} overlap segment "
                    f"{item['segment_id']} (batches {old_range[0]}..{old_range[1] - 1}); "
                    f"use start_batch >= {next_free}")
        return prior

    def _with_segments(self, manifest: dict) -> dict:
        if not self._prior_segments:
            return manifest  # single-segment run: unchanged legacy shape
        segment_id = len(self._prior_segments)
        merged = dict(manifest)
        merged["segment_id"] = segment_id
        merged["segments"] = [*self._prior_segments, _segment_record(manifest, segment_id)]
        return merged

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
                json.dump(self._with_segments(manifest), stream, indent=2, allow_nan=False)
                self._sync(stream)
            os.replace(temporary, self.metadata_path)
            self._sync_directory()
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
