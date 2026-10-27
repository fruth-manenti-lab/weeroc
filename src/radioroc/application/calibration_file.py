"""Calibration file: save/load the operator's calibration settings (no Qt, no hardware).

The chip's per-channel threshold trims live only in its registers and are lost
on a power cycle. This file keeps the settings and the trims from the most
recent *verified* autocalibration run so they can be restored later.
Loading a file never touches the chip; see ``build_reapply_operation``.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

SCHEMA_VERSION = 1
N_CHANNELS = 64
DEFAULT_FOLDER = Path("radioroc_runs") / "calibration"
_AUTOCAL_NAME = "autocalibration_metadata.json"


class CalibrationFileError(ValueError):
    """A calibration file is unreadable or invalid; the message is student-readable."""


def default_filename(now=None) -> str:
    return f"calibration-{(now or datetime.now()):%Y%m%d-%H%M%S}.json"


def package_version() -> str | None:
    try:
        from importlib.metadata import version
        return version("radioroc")
    except Exception:
        return None


def find_autocalibration_trims(directory=None, runs_root=None):
    """Return ``(trims_dict_or_None, message)`` from an autocalibration run folder.

    `directory` is tried first (the run the window just made); otherwise the
    newest ``autocalibration_metadata.json`` under `runs_root` is used. Only a
    completed run with ``calibration_status == "verified"`` supplies trims.
    The dict has ``run_directory``, ``trim_kind`` ("T1"/"T2"), ``trims``
    ({channel: 0..63}) and ``status``.
    """
    candidates = []
    if directory:
        candidates.append(Path(directory) / _AUTOCAL_NAME)
    elif runs_root and Path(runs_root).is_dir():
        found = sorted(Path(runs_root).rglob(_AUTOCAL_NAME),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        candidates.extend(found[:20])
    if not candidates:
        return None, "no autocalibration run found"
    last_reason = "no autocalibration run found"
    for path in candidates:
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            last_reason = f"cannot read {path}: {exc}"
            continue
        if not isinstance(manifest, dict):
            last_reason = f"{path} is not a JSON object"
            continue
        if manifest.get("status") != "completed" or manifest.get("calibration_status") != "verified":
            last_reason = (f"latest autocalibration run {path.parent} is not completed and "
                           f"verified (status={manifest.get('status')!r}, "
                           f"calibration_status={manifest.get('calibration_status')!r})")
            continue
        after = manifest.get("calibration_after")
        if not isinstance(after, dict) or not after:
            last_reason = f"autocalibration run {path.parent} recorded no trims"
            continue
        try:
            trims = {str(int(k)): int(v) for k, v in after.items()}
        except (TypeError, ValueError):
            last_reason = f"autocalibration run {path.parent} has malformed trims"
            continue
        operation = manifest.get("operation")
        t1 = operation.get("t1", True) if isinstance(operation, dict) else True
        return {"run_directory": str(path.parent), "trim_kind": "T1" if t1 else "T2",
                "trims": trims, "status": "verified"}, "ok"
    return None, last_reason


def build_document(*, channels, trigger_channel, trigger_channel_2, auto_triggers,
                   operating_threshold_dac, bias_voltage_text="", note="",
                   autocalibration=None, hold_scan=None, trigger_gain_code=None, pedestals=None, now=None) -> dict:
    doc = {
        "schema_version": SCHEMA_VERSION,
        "created": (now or datetime.now()).astimezone().isoformat(timespec="seconds"),
        "app_version": package_version(),
        "channels": sorted(int(c) for c in channels),
        "trigger_channel": int(trigger_channel),
        "trigger_channel_2": int(trigger_channel_2),
        "auto_triggers": bool(auto_triggers),
        "operating_threshold_dac": int(operating_threshold_dac),
        "bias_voltage_text": str(bias_voltage_text),
        "note": str(note),
        "autocalibration": autocalibration,
    }
    if hold_scan:
        doc["hold_scan"] = hold_scan
    if trigger_gain_code is not None:
        doc["trigger_gain_code"] = int(trigger_gain_code)
    if pedestals is not None:
        doc["pedestals"] = pedestals if isinstance(pedestals, dict) else pedestals.to_dict()
    return doc


def save_document(path, doc) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return path


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _channel(name, value):
    if not _is_int(value) or not 0 <= value < N_CHANNELS:
        raise CalibrationFileError(f"'{name}' must be a whole number 0..{N_CHANNELS - 1}, got {value!r}")
    return value


def validate_document(data) -> dict:
    """Check a parsed file; return the cleaned document or raise CalibrationFileError."""
    if not isinstance(data, dict):
        raise CalibrationFileError("this is not a calibration file (top level is not an object)")
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise CalibrationFileError(
            f"unsupported calibration file version {version!r}; this app reads version {SCHEMA_VERSION}")
    channels = data.get("channels")
    if not isinstance(channels, list):
        raise CalibrationFileError("'channels' must be a list of channel numbers")
    channels = sorted({_channel("channels", c) for c in channels})
    t1 = _channel("trigger_channel", data.get("trigger_channel"))
    t2 = _channel("trigger_channel_2", data.get("trigger_channel_2"))
    auto = data.get("auto_triggers")
    if not isinstance(auto, bool):
        raise CalibrationFileError("'auto_triggers' must be true or false")
    dac = data.get("operating_threshold_dac")
    if not _is_int(dac) or not 0 <= dac <= 1023:
        raise CalibrationFileError(f"'operating_threshold_dac' must be a whole number 0..1023, got {dac!r}")
    for key in ("bias_voltage_text", "note"):
        if not isinstance(data.get(key, ""), str):
            raise CalibrationFileError(f"'{key}' must be text")
    autocal = data.get("autocalibration")
    if autocal is not None:
        if not isinstance(autocal, dict):
            raise CalibrationFileError("'autocalibration' must be an object or null")
        kind = autocal.get("trim_kind")
        if kind not in ("T1", "T2"):
            raise CalibrationFileError("'autocalibration.trim_kind' must be \"T1\" or \"T2\"")
        trims = autocal.get("trims")
        if not isinstance(trims, dict) or not trims:
            raise CalibrationFileError("'autocalibration.trims' must be a non-empty object")
        clean = {}
        for key, value in trims.items():
            try:
                channel = int(key)
            except (TypeError, ValueError):
                raise CalibrationFileError(f"trim channel {key!r} is not a number") from None
            _channel("trim channel", channel)
            if not _is_int(value) or not 0 <= value <= 63:
                raise CalibrationFileError(f"trim for channel {channel} must be a whole number 0..63, got {value!r}")
            clean[channel] = value
        autocal = dict(autocal, trims=clean)
    hold = data.get("hold_scan")
    if hold is not None and not isinstance(hold, dict):
        raise CalibrationFileError("'hold_scan' must be an object")
    if hold is not None and "hold_delay_ns" in hold:
        value = hold["hold_delay_ns"]
        if not _is_int(value) or not 0 <= value <= 100000:
            raise CalibrationFileError(f"'hold_delay_ns' must be a whole number 0..100000, got {value!r}")
    gain = data.get("trigger_gain_code")
    if gain is not None and (not _is_int(gain) or not 1 <= gain <= 63):
        raise CalibrationFileError(f"'trigger_gain_code' must be a whole number 1..63, got {gain!r}")
    pedestals = data.get("pedestals")
    if pedestals is not None:
        from radioroc.data.pedestals import PedestalSet
        try:
            pedestals = PedestalSet.from_dict(pedestals)
        except ValueError as exc:
            raise CalibrationFileError(f"'pedestals' is invalid: {exc}") from exc
    return {"channels": channels, "trigger_channel": t1, "trigger_channel_2": t2,
            "auto_triggers": auto, "operating_threshold_dac": dac,
            "bias_voltage_text": data.get("bias_voltage_text", ""), "note": data.get("note", ""),
            "autocalibration": autocal, "hold_scan": hold, "trigger_gain_code": gain,
            "pedestals": pedestals,
            "created": data.get("created"), "app_version": data.get("app_version")}


def load_document(path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise CalibrationFileError(f"cannot open the file: {exc}") from exc
    except (UnicodeError, ValueError) as exc:
        raise CalibrationFileError(f"the file is not valid JSON: {exc}") from exc
    return validate_document(data)


def build_reapply_operation(autocalibration: dict):
    """Build the existing, verified ChannelConfigOperation that writes only the trim DACs.

    Sent through ``ConnectionWorker.apply_channel_config`` (writes are read back).
    """
    from radioroc.application.channel_config import ChannelConfigOperation
    trims = dict(autocalibration["trims"])
    if autocalibration["trim_kind"] == "T1":
        return ChannelConfigOperation(t1_calibration_dac_values=trims, verify=True)
    return ChannelConfigOperation(t2_calibration_dac_values=trims, verify=True)
