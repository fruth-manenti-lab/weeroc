"""Read a real vendor-collected `readable_adc_acq.txt` acquisition file.

Reader only -- there is no evidenced consumer for a vendor-format *writer*
in this codebase today, so writing one is explicitly out of scope.

The format was reconstructed from real disassembly of `adc.pyc`
(`local_artifacts/extracted/RadiorocUI_2_2_0_5.exe_extracted/
PYZ-00.pyz_extracted/adc.pyc`, `write_out_file`/`get_acq_setup`,
`marshal.loads`+`dis`, per `AGENTS.md`'s vendor-evidence policy), recorded
in `IMPLEMENTATION_STATUS.md`'s RADIOROC 35 entry:

- Line 1: the file's own path (a vendor quirk -- `write_out_file` writes
  `fp + "\\n"` first, `fp` being the very path it was opened with). Not
  meaningful data; accepted but not validated.
- Lines 2-3: `get_acq_setup(ui)`'s return value, one string ending in `\\n`
  with one embedded `\\n` (confirmed directly in `get_acq_setup`'s
  `co_consts`, which contain the literal `'\\nNb acq: '` and a trailing
  `'\\n'`) -- free-form prose (trigger type, T1/T2, window width, nb
  triggers, Nb acq, Reset_n mode, trigger source, hold delay). Captured
  verbatim; not parsed for structured fields (no fixed grammar guaranteed
  stable across vendor versions, and nothing here needs those values --
  our own manifest already has them, typed, for our own runs).
- Line 4: the header row, built in `write_out_file` as the literal string
  `'#Acq'` followed by `',HG{ch},LG{ch}'` for `ch in range(64)` (confirmed
  by disassembly: `LOAD_CONST '#Acq'`, then a `range(64)` loop emitting
  `',HG{ch}' + ',LG{ch}'` per channel) -- i.e.
  `#Acq,HG0,LG0,HG1,LG1,...,HG63,LG63`.
- Remaining lines: one row per acquisition/event index (1-based -- the
  bytecode writes `str(i + 1)`), `{index},{hg0},{lg0},{hg1},{lg1},...,
  {hg63},{lg63}` -- 129 comma-separated values, HG then LG interleaved per
  channel, always all 64 channels regardless of which channels were
  actually saved.

`rows` is normalized into the same per-(event, channel) shape
`SavedAcquisitionRun.rows` uses (`channel`/`hg`/`lg`), so a vendor file can
be diffed directly against one of our own saved runs. The vendor file's
`acq` (its 1-based acquisition/event index) plays the role our own
`event` field does -- both identify "which physical event within this
row's group this is" -- but they are not the same concept: the vendor has
no per-batch grouping at all (`acq` numbers every acquisition in the whole
file), while our own `event` restarts within each `batch`. Compare `acq`
against our own `event` only after accounting for that difference (e.g.
per-batch offsets), never assume they line up 1:1 across an entire run.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


_N_CHANNELS = 64
_HEADER = "#Acq" + "".join(f",HG{ch},LG{ch}" for ch in range(_N_CHANNELS))
_EXPECTED_COLUMNS = 1 + 2 * _N_CHANNELS  # index + (hg, lg) per channel


@dataclass(frozen=True)
class VendorAcquisitionFile:
    setup_text: str
    rows: tuple[dict, ...]
    warnings: tuple[str, ...]


def read_vendor_acquisition_file(path: Path) -> VendorAcquisitionFile:
    """Parse a vendor `readable_adc_acq.txt` file.

    Raises `NotImplementedError` for the vendor's other on-disk format,
    `raw_adc_acq.txt` (every received byte, one per line, formatted as
    hex -- a different, weirder byte-per-line encoding; see `get_hg_lg` in
    `adc.pyc` for anyone who later wants to add support for it). This
    reader only implements the human/analysis-facing `readable` format the
    vendor GUI's own `load_adc_data` dispatches to by checking whether the
    filename contains the substring `"raw"`.
    """
    path = Path(path)
    if "raw" in path.name:
        raise NotImplementedError(
            f"{path.name} looks like the vendor's raw byte-per-line hex format "
            "(filename contains 'raw'); only the 'readable' wide-CSV format is "
            "supported by this reader (see get_hg_lg in adc.pyc for that format)"
        )

    # Universal-newline translation (the default `newline=None`) normalizes
    # the vendor Windows app's likely \r\n line endings to \n before we
    # split, so downstream fields never carry a stray trailing \r.
    with path.open(encoding="utf-8") as stream:
        lines = stream.read().split("\n")

    if len(lines) < 4:
        raise ValueError(f"vendor acquisition file is too short to contain a header: {path}")

    # Line 0 is the file's own path -- present but not meaningful data.
    setup_text = lines[1] + "\n" + lines[2]
    header = lines[3]
    if header != _HEADER:
        raise ValueError(f"unrecognized vendor acquisition header: {header!r}; expected {_HEADER!r}")

    warnings: list[str] = []
    rows: list[dict] = []
    for number, line in enumerate(lines[4:], start=5):
        if line == "":
            continue
        try:
            rows.extend(_parse_data_row(line))
        except ValueError as exc:
            warnings.append(f"malformed data row at line {number}: {exc}; row skipped")

    return VendorAcquisitionFile(setup_text, tuple(rows), tuple(warnings))


def _parse_data_row(line: str) -> list[dict]:
    fields = line.split(",")
    if len(fields) != _EXPECTED_COLUMNS:
        raise ValueError(f"expected {_EXPECTED_COLUMNS} comma-separated values, found {len(fields)}")
    try:
        acq = int(fields[0])
    except ValueError as exc:
        raise ValueError(f"acquisition index {fields[0]!r} is not an integer") from exc
    rows = []
    for channel in range(_N_CHANNELS):
        hg_text, lg_text = fields[1 + 2 * channel], fields[2 + 2 * channel]
        try:
            hg, lg = float(hg_text), float(lg_text)
        except ValueError as exc:
            raise ValueError(f"channel {channel} HG/LG value is not numeric ({hg_text!r}, {lg_text!r})") from exc
        rows.append({"acq": acq, "channel": channel, "hg": hg, "lg": lg})
    return rows
