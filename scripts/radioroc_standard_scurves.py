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
        self.ser.write(frame)
        self.ser.flush()
        if read_len <= 0:
            return b""
        return self.ser.read(read_len)

    def read_word(self, address: int) -> str:
        response = self._xfer(encode_read_request(address, 1), 5)
        if len(response) != 5 or response[0] != 0xAA or response[-1] != 0x55:
            raise RuntimeError(f"bad read_word({address}) response: {response.hex(' ')}")
        return bits(response[3], 8)

    def read_words(self, address: int, length: int) -> bytes:
        response = self._xfer(encode_read_request(address, length), length + 4)
        if len(response) != length + 4 or response[0] != 0xAA or response[-1] != 0x55:
            raise RuntimeError(f"bad read_words({address}, {length}) response: {response.hex(' ')}")
        return response[3:-1]

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
    ) -> None:
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        self.configure_scurve_firmware(clock_index=clock_index, edge_or_level=edge_or_level)
        self.prepare_scurve_masks(t1=t1, use_mask=use_mask, use_ctest=use_ctest)
        saved_w1 = self.read_word(1) if not self.dry_run else "00000000"
        header = ["DAC"] + [f"ch{ch}" for ch in channels]
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
                        print(f"pulse data: {pulse_data}")
                        values.append(math.nan)
                    if use_mask:
                        self.set_mask_for_channel(ch, t1=t1, enabled=False)
                    if use_ctest:
                        self.set_ctest_for_channel(ch, enabled=False)
                    self.write_word(1, saved_w1[:6] + "10")
                writer.writerow([dac] + values)
                print(f"scurve dac={dac} values={values[:8]}{'...' if len(values) > 8 else ''}")
        self.write_word(1, saved_w1[:6] + "00")

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
        print(f"{'T1' if t1 else 'T2'} autocalibration: step1 - 2-step LSB estimate")
        self.write_word(3, "00111111")
        self.prepare_calibration_rows(t1=t1, value=0, channels=channels)
        step1 = out_dir / "autocal_step1.csv"
        self.scurve(
            list(range(0, 1000, 50)),
            t1=t1,
            use_mask=use_mask,
            use_ctest=use_ctest,
            channels=channels,
            out_csv=step1,
            clock_index=clock_index,
            edge_or_level=edge_or_level,
        )

        positions = self._estimate_crossings(step1, channels)
        center = int(statistics.mean([p for p in positions.values() if p is not None] or [500]))
        start = max(0, center - 100)
        stop = min(1023, center + 100)

        print(f"{'T1' if t1 else 'T2'} autocalibration: step2 - transition window {start}..{stop}")
        step2 = out_dir / "autocal_step2.csv"
        self.scurve(
            list(range(start, stop + 1, 10)),
            t1=t1,
            use_mask=use_mask,
            use_ctest=use_ctest,
            channels=channels,
            out_csv=step2,
            clock_index=clock_index,
            edge_or_level=edge_or_level,
        )
        positions = self._estimate_crossings(step2, channels)
        mean_pos = statistics.mean([p for p in positions.values() if p is not None] or [center])

        print(f"{'T1' if t1 else 'T2'} autocalibration: step3 - apply 6-bit threshold corrections")
        calib_subadd = 4 if t1 else 5
        calib_rows = []
        for ch in channels:
            row = self.find_row(ch, calib_subadd)
            if row is None:
                continue
            current = parse_bits(row.data) & 0x3F
            pos = positions.get(ch)
            correction = 0 if pos is None else round(pos - mean_pos)
            value = min(63, max(0, current - correction))
            calib_rows.append(I2CRow(ch, calib_subadd, bits(value, 8)))
        if calib_rows:
            print(f"calib min={min(parse_bits(r.data) for r in calib_rows)} max={max(parse_bits(r.data) for r in calib_rows)}")
            self.write_fifo(calib_rows)

        print(f"{'T1' if t1 else 'T2'} autocalibration: step5 - Plot/result scan")
        final_start = max(0, int(mean_pos) - 50)
        final_stop = min(1023, int(mean_pos) + 50)
        self.scurve(
            list(range(final_start, final_stop + 1, 2)),
            t1=t1,
            use_mask=use_mask,
            use_ctest=use_ctest,
            channels=channels,
            out_csv=out_dir / "autocal_final.csv",
            clock_index=clock_index,
            edge_or_level=edge_or_level,
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
    parser.add_argument("--autocalibrate", action="store_true")
    parser.add_argument("--channels", default="0", help="Channel list, e.g. 0, 0-7, or all.")
    parser.add_argument("--dac-min", type=int, default=0)
    parser.add_argument("--dac-max", type=int, default=1023)
    parser.add_argument("--dac-step", type=int, default=50)
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
