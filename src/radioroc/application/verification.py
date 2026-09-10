"""Side-effect-safe readback checks for threshold-scan restoration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from radioroc_client import I2CRow, RadiorocDevice, bits


_FPGA_ADDRESSES = (0, 1, 6)


def _valid_bits(value) -> bool:
    return isinstance(value, str) and len(value) == 8 and not (set(value) - {"0", "1"})


def _fpga_rows(values: Mapping[int, str]) -> list[dict]:
    return [{"address": address, "data": values[address]}
            for address in _FPGA_ADDRESSES if address in values]


def _asic_rows(values: Mapping[tuple[int, int], str], order: Sequence[tuple[int, int]]) -> list[dict]:
    return [{"add": add, "subadd": subadd, "data": values[(add, subadd)]}
            for add, subadd in order if (add, subadd) in values]


def _error(label: str, exc: BaseException) -> str:
    details = []
    seen = set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        details.append(f"{type(current).__name__}: {current}")
        details.extend(f"note: {note}" for note in getattr(current, "__notes__", ()))
        current = current.__cause__ or current.__context__
    return f"{label}: {'; caused by: '.join(details)}"


def verify_threshold_restoration(
    device: RadiorocDevice,
    snapshot,
    expected_asic_registers: Sequence[tuple[int, int]],
    *,
    execution_mode: str,
) -> dict:
    """Compare live FPGA/ASIC state with one in-memory pre-scan snapshot.

    ASIC FIFO reads temporarily alter FPGA I2C controls.  The verifier therefore
    captures live FPGA words first, idles word 60 and restores the exact observed
    word 0 after its FIFO read, then rereads words 0, 1 and 6.  It never writes an
    ASIC register and never fills missing snapshot values from configuration.
    """

    try:
        supplied_registers = list(expected_asic_registers)
    except BaseException as exc:
        supplied_registers = []
        register_list_error = _error("cannot inspect expected ASIC registers", exc)
    else:
        register_list_error = None
    report = {
        "status": "incomplete",
        "execution_mode": execution_mode,
        "expected": {"fpga": [], "asic": []},
        "observed": {"fpga_before_asic": [], "asic": [], "fpga_after_asic": []},
        "mismatches": [],
        "missing": [],
        "errors": [],
        "cleanup": {
            "status": "not_required",
            "word60_idle_attempted": False,
            "word0_restore_attempted": False,
            "errors": [],
        },
    }

    complete_snapshot = True
    if register_list_error is not None:
        complete_snapshot = False
        report["errors"].append(register_list_error)
    snapshot_fpga = None
    snapshot_asic = None
    if not isinstance(snapshot, Mapping):
        complete_snapshot = False
        report["errors"].append("snapshot is absent or is not a mapping")
    else:
        snapshot_fpga = snapshot.get("fpga")
        snapshot_asic = snapshot.get("asic")
        if not isinstance(snapshot_fpga, Mapping):
            complete_snapshot = False
            report["errors"].append("snapshot FPGA state is absent or is not a mapping")
            snapshot_fpga = {}
        if not isinstance(snapshot_asic, Mapping):
            complete_snapshot = False
            report["errors"].append("snapshot ASIC state is absent or is not a mapping")
            snapshot_asic = {}
    snapshot_fpga = snapshot_fpga or {}
    snapshot_asic = snapshot_asic or {}

    expected_fpga = {}
    for address in _FPGA_ADDRESSES:
        if address not in snapshot_fpga:
            complete_snapshot = False
            report["missing"].append({"kind": "snapshot_fpga", "address": address})
            continue
        value = snapshot_fpga[address]
        if not _valid_bits(value):
            complete_snapshot = False
            report["errors"].append(f"snapshot FPGA {address} is not an eight-bit binary value")
            continue
        expected_fpga[address] = value

    expected_asic = {}
    seen = set()
    registers = []
    for register in supplied_registers:
        if (not isinstance(register, tuple) or len(register) != 2 or
                isinstance(register[0], bool) or isinstance(register[1], bool) or
                not isinstance(register[0], int) or not isinstance(register[1], int) or
                not 0 <= register[0] <= 255 or not 0 <= register[1] <= 255):
            complete_snapshot = False
            report["errors"].append(f"invalid expected ASIC register: {register!r}")
            continue
        if register in seen:
            complete_snapshot = False
            report["errors"].append(f"duplicate expected ASIC register: {register!r}")
            continue
        seen.add(register)
        registers.append(register)
        if register not in snapshot_asic:
            complete_snapshot = False
            report["missing"].append({"kind": "snapshot_asic", "add": register[0],
                                      "subadd": register[1]})
            continue
        value = snapshot_asic[register]
        if not _valid_bits(value):
            complete_snapshot = False
            report["errors"].append(
                f"snapshot ASIC {register[0]}/{register[1]} is not an eight-bit binary value")
            continue
        expected_asic[register] = value

    report["expected"]["fpga"] = _fpga_rows(expected_fpga)
    report["expected"]["asic"] = _asic_rows(expected_asic, registers)

    # Without a complete, trustworthy snapshot there is nothing safe to compare
    # and no reason to introduce further I2C side effects.
    if not complete_snapshot:
        return report

    observed_before = {}
    for address in _FPGA_ADDRESSES:
        try:
            value = device.read_word(address)
            if not _valid_bits(value):
                raise ValueError("readback is not an eight-bit binary value")
            observed_before[address] = value
            if address in expected_fpga and value != expected_fpga[address]:
                report["mismatches"].append({"kind": "fpga", "phase": "before_asic",
                                             "address": address, "expected": expected_fpga[address],
                                             "observed": value})
        except BaseException as exc:
            report["errors"].append(_error(f"read FPGA {address} before ASIC verification", exc))
    report["observed"]["fpga_before_asic"] = _fpga_rows(observed_before)

    # All three words are needed to prove that the verifier did not change FPGA
    # state.  In particular, without word 0 the I2C side effect cannot be undone.
    valid_baseline = all(address in observed_before for address in _FPGA_ADDRESSES)
    asic_attempted = bool(registers) and valid_baseline
    observed_asic = {}
    incomplete_readback = False
    if registers and not valid_baseline:
        report["errors"].append("ASIC verification skipped because the FPGA baseline is incomplete")
    elif registers:
        try:
            payload = device.read_fifo([I2CRow(add, subadd, "00000000")
                                        for add, subadd in registers])
            if not isinstance(payload, (bytes, bytearray)):
                raise TypeError("ASIC readback must be bytes")
            if len(payload) != len(registers):
                report["errors"].append(
                    f"read ASIC restoration state: expected {len(registers)} ASIC readback bytes, "
                    f"received {len(payload)}")
                incomplete_readback = True
                for add, subadd in registers:
                    report["missing"].append({"kind": "observed_asic", "add": add,
                                              "subadd": subadd})
            else:
                for register, value in zip(registers, payload):
                    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
                        raise ValueError(f"invalid ASIC readback byte for {register!r}: {value!r}")
                    observed_asic[register] = bits(value, 8)
                    if register in expected_asic and observed_asic[register] != expected_asic[register]:
                        report["mismatches"].append({
                            "kind": "asic", "add": register[0], "subadd": register[1],
                            "expected": expected_asic[register], "observed": observed_asic[register],
                        })
        except BaseException as exc:
            report["errors"].append(_error("read ASIC restoration state", exc))
        finally:
            # Attempt both operations independently, including after a read error.
            report["cleanup"]["word60_idle_attempted"] = True
            try:
                device.write_word(60, "00000000")
            except BaseException as exc:
                report["cleanup"]["errors"].append(_error("idle I2C control", exc))
            report["cleanup"]["word0_restore_attempted"] = True
            try:
                device.write_word(0, observed_before[0])
            except BaseException as exc:
                report["cleanup"]["errors"].append(_error("restore observed FPGA 0", exc))

    report["observed"]["asic"] = _asic_rows(observed_asic, registers)
    if asic_attempted:
        observed_after = {}
        for address in _FPGA_ADDRESSES:
            try:
                value = device.read_word(address)
                if not _valid_bits(value):
                    raise ValueError("readback is not an eight-bit binary value")
                observed_after[address] = value
                if value != observed_before[address]:
                    report["mismatches"].append({
                        "kind": "verifier_fpga_restoration", "address": address,
                        "expected": observed_before[address], "observed": value,
                    })
            except BaseException as exc:
                report["errors"].append(_error(f"reread FPGA {address} after ASIC verification", exc))
        report["observed"]["fpga_after_asic"] = _fpga_rows(observed_after)
        report["cleanup"]["status"] = (
            "failed" if report["cleanup"]["errors"] or len(observed_after) != len(_FPGA_ADDRESSES) or
            any(item["kind"] == "verifier_fpga_restoration" for item in report["mismatches"])
            else "restored"
        )

    if not complete_snapshot or incomplete_readback:
        report["status"] = "incomplete"
    elif report["mismatches"] or report["errors"] or report["cleanup"]["errors"]:
        report["status"] = "failed"
    else:
        report["status"] = "passed"
    return report
