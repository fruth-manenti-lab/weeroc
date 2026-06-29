"""Legacy RADIOROC all-in-one workflow script.

This file is kept as a compatibility/reference implementation for the original
prototype workflows. New user-facing work should prefer the focused scripts
(`radioroc_threshold_scan.py`, `radioroc_hold_scan.py`, etc.) and the shared
library in `radioroc_client.py`.
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

import serial


DEFAULT_PORT = "/dev/cu.usbserial-RD3_320"
DEFAULT_CONFIG = Path("configs/radio_default_i2c.csv")
DEFAULT_OUT = Path("radioroc_runs")
N_CHANNELS = 64
FPGA_IO_NAMES = ("io0", "io1", "io2", "io3", "io4")


def bits(value: int, width: int = 8) -> str:
    return format(value, f"0{width}b")


def parse_bits(value: str) -> int:
    return int(str(value).strip(), 2)


def encode_read_request(address: int, length: int = 1) -> bytes:
    if not 0 <= address <= 127:
        raise ValueError("address must be in range 0..127")
    if not 1 <= length <= 65536:
        raise ValueError("length must be in range 1..65536")
    encoded_length = length - 1
    return bytes([0xAA, encoded_length & 0xFF, address | 0x80, (encoded_length >> 8) & 0xFF, 0x55])


def encode_write_request(address: int, payload: bytes) -> bytes:
    if not 0 <= address <= 127:
        raise ValueError("address must be in range 0..127")
    if not 1 <= len(payload) <= 256:
        raise ValueError("payload length must be in range 1..256")
    return bytes([0xAA, len(payload) - 1, address]) + payload + bytes([0x55])


@dataclass
class I2CRow:
    add: int
    subadd: int
    data: str


class RadiorocSerial:
    def __init__(self, port: str, baud: int, timeout: float = 0.5):
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self.ser: serial.Serial | None = None

    def __enter__(self) -> "RadiorocSerial":
        self.ser = serial.Serial(self.port, baudrate=self.baud, timeout=self.timeout, write_timeout=self.timeout)
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()
        return self

    def __exit__(self, *exc: object) -> None:
        if self.ser:
            self.ser.close()

    def _xfer(self, frame: bytes, read_len: int = 0) -> bytes:
        if self.ser is None:
            raise RuntimeError("serial port is not open")
        if read_len > 0:
            self.ser.reset_input_buffer()
        self.ser.write(frame)
        self.ser.flush()
        if read_len <= 0:
            return b""
        data = bytearray()
        deadline = time.monotonic() + max(self.timeout, 0.1)
        while time.monotonic() < deadline:
            chunk = self.ser.read(max(1, read_len - len(data)))
            if chunk:
                data.extend(chunk)
                while data and data[0] != 0xAA:
                    data.pop(0)
                if len(data) >= read_len:
                    candidate = bytes(data[:read_len])
                    if candidate[-1] == 0x55:
                        return candidate
                    data.pop(0)
            else:
                time.sleep(0.001)
        return bytes(data)

    def read_word(self, address: int) -> str:
        last_response = b""
        for _ in range(3):
            response = self._xfer(encode_read_request(address, 1), 5)
            if len(response) == 5 and response[0] == 0xAA and response[-1] == 0x55:
                return bits(response[3], 8)
            last_response = response
            time.sleep(0.01)
        raise RuntimeError(f"bad read_word({address}) response: {last_response.hex(' ')}")

    def read_words(self, address: int, length: int) -> bytes:
        last_response = b""
        for _ in range(3):
            response = self._xfer(encode_read_request(address, length), length + 4)
            if len(response) == length + 4 and response[0] == 0xAA and response[-1] == 0x55:
                return response[3:-1]
            last_response = response
            time.sleep(0.01)
        raise RuntimeError(f"bad read_words({address}, {length}) response: {last_response.hex(' ')}")

    def write_word(self, address: int, word_bits: str) -> None:
        payload = parse_bits(word_bits).to_bytes(1, "little")
        self._xfer(encode_write_request(address, payload))

    def write_words(self, address: int, payload: bytes) -> None:
        offset = 0
        while offset < len(payload):
            chunk = payload[offset : offset + 256]
            self._xfer(encode_write_request(address, chunk))
            offset += len(chunk)


class RadiorocOps:
    def __init__(self, dev: RadiorocSerial, *, dry_run: bool):
        self.dev = dev
        self.dry_run = dry_run
        self.df_i2c: list[I2CRow] = []
        # These are module constants in the official uiroc.i2c code for
        # Radioroc2UI 2.2.0.5.
        self.chip_id = 1
        self.add_length = 8
        self.subadd_length = 8

    def load_default_config(self, path: Path) -> None:
        with path.open(newline="") as fp:
            self.df_i2c = [I2CRow(int(r["add"]), int(r["subadd"]), str(r["data"]).strip()) for r in csv.DictReader(fp)]

    def read_word(self, address: int) -> str:
        return self.dev.read_word(address)

    def write_word(self, address: int, word_bits: str) -> None:
        if self.dry_run:
            print(f"DRY write_word add={address} data={word_bits}")
            return
        self.dev.write_word(address, word_bits)

    def _full_address(self, add: int, subadd: int) -> bytes:
        full = f"{add:0{self.add_length}b}{subadd:0{self.subadd_length}b}"
        return int(full, 2).to_bytes(2, "big")

    def write_register(self, add: int, subadd: int, data: str) -> None:
        row = self.find_row(add, subadd)
        if row is not None:
            row.data = data
        payload = self.chip_id.to_bytes(1, "big") + self._full_address(add, subadd) + parse_bits(data).to_bytes(1, "little")
        self._i2c_fifo_transaction(payload, read=False)

    def write_fifo(self, rows: list[I2CRow]) -> None:
        payload = b"".join(
            self.chip_id.to_bytes(1, "little")
            + self._full_address(row.add, row.subadd)
            + parse_bits(row.data).to_bytes(1, "little")
            for row in rows
        )
        self._i2c_fifo_transaction(payload, read=False)

    def read_fifo(self, rows: list[I2CRow]) -> bytes:
        payload = b"".join(
            (128 + self.chip_id).to_bytes(1, "little") + self._full_address(row.add, row.subadd) + b"\x00"
            for row in rows
        )
        return self._i2c_fifo_transaction(payload, read=True) or b""

    def _i2c_fifo_transaction(self, payload: bytes, *, read: bool) -> bytes | None:
        if self.dry_run:
            kind = "read" if read else "write"
            print(f"DRY i2c_{kind}_fifo {len(payload)} bytes")
            return b"" if read else None
        # Mirrors uiroc.i2c: set bus active, write FIFO at FPGA address 56,
        # trigger transaction through control register 60, wait for status bit.
        add0 = self.dev.read_word(0)
        self.dev.write_word(60, "00000000")
        self.dev.write_word(0, add0[0] + "1" + add0[2:8])
        try:
            for offset in range(0, len(payload), 256):
                chunk = payload[offset : offset + 256]
                self.dev.write_words(56, chunk)
                self.dev.write_word(60, "00000000")
                self.dev.write_word(60, "00000010")
                for _ in range(1000):
                    if self.dev.read_word(4)[7] == "1":
                        break
                else:
                    raise TimeoutError("i2c FIFO transaction timed out")
                self.dev.write_word(60, "00000100")
            if read:
                # Vendor read_fifo reads address 55 before clearing the I2C-active
                # bit in word 0.
                return self.dev.read_words(55, len(payload) // 4)
            return None
        finally:
            self.dev.write_word(0, add0[0] + "0" + add0[2:8])

    def find_row(self, add: int, subadd: int) -> I2CRow | None:
        for row in self.df_i2c:
            if row.add == add and row.subadd == subadd:
                return row
        return None

    def read_register_bits(self, add: int, subadd: int) -> str:
        row = self.find_row(add, subadd)
        fallback = row.data if row is not None else "00000000"
        if self.dry_run:
            return fallback
        try:
            data = self.read_fifo([I2CRow(add, subadd, fallback)])
        except Exception:
            return fallback
        if not data:
            return fallback
        return bits(data[0], 8)

    def rows(self, *, add_lt: int | None = None, subadd: int | None = None) -> list[I2CRow]:
        out = self.df_i2c
        if add_lt is not None:
            out = [r for r in out if r.add < add_lt]
        if subadd is not None:
            out = [r for r in out if r.subadd == subadd]
        return [I2CRow(r.add, r.subadd, r.data) for r in out]

    def apply_default_config(self) -> None:
        if not self.df_i2c:
            raise RuntimeError("default config not loaded")
        self.write_fifo(self.df_i2c)

    def verify_default_config(self, *, limit: int | None = None) -> bool:
        if not self.df_i2c:
            raise RuntimeError("default config not loaded")
        rows = self.df_i2c[:limit] if limit is not None else self.df_i2c
        readback = self.read_fifo(rows)
        if self.dry_run:
            print(f"DRY verify_default_config rows={len(rows)}")
            return True

        mismatches = []
        for row, value in zip(rows, readback):
            expected = parse_bits(row.data)
            if value != expected:
                mismatches.append((row.add, row.subadd, expected, value))

        print(f"Verified {len(rows)} I2C default rows: {len(rows) - len(mismatches)} ok, {len(mismatches)} mismatch")
        for add, subadd, expected, value in mismatches[:20]:
            print(f"  mismatch add={add} subadd={subadd}: expected={bits(expected)} read={bits(value)}")
        if len(mismatches) > 20:
            print(f"  ... {len(mismatches) - 20} more mismatches")
        return not mismatches

    def initialize_fpga(self) -> None:
        # Mirrors the official UI connection sequence after firmware readback.
        self.write_word(0, "00111111")
        self.write_word(1, "01000000")

    def configure_scurve_firmware(self, *, clock_index: int, edge_or_level: bool) -> None:
        if not 0 <= clock_index <= 3:
            raise ValueError("clock_index must be in range 0..3")
        w1 = self.read_word(1) if not self.dry_run else "00000000"
        self.write_word(1, w1[:4] + bits(clock_index, 2) + w1[6:])

        w3 = self.read_word(3) if not self.dry_run else "00000000"
        self.write_word(3, w3[:-1] + str(int(edge_or_level)))

    def set_threshold_dac(self, dac: int, *, t1: bool) -> None:
        dac_bits = bits(dac, 10)
        if t1:
            self.write_register(65, 2, "000000" + dac_bits[:2])
            self.write_register(65, 1, dac_bits[2:])
        else:
            self.write_register(65, 2, dac_bits[4:] + "00")
            self.write_register(65, 3, "0000" + dac_bits[:4])

    def set_trigger_preamp_gain(self, gain: int, *, channels: list[int]) -> None:
        if not 1 <= gain <= 63:
            raise ValueError("trigger preamp gain code must be in range 1..63; 1=max gain, 63=min gain")
        rows = []
        for ch in channels:
            row = self.find_row(ch, 1)
            if row is None:
                continue
            current = parse_bits(row.data)
            compensation = current & 0xC0
            rows.append(I2CRow(ch, 1, bits(compensation | gain, 8)))
        if not rows:
            raise RuntimeError("no trigger preamp gain rows found for selected channels")
        print(f"Setting trigger preamp paT gain code {gain} on channels {channels}")
        self.write_fifo(rows)

    def set_mask_for_channel(self, channel: int, *, t1: bool, enabled: bool) -> None:
        row = self.find_row(channel, 6)
        if row is None:
            return
        data = list(row.data)
        data[3 if t1 else 4] = "1" if enabled else "0"
        self.write_register(channel, 6, "".join(data))

    def set_ctest_for_channel(self, channel: int, enabled: bool) -> None:
        row = self.find_row(channel, 7)
        if row is None:
            return
        data = list(row.data)
        data[3] = "1" if enabled else "0"
        self.write_register(channel, 7, "".join(data))

    def prepare_scurve_masks(self, *, t1: bool, use_mask: bool, use_ctest: bool) -> None:
        clps_t = "00010000" if t1 else "00100000"
        self.write_fifo([I2CRow(66, ch, clps_t) for ch in range(N_CHANNELS)])
        if use_mask:
            rows = self.rows(add_lt=N_CHANNELS, subadd=6)
            for row in rows:
                data = list(row.data)
                data[3 if t1 else 4] = "0"
                row.data = "".join(data)
            self.write_fifo(rows)
        if use_ctest:
            rows = self.rows(add_lt=N_CHANNELS, subadd=7)
            for row in rows:
                data = list(row.data)
                data[3] = "0"
                row.data = "".join(data)
            self.write_fifo(rows)

    @staticmethod
    def _accurate_delay_ms(delay_ms: float) -> None:
        if delay_ms <= 0:
            return
        deadline = time.perf_counter() + delay_ms / 1000.0
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return
            if remaining > 0.003:
                time.sleep(remaining - 0.001)

    def scurve(
        self,
        dacs: list[int],
        *,
        t1: bool,
        use_mask: bool,
        use_ctest: bool,
        channels: list[int],
        out_csv: Path,
        clock_index: int,
        edge_or_level: bool,
        stop_after_all_low: int = 0,
        low_threshold: float = 0.5,
    ) -> None:
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        self.configure_scurve_firmware(clock_index=clock_index, edge_or_level=edge_or_level)
        self.prepare_scurve_masks(t1=t1, use_mask=use_mask, use_ctest=use_ctest)
        saved_w1 = self.read_word(1) if not self.dry_run else "00000000"
        header = ["DAC"] + [f"ch{ch}" for ch in channels]
        low_rows = 0
        try:
            with out_csv.open("w", newline="") as fp:
                writer = csv.writer(fp)
                writer.writerow(header)
                for dac in dacs:
                    self.set_threshold_dac(dac, t1=t1)
                    time.sleep(0.001)
                    values = []
                    for ch in channels:
                        self.write_word(6, bits(ch))
                        if use_mask:
                            self.set_mask_for_channel(ch, t1=t1, enabled=True)
                        if use_ctest:
                            self.set_ctest_for_channel(ch, enabled=True)
                        # Mirrors original sequence: reset, gate/pulse, latch, then
                        # read pulse/scurve counters from FPGA words 8 and 9.
                        self.write_word(1, saved_w1[:6] + "00")
                        self.write_word(1, saved_w1[:6] + "10")
                        self.write_word(1, saved_w1[:6] + "11")
                        time.sleep(0.2 if self.dry_run else (220 / (10**clock_index)) / 1000)
                        if self.dry_run:
                            pulse_data, scurve_data = 0, 0
                        else:
                            pulse_data, fifo9 = self.dev.read_words(8, 2)
                            scurve_data = min(fifo9, 200)
                        if pulse_data >= 200 and scurve_data <= 200:
                            values.append(round(scurve_data * 100.0 / pulse_data, 1))
                        else:
                            print(f"pulse data: {pulse_data}", flush=True)
                            values.append(math.nan)
                        if use_mask:
                            self.set_mask_for_channel(ch, t1=t1, enabled=False)
                        if use_ctest:
                            self.set_ctest_for_channel(ch, enabled=False)
                        self.write_word(1, saved_w1[:6] + "10")
                    writer.writerow([dac] + values)
                    fp.flush()
                    print(f"scurve dac={dac} values={values[:8]}{'...' if len(values) > 8 else ''}", flush=True)
                    has_valid_value = any(not math.isnan(v) for v in values)
                    all_low = has_valid_value and all(math.isnan(v) or v <= low_threshold for v in values)
                    if stop_after_all_low > 0 and all_low:
                        low_rows += 1
                        if low_rows >= stop_after_all_low:
                            print(
                                f"scurve early stop after {low_rows} rows <= {low_threshold}% at dac={dac}",
                                flush=True,
                            )
                            break
                    else:
                        low_rows = 0
        finally:
            try:
                if use_mask or use_ctest:
                    self.prepare_scurve_masks(t1=t1, use_mask=use_mask, use_ctest=use_ctest)
                self.write_word(1, saved_w1[:6] + "00")
            except Exception as exc:
                print(f"warning: scurve cleanup failed: {exc}", flush=True)

    def threshold_scan(
        self,
        dacs: list[int],
        *,
        t1: bool,
        use_mask: bool,
        use_ctest: bool,
        channels: list[int],
        out_csv: Path,
        trigger_window_ms: float,
        averages: int,
    ) -> None:
        if trigger_window_ms <= 0:
            raise ValueError("trigger_window_ms must be positive")
        if averages < 1:
            raise ValueError("averages must be at least 1")

        out_csv.parent.mkdir(parents=True, exist_ok=True)
        self.prepare_scurve_masks(t1=t1, use_mask=use_mask, use_ctest=use_ctest)
        saved_w1 = self.read_word(1) if not self.dry_run else "00000000"
        header = ["DAC"] + [f"ch{ch}" for ch in channels]
        start_time = time.perf_counter()
        try:
            with out_csv.open("w", newline="") as fp:
                writer = csv.writer(fp)
                writer.writerow(header)
                for dac in dacs:
                    self.set_threshold_dac(dac, t1=t1)
                    values = []
                    for ch in channels:
                        self.write_word(6, bits(ch))
                        if use_mask:
                            self.set_mask_for_channel(ch, t1=t1, enabled=True)
                        if use_ctest:
                            self.set_ctest_for_channel(ch, enabled=True)

                        rates = []
                        for _ in range(averages):
                            # Mirrors the vendor threshold scan: reset counter,
                            # open counting window, wait, close window, read count.
                            self.write_word(1, "01" + saved_w1[2:8])
                            self.write_word(1, "00" + saved_w1[2:8])
                            self.write_word(1, "10" + saved_w1[2:8])
                            if self.dry_run:
                                trigger_count = 0
                            else:
                                self._accurate_delay_ms(trigger_window_ms)
                                self.write_word(1, "00" + saved_w1[2:8])
                                trigger_count = int.from_bytes(self.dev.read_words(96, 4), "little")
                            rates.append(trigger_count / (trigger_window_ms / 1000.0))
                        values.append(statistics.mean(rates))

                        if use_mask:
                            self.set_mask_for_channel(ch, t1=t1, enabled=False)
                        if use_ctest:
                            self.set_ctest_for_channel(ch, enabled=False)
                    writer.writerow([dac] + [round(v, 6) for v in values])
                    fp.flush()
                    print(f"threshold dac={dac} hz={values[:8]}{'...' if len(values) > 8 else ''}", flush=True)
        finally:
            try:
                if use_mask or use_ctest:
                    self.prepare_scurve_masks(t1=t1, use_mask=use_mask, use_ctest=use_ctest)
                self.write_word(1, saved_w1)
            except Exception as exc:
                print(f"warning: threshold scan cleanup failed: {exc}", flush=True)
            total_time = time.perf_counter() - start_time
            print(f"thresholdscan measurement time: {total_time:.3f} seconds", flush=True)

    def configure_adc_external_hold(
        self,
        *,
        trigger_channel: int,
        hold_delay_ns: int,
        conversion_delay_ns: int,
        nb_acq: int,
        trigger_type: int,
        trigger_source: int,
        rstn_manual: bool,
        ext_trig: bool,
        peak_sensing: bool,
        adc_window_ns: int,
        adc_nb_trig: int,
    ) -> None:
        if not 0 <= trigger_channel < N_CHANNELS:
            raise ValueError("trigger_channel must be in range 0..63")
        if hold_delay_ns < 0 or hold_delay_ns % 5 != 0:
            raise ValueError("hold_delay_ns must be non-negative and divisible by 5")
        if conversion_delay_ns < 0 or conversion_delay_ns % 40 != 0:
            raise ValueError("conversion_delay_ns must be non-negative and divisible by 40")
        if nb_acq < 1 or nb_acq > 255:
            raise ValueError("nb_acq must be in range 1..255")
        if not 0 <= trigger_type <= 3:
            raise ValueError("trigger_type must be in range 0..3")
        if not 0 <= trigger_source <= 7:
            raise ValueError("trigger_source must be in range 0..7")
        if adc_window_ns < 0 or adc_window_ns % 5 != 0:
            raise ValueError("adc_window_ns must be non-negative and divisible by 5")
        if not 0 <= adc_nb_trig <= 63:
            raise ValueError("adc_nb_trig must be in range 0..63")

        ext_hold_code = hold_delay_ns // 5
        if ext_hold_code > 0xFFF:
            raise ValueError("external hold delay code must fit in 12 bits; max delay is 20475 ns")

        i2c65_12_bits = self.read_register_bits(65, 12)
        # Vendor holdscan external mode sets the ASIC hold source to external.
        if peak_sensing:
            self.write_register(65, 12, i2c65_12_bits[:2] + "01" + "0000")
        else:
            self.write_register(65, 12, i2c65_12_bits[:3] + "1" + i2c65_12_bits[4:])

        ext_hold_bits = bits(ext_hold_code, 12)
        w22 = "00" + bits(trigger_channel, 6)
        saved_w23 = self.read_word(23) if (peak_sensing and not self.dry_run) else "00000000"
        w23 = "01" + saved_w23[2:] if peak_sensing else "00000000"
        w24 = bits(adc_window_ns // 5, 8)
        peak_or_ext_trig = peak_sensing or ext_trig
        w25 = bits(trigger_source, 3) + str(int(rstn_manual)) + "1" + str(int(peak_or_ext_trig)) + bits(trigger_type, 2)
        w26 = ext_hold_bits[4:]
        w27 = "00" + bits(adc_nb_trig, 6)
        w30 = ext_hold_bits[:4] + bits(0, 3)
        w31 = bits(conversion_delay_ns // 40, 8)

        self.write_word(22, w22)
        self.write_word(23, w23)
        self.write_word(24, w24)
        self.write_word(25, w25)
        self.write_word(26, w26)
        self.write_word(27, w27)
        self.write_word(30, w30)
        self.write_word(31, w31)
        self.write_word(21, bits(nb_acq))

    def configure_adc_internal_hold(self, *, trigger_channel: int, hold_code: int, nb_acq: int) -> None:
        if not 0 <= trigger_channel < N_CHANNELS:
            raise ValueError("trigger_channel must be in range 0..63")
        if not 0 <= hold_code <= 255:
            raise ValueError("internal hold code must be in range 0..255")
        if nb_acq < 1 or nb_acq > 255:
            raise ValueError("nb_acq must be in range 1..255")

        i2c65_12 = self.read_register_bits(65, 12)
        self.write_register(65, 12, i2c65_12[:2] + "10" + i2c65_12[4:])
        self.write_register(65, 8, bits(hold_code))

        saved_w23 = self.read_word(23) if not self.dry_run else "00000000"
        self.write_word(31, "11111111")
        self.write_word(25, "01110100")
        self.write_word(22, "00" + bits(trigger_channel, 6))
        self.write_word(23, "00" + saved_w23[2:])
        self.write_word(21, bits(nb_acq))

    def acquire_adc_batch(
        self,
        *,
        nb_acq: int,
        timeout_s: float = 5.0,
        synchro_trigger: bool = False,
    ) -> tuple[list[list[float]], list[list[float]]]:
        if nb_acq < 1 or nb_acq > 255:
            raise ValueError("nb_acq must be in range 1..255")
        if self.dry_run:
            return [[math.nan] * nb_acq for _ in range(N_CHANNELS)], [[math.nan] * nb_acq for _ in range(N_CHANNELS)]

        saved_w2 = self.read_word(2)
        self.write_word(21, bits(nb_acq))
        self.write_word(2, saved_w2[:1] + "1" + saved_w2[3:])
        self.write_word(2, saved_w2[:1] + "0" + saved_w2[3:])
        self.write_word(2, saved_w2[0] + "1" + saved_w2[2:])
        self.write_word(2, saved_w2[0] + "0" + saved_w2[2:])

        if synchro_trigger:
            self.pulse_synchro_trigger(count=nb_acq + 1, period_ms=1.0)

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            w4 = self.read_word(4)
            if w4[5] == "1":
                break
            time.sleep(0.01)
        else:
            raise TimeoutError("ADC acquisition timed out waiting for FPGA word 4 bit 5")

        count_words = self.read_word(29) + self.read_word(28)
        total_nb_acq = int(int(count_words, 2) / 256)
        if total_nb_acq <= 0:
            return [[] for _ in range(N_CHANNELS)], [[] for _ in range(N_CHANNELS)]

        payload = self.dev.read_words(20, total_nb_acq * N_CHANNELS * 4)
        lg = [[] for _ in range(N_CHANNELS)]
        hg = [[] for _ in range(N_CHANNELS)]
        ch = 0
        for i in range(0, len(payload) - 3, 4):
            lg[ch].append(0.25 * int.from_bytes(payload[i : i + 2], "big"))
            hg[ch].append(0.25 * int.from_bytes(payload[i + 2 : i + 4], "big"))
            ch = 0 if ch == N_CHANNELS - 1 else ch + 1
        return hg, lg

    def pulse_synchro_trigger(self, *, count: int, period_ms: float) -> None:
        if count < 1:
            raise ValueError("sync pulse count must be at least 1")
        if period_ms < 0:
            raise ValueError("sync pulse period must be non-negative")
        saved_w22 = self.read_word(22) if not self.dry_run else "00000000"
        for i in range(count):
            self.write_word(22, "1" + saved_w22[1:])
            self.write_word(22, "0" + saved_w22[1:])
            if period_ms > 0 and i != count - 1:
                time.sleep(period_ms / 1000.0)

    def read_fpga_io_mux(self) -> dict[str, int]:
        # Vendor firmware_options.set_io packs IO4..IO0 as 5 three-bit fields:
        # word78 gets the first 7 bits, word77 gets the last 8 bits.
        if self.dry_run:
            return {name: 0 for name in FPGA_IO_NAMES}
        w77 = self.read_word(77)
        w78 = self.read_word(78)
        packed = w78[-7:] + w77
        return {
            "io4": int(packed[0:3], 2),
            "io3": int(packed[3:6], 2),
            "io2": int(packed[6:9], 2),
            "io1": int(packed[9:12], 2),
            "io0": int(packed[12:15], 2),
        }

    def write_fpga_io_mux(self, **updates: int) -> dict[str, int]:
        mux = self.read_fpga_io_mux()
        for name, index in updates.items():
            if name not in FPGA_IO_NAMES:
                raise ValueError(f"unknown FPGA IO name {name!r}; expected one of {', '.join(FPGA_IO_NAMES)}")
            if not 0 <= index <= 7:
                raise ValueError("FPGA IO mux index must be in range 0..7")
            mux[name] = index
        packed = (
            bits(mux["io4"], 3)
            + bits(mux["io3"], 3)
            + bits(mux["io2"], 3)
            + bits(mux["io1"], 3)
            + bits(mux["io0"], 3)
        )
        self.write_word(77, packed[7:15])
        self.write_word(78, packed[0:7])
        return mux

    def scan_fpga_io_mux_for_synchro(self, *, io_name: str, pulses_per_index: int, period_ms: float) -> None:
        if io_name not in FPGA_IO_NAMES:
            raise ValueError(f"unknown FPGA IO name {io_name!r}; expected one of {', '.join(FPGA_IO_NAMES)}")
        if pulses_per_index < 1:
            raise ValueError("pulses_per_index must be at least 1")
        original = self.read_fpga_io_mux()
        print(f"Initial FPGA IO mux: {original}", flush=True)
        try:
            for index in range(8):
                mux = self.write_fpga_io_mux(**{io_name: index})
                print(
                    f"Testing {io_name.upper()} mux index {index}; mux={mux}; "
                    f"pulsing {pulses_per_index} times at {period_ms} ms period",
                    flush=True,
                )
                self.pulse_synchro_trigger(count=pulses_per_index, period_ms=period_ms)
        finally:
            self.write_fpga_io_mux(**original)
            print(f"Restored FPGA IO mux: {original}", flush=True)

    def scan_all_fpga_io_muxes_for_synchro(self, *, pulses_per_index: int, period_ms: float) -> None:
        if pulses_per_index < 1:
            raise ValueError("pulses_per_index must be at least 1")
        original = self.read_fpga_io_mux()
        print(f"Initial FPGA IO mux: {original}", flush=True)
        try:
            for index in range(8):
                updates = {name: index for name in FPGA_IO_NAMES}
                mux = self.write_fpga_io_mux(**updates)
                print(
                    f"Testing all FPGA IO muxes at index {index}; mux={mux}; "
                    f"pulsing {pulses_per_index} times at {period_ms} ms period",
                    flush=True,
                )
                self.pulse_synchro_trigger(count=pulses_per_index, period_ms=period_ms)
        finally:
            self.write_fpga_io_mux(**original)
            print(f"Restored FPGA IO mux: {original}", flush=True)

    @staticmethod
    def _mean_stdev(values: list[float]) -> tuple[float, float]:
        if not values:
            return math.nan, math.nan
        if len(values) == 1:
            return values[0], 0.0
        return statistics.mean(values), statistics.stdev(values)

    def hold_scan(
        self,
        delays_ns: list[int],
        *,
        mode: str,
        channels: list[int],
        out_csv: Path,
        trigger_channel: int,
        threshold_dac: int | None,
        t1: bool,
        use_mask: bool,
        use_ctest: bool,
        nb_acq: int,
        conversion_delay_ns: int,
        trigger_type: int,
        trigger_source: int,
        rstn_manual: bool,
        ext_trig: bool,
        peak_sensing: bool,
        adc_window_ns: int,
        adc_nb_trig: int,
        timeout_s: float,
        synchro_trigger: bool,
    ) -> None:
        if mode not in {"internal", "external"}:
            raise ValueError("hold scan mode must be internal or external")
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        if threshold_dac is not None:
            self.set_threshold_dac(threshold_dac, t1=t1)
        self.prepare_scurve_masks(t1=t1, use_mask=use_mask, use_ctest=use_ctest)
        if use_mask:
            self.set_mask_for_channel(trigger_channel, t1=t1, enabled=True)
        if use_ctest:
            self.set_ctest_for_channel(trigger_channel, enabled=True)
        saved_w2 = self.read_word(2) if not self.dry_run else "00000000"
        saved_i2c65_12 = self.read_register_bits(65, 12)
        header = ["hold_code" if mode == "internal" else "hold_delay_ns"]
        for ch in channels:
            header.extend([f"ch{ch}_hg_mean", f"ch{ch}_hg_stdev", f"ch{ch}_lg_mean", f"ch{ch}_lg_stdev", f"ch{ch}_count"])
        start_time = time.perf_counter()
        try:
            with out_csv.open("w", newline="") as fp:
                writer = csv.writer(fp)
                writer.writerow(header)
                for delay_ns in delays_ns:
                    if mode == "internal":
                        self.configure_adc_internal_hold(
                            trigger_channel=trigger_channel,
                            hold_code=delay_ns,
                            nb_acq=nb_acq,
                        )
                    else:
                        self.configure_adc_external_hold(
                            trigger_channel=trigger_channel,
                            hold_delay_ns=delay_ns,
                            conversion_delay_ns=conversion_delay_ns,
                            nb_acq=nb_acq,
                            trigger_type=trigger_type,
                            trigger_source=trigger_source,
                            rstn_manual=rstn_manual,
                            ext_trig=ext_trig,
                            peak_sensing=peak_sensing,
                            adc_window_ns=adc_window_ns,
                            adc_nb_trig=adc_nb_trig,
                        )
                    hg, lg = self.acquire_adc_batch(
                        nb_acq=nb_acq,
                        timeout_s=timeout_s,
                        synchro_trigger=synchro_trigger,
                    )
                    row: list[float | int] = [delay_ns]
                    summary = []
                    for ch in channels:
                        hg_mean, hg_stdev = self._mean_stdev(hg[ch])
                        lg_mean, lg_stdev = self._mean_stdev(lg[ch])
                        row.extend([hg_mean, hg_stdev, lg_mean, lg_stdev, len(hg[ch])])
                        summary.append((ch, hg_mean, lg_mean, len(hg[ch])))
                    writer.writerow(row)
                    fp.flush()
                    label = "code" if mode == "internal" else "delay"
                    unit = "" if mode == "internal" else " ns"
                    print(f"hold {label}={delay_ns}{unit} values={summary[:4]}{'...' if len(summary) > 4 else ''}", flush=True)
        finally:
            try:
                if use_mask or use_ctest:
                    self.prepare_scurve_masks(t1=t1, use_mask=use_mask, use_ctest=use_ctest)
                self.write_register(65, 12, saved_i2c65_12)
                self.write_word(2, saved_w2)
            except Exception as exc:
                print(f"warning: hold scan cleanup failed: {exc}", flush=True)
            total_time = time.perf_counter() - start_time
            print(f"holdscan measurement time: {total_time:.3f} seconds", flush=True)

    def autocalibrate_scurve(
        self,
        *,
        t1: bool,
        use_mask: bool,
        use_ctest: bool,
        channels: list[int],
        out_dir: Path,
        clock_index: int,
        edge_or_level: bool,
    ) -> None:
        calib_subadd = 4 if t1 else 5
        calib_defaults = {
            ch: parse_bits(row.data) & 0x3F
            for ch in channels
            if (row := self.find_row(ch, calib_subadd)) is not None
        }
        if not calib_defaults:
            raise RuntimeError("no calibration rows found for selected channels")

        ref_ch = channels[0]
        ref_default = calib_defaults[ref_ch]

        print(f"{'T1' if t1 else 'T2'} autocalibration: step1 - 2-step LSB estimate")
        self.write_word(3, "00111111")
        self.write_register(ref_ch, calib_subadd, bits(0, 8))
        step1_zero = out_dir / "autocal_step1_zero.csv"
        self.scurve(
            list(range(0, 1000, 50)),
            t1=t1,
            use_mask=use_mask,
            use_ctest=use_ctest,
            channels=[ref_ch],
            out_csv=step1_zero,
            clock_index=clock_index,
            edge_or_level=edge_or_level,
        )

        self.write_register(ref_ch, calib_subadd, bits(63, 8))
        step1_full = out_dir / "autocal_step1_full.csv"
        self.scurve(
            list(range(0, 1000, 50)),
            t1=t1,
            use_mask=use_mask,
            use_ctest=use_ctest,
            channels=[ref_ch],
            out_csv=step1_full,
            clock_index=clock_index,
            edge_or_level=edge_or_level,
        )

        self.write_register(ref_ch, calib_subadd, bits(ref_default, 8))

        ref_zero = self._estimate_crossings(step1_zero, [ref_ch]).get(ref_ch)
        ref_full = self._estimate_crossings(step1_full, [ref_ch]).get(ref_ch)
        if ref_zero is None or ref_full is None or ref_full == ref_zero:
            lsb_ratio = 1.0
        else:
            lsb_ratio = abs(ref_full - ref_zero) / 63.0
        lsb_ratio = max(lsb_ratio, 0.25)
        print(f"LSB ratio estimate: {lsb_ratio:.3f} DACu/calib from ch{ref_ch}")

        print(f"{'T1' if t1 else 'T2'} autocalibration: step2 - transition window")
        step2_stop = min(1023, max(300, int(max([p for p in [ref_zero, ref_full] if p is not None] or [150]) + 150)))
        step2 = out_dir / "autocal_step2.csv"
        self.scurve(
            list(range(0, step2_stop + 1, 10)),
            t1=t1,
            use_mask=use_mask,
            use_ctest=use_ctest,
            channels=channels,
            out_csv=step2,
            clock_index=clock_index,
            edge_or_level=edge_or_level,
        )
        positions = self._estimate_crossings(step2, channels)
        valid_positions = [p for p in positions.values() if p is not None]
        mean_pos = statistics.mean(valid_positions or [500])

        print(f"{'T1' if t1 else 'T2'} autocalibration: step3 - apply 6-bit threshold corrections")
        calib_rows = []
        for ch in channels:
            row = self.find_row(ch, calib_subadd)
            if row is None:
                continue
            current = calib_defaults.get(ch, parse_bits(row.data) & 0x3F)
            pos = positions.get(ch)
            correction = 0 if pos is None else round((pos - mean_pos) / lsb_ratio)
            value = min(63, max(0, current - correction))
            calib_rows.append(I2CRow(ch, calib_subadd, bits(value, 8)))
        if calib_rows:
            print(f"calib min={min(parse_bits(r.data) for r in calib_rows)} max={max(parse_bits(r.data) for r in calib_rows)}")
            self.write_fifo(calib_rows)

        print(f"{'T1' if t1 else 'T2'} autocalibration: step5 - Plot/result scan")
        final_start = max(0, int(mean_pos) - 50)
        final_stop = min(1023, int(mean_pos) + 120)
        self.scurve(
            list(range(final_start, final_stop + 1, 2)),
            t1=t1,
            use_mask=use_mask,
            use_ctest=use_ctest,
            channels=channels,
            out_csv=out_dir / "autocal_final.csv",
            clock_index=clock_index,
            edge_or_level=edge_or_level,
            stop_after_all_low=5,
        )

    def prepare_calibration_rows(self, *, t1: bool, value: int, channels: list[int]) -> None:
        subadd = 4 if t1 else 5
        rows = [I2CRow(ch, subadd, bits(value, 8)) for ch in channels]
        self.write_fifo(rows)

    @staticmethod
    def _estimate_crossings(csv_path: Path, channels: list[int]) -> dict[int, float | None]:
        with csv_path.open(newline="") as fp:
            rows = list(csv.DictReader(fp))
        out: dict[int, float | None] = {}
        for ch in channels:
            col = f"ch{ch}"
            pairs = [(float(row["DAC"]), float(row[col])) for row in rows if row.get(col) not in ("", None)]
            crossing = None
            for (x0, y0), (x1, y1) in zip(pairs, pairs[1:]):
                if (y0 - 50.0) == 0:
                    crossing = x0
                    break
                if (y0 - 50.0) * (y1 - 50.0) <= 0 and y0 != y1:
                    crossing = x0 + (50.0 - y0) * (x1 - x0) / (y1 - y0)
                    break
            out[ch] = crossing
        return out


def parse_channels(value: str) -> list[int]:
    if value.lower() in {"all", "*"}:
        return list(range(N_CHANNELS))
    channels: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = [int(x) for x in part.split("-", 1)]
            channels.update(range(lo, hi + 1))
        else:
            channels.add(int(part))
    result = sorted(channels)
    if not all(0 <= ch < N_CHANNELS for ch in result):
        raise ValueError("channels must be in range 0..63")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="RADIOROC standard setup and S-curve/autocalibration runner.")
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--execute", action="store_true", help="Actually write hardware settings. Without this, dry-run only.")
    parser.add_argument("--apply-defaults", action="store_true")
    parser.add_argument("--verify-defaults", action="store_true")
    parser.add_argument("--verify-limit", type=int, default=16, help="Rows to verify; use 0 for the full default table.")
    parser.add_argument("--skip-fpga-init", action="store_true")
    parser.add_argument("--scurve", action="store_true")
    parser.add_argument("--threshold-scan", action="store_true")
    parser.add_argument("--hold-scan", action="store_true")
    parser.add_argument("--pulse-synchro-test", action="store_true", help="Pulse the FPGA synchro-trigger output without running an acquisition.")
    parser.add_argument("--autocalibrate", action="store_true")
    parser.add_argument("--channels", default="0", help="Channel list, e.g. 0, 0-7, or all.")
    parser.add_argument("--dac-min", type=int, default=0)
    parser.add_argument("--dac-max", type=int, default=1023)
    parser.add_argument("--dac-step", type=int, default=50)
    parser.add_argument("--hold-mode", choices=["internal", "external"], default="internal")
    parser.add_argument("--hold-min-ns", "--hold-min-code", dest="hold_min_ns", type=int, default=0)
    parser.add_argument("--hold-max-ns", "--hold-max-code", dest="hold_max_ns", type=int, default=255)
    parser.add_argument("--hold-step-ns", "--hold-step-code", dest="hold_step_ns", type=int, default=5)
    parser.add_argument("--hold-trigger-channel", type=int, help="ADC trigger channel for hold scan. Defaults to first selected channel.")
    parser.add_argument("--hold-threshold-dac", type=int, help="Set T1/T2 threshold DAC before the hold scan.")
    parser.add_argument("--hold-acquisitions", type=int, default=10, help="ADC acquisitions per hold-delay point.")
    parser.add_argument("--hold-conversion-delay-ns", type=int, default=400, help="ADC conversion delay; must be divisible by 40 ns.")
    parser.add_argument("--hold-timeout-s", type=float, default=5.0, help="Timeout per ADC batch.")
    parser.add_argument("--hold-synchro-trigger", action="store_true", help="Pulse the FPGA synchro-trigger output for each hold-scan ADC batch.")
    parser.add_argument("--sync-pulses", type=int, default=1000, help="Number of pulses for --pulse-synchro-test.")
    parser.add_argument("--sync-period-ms", type=float, default=10.0, help="Pulse period for --pulse-synchro-test.")
    parser.add_argument("--sync-io", choices=FPGA_IO_NAMES, default="io1", help="FPGA IO connector to configure for sync pulse diagnostics.")
    parser.add_argument("--sync-io-mux-index", type=int, help="Set one FPGA IO mux index before sync pulse diagnostics.")
    parser.add_argument("--scan-sync-io-mux", action="store_true", help="Cycle mux indices 0..7 on --sync-io while pulsing the synchro trigger.")
    parser.add_argument("--scan-all-sync-io-muxes", action="store_true", help="Cycle mux indices 0..7 on every FPGA IO while pulsing the synchro trigger.")
    parser.add_argument("--adc-trigger-type", type=int, default=0, help="Vendor ADC trigger type code; default 0=simple trigger.")
    parser.add_argument("--adc-trigger-source", type=int, default=3, help="Vendor ADC T1 source code; default 3=individual channel.")
    parser.add_argument("--adc-window-ns", type=int, default=50, help="ADC trigger coincidence/window width; must be divisible by 5 ns.")
    parser.add_argument("--adc-nb-trig", type=int, default=1, help="ADC time-window trigger count.")
    parser.add_argument("--adc-rstn-manual", action="store_true", help="Set vendor ADC Reset_n manual bit.")
    parser.add_argument("--adc-ext-trig", action="store_true", help="Use external ASIC acquisition trigger in ADC setup.")
    parser.add_argument("--hold-peak-sensing", action="store_true", help="Use the vendor external-hold peak-sensing control word for synchronized hold scans.")
    parser.add_argument("--trigger-window-ms", type=float, default=100.0, help="Threshold-scan counting window per channel/DAC.")
    parser.add_argument("--threshold-averages", type=int, default=1, help="Number of repeated threshold-count windows to average per DAC/channel.")
    parser.add_argument(
        "--trigger-preamp-gain",
        "--pat-gain",
        type=int,
        help="Set selected channels' trigger preamplifier paT gain code before scanning: 1=max gain, 63=min gain.",
    )
    parser.add_argument("--t2", action="store_true", help="Use T2 instead of T1.")
    parser.add_argument("--no-mask", action="store_true")
    parser.add_argument("--use-ctest", action="store_true")
    parser.add_argument("--clock-index", type=int, default=3, help="S-curve clock index: 0=1 kHz, 1=10 kHz, 2=100 kHz, 3=1 MHz.")
    parser.add_argument("--trigger-level", action="store_true", help="Count trigger level instead of trigger rising edge.")
    args = parser.parse_args()

    channels = parse_channels(args.channels)
    dry_run = not args.execute
    args.out_dir.mkdir(parents=True, exist_ok=True)
    print("DRY RUN" if dry_run else "EXECUTE MODE")
    print(f"Guide flow: default config -> S-curves/autocalibration; channels={channels}; trigger={'T2' if args.t2 else 'T1'}")

    with RadiorocSerial(args.port, args.baud) as dev:
        ops = RadiorocOps(dev, dry_run=dry_run)
        ops.load_default_config(args.config)
        fw = ops.read_word(100)
        print(f"firmware/status word at 100: {fw} ({parse_bits(fw)})")

        if not args.skip_fpga_init:
            print("Initializing FPGA control words")
            ops.initialize_fpga()

        if args.apply_defaults:
            print(f"Applying default I2C configuration from {args.config}")
            ops.apply_default_config()

        if args.verify_defaults:
            limit = None if args.verify_limit == 0 else args.verify_limit
            if not ops.verify_default_config(limit=limit):
                raise SystemExit(2)

        if args.trigger_preamp_gain is not None:
            ops.set_trigger_preamp_gain(args.trigger_preamp_gain, channels=channels)

        if args.sync_io_mux_index is not None:
            mux = ops.write_fpga_io_mux(**{args.sync_io: args.sync_io_mux_index})
            print(f"Set {args.sync_io.upper()} mux index to {args.sync_io_mux_index}; mux={mux}")

        if args.scan_sync_io_mux:
            ops.scan_fpga_io_mux_for_synchro(
                io_name=args.sync_io,
                pulses_per_index=args.sync_pulses,
                period_ms=args.sync_period_ms,
            )

        if args.scan_all_sync_io_muxes:
            ops.scan_all_fpga_io_muxes_for_synchro(
                pulses_per_index=args.sync_pulses,
                period_ms=args.sync_period_ms,
            )

        if args.pulse_synchro_test:
            print(f"Pulsing FPGA synchro trigger {args.sync_pulses} times, period {args.sync_period_ms} ms")
            ops.pulse_synchro_trigger(count=args.sync_pulses, period_ms=args.sync_period_ms)

        if args.scurve:
            dacs = list(range(args.dac_min, args.dac_max + 1, args.dac_step))
            ops.scurve(
                dacs,
                t1=not args.t2,
                use_mask=not args.no_mask,
                use_ctest=args.use_ctest,
                channels=channels,
                out_csv=args.out_dir / "scurve.csv",
                clock_index=args.clock_index,
                edge_or_level=args.trigger_level,
            )

        if args.threshold_scan:
            dacs = list(range(args.dac_min, args.dac_max + 1, args.dac_step))
            ops.threshold_scan(
                dacs,
                t1=not args.t2,
                use_mask=not args.no_mask,
                use_ctest=args.use_ctest,
                channels=channels,
                out_csv=args.out_dir / "thresholdscan.csv",
                trigger_window_ms=args.trigger_window_ms,
                averages=args.threshold_averages,
            )

        if args.hold_scan:
            delays_ns = list(range(args.hold_min_ns, args.hold_max_ns + 1, args.hold_step_ns))
            ops.hold_scan(
                delays_ns,
                mode=args.hold_mode,
                t1=not args.t2,
                use_mask=not args.no_mask,
                use_ctest=args.use_ctest,
                channels=channels,
                out_csv=args.out_dir / "holdscan.csv",
                trigger_channel=args.hold_trigger_channel if args.hold_trigger_channel is not None else channels[0],
                threshold_dac=args.hold_threshold_dac,
                nb_acq=args.hold_acquisitions,
                conversion_delay_ns=args.hold_conversion_delay_ns,
                trigger_type=args.adc_trigger_type,
                trigger_source=args.adc_trigger_source,
                rstn_manual=args.adc_rstn_manual,
                ext_trig=args.adc_ext_trig,
                peak_sensing=args.hold_peak_sensing,
                adc_window_ns=args.adc_window_ns,
                adc_nb_trig=args.adc_nb_trig,
                timeout_s=args.hold_timeout_s,
                synchro_trigger=args.hold_synchro_trigger,
            )

        if args.autocalibrate:
            ops.autocalibrate_scurve(
                t1=not args.t2,
                use_mask=not args.no_mask,
                use_ctest=args.use_ctest,
                channels=channels,
                out_dir=args.out_dir,
                clock_index=args.clock_index,
                edge_or_level=args.trigger_level,
            )


if __name__ == "__main__":
    main()
