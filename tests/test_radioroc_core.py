from __future__ import annotations

import csv
from pathlib import Path
import tempfile
import unittest

from radioroc_analysis import (
    filter_hold_data,
    find_latest_scan,
    has_invalid_internal_zero_point,
    log_profile_residual_derivative,
    parse_hold_channels,
    parse_threshold_channels,
    poisson_rate_errors,
    read_hold_csv,
    read_threshold_attempt_std,
    read_threshold_csv,
    summarize_hold,
    summarize_threshold,
    threshold_dac_to_mv,
    threshold_derivative,
)
from radioroc_client import (
    HoldScanConfig,
    RadiorocDevice,
    RadiorocMemoryTransport,
    ScurveConfig,
    ThresholdScanConfig,
    bits,
    encode_read_request,
    encode_write_request,
    parse_bits,
    parse_channels,
    scan_values,
)


class RadiorocCoreTests(unittest.TestCase):
    def test_bits_and_parse_bits(self) -> None:
        self.assertEqual(bits(5), "00000101")
        self.assertEqual(bits(5, 3), "101")
        self.assertEqual(parse_bits("00000101"), 5)

    def test_serial_frame_encoding(self) -> None:
        self.assertEqual(encode_read_request(100), bytes.fromhex("aa 00 e4 00 55"))
        self.assertEqual(encode_write_request(1, b"\x40"), bytes.fromhex("aa 00 01 40 55"))
        with self.assertRaises(ValueError):
            encode_read_request(128)
        with self.assertRaises(ValueError):
            encode_write_request(0, b"")

    def test_channel_parsing(self) -> None:
        self.assertEqual(parse_channels("4"), [4])
        self.assertEqual(parse_channels("0-2,4"), [0, 1, 2, 4])
        self.assertEqual(parse_channels("all", n_channels=3), [0, 1, 2])
        with self.assertRaises(ValueError):
            parse_channels("3-1")

    def test_scan_config_validation(self) -> None:
        ThresholdScanConfig(channels=[4], dac_min=0, dac_max=10, dac_step=5).validate()
        ScurveConfig(channels=[4], clock_index=3).validate()
        HoldScanConfig(mode="external", channels=[4], trigger_channel=4, hold_min=0, hold_max=10, hold_step=5).validate()
        with self.assertRaises(ValueError):
            ThresholdScanConfig(channels=[], dac_step=5).validate()
        with self.assertRaises(ValueError):
            HoldScanConfig(mode="external", channels=[4], trigger_channel=4, hold_min=0, hold_max=11, hold_step=5).validate()

    def test_scan_values(self) -> None:
        self.assertEqual(scan_values(0, 10, 5), [0, 5, 10])
        with self.assertRaises(ValueError):
            scan_values(0, 10, 0)

    def test_memory_transport(self) -> None:
        transport = RadiorocMemoryTransport({100: "00000101"})
        device = RadiorocDevice(transport, dry_run=False)  # type: ignore[arg-type]
        self.assertEqual(device.read_word(100), "00000101")
        device.write_word(3, "11110000")
        self.assertEqual(transport.words[3], "11110000")

    def test_tq_mask_and_input_dac_bit_positions(self) -> None:
        # Bit positions recovered from the vendor GUI's compiled widget
        # properties (radioroc2UI.pyc / i2c.pyc's set_value convention:
        # position = LSB index), cross-checked against this codebase's
        # already hardware-validated T1 (index 3) / T2 (index 4) bits on the
        # same channel-6 register. Not yet independently hardware-validated
        # for these specific bits.
        device = RadiorocDevice(RadiorocMemoryTransport(), dry_run=True)  # type: ignore[arg-type]
        device.load_default_config()

        device.set_tq_mask_for_channel(4, enabled=True)
        self.assertEqual(device.find_i2c_row(4, 6).data[5], "1")
        device.set_tq_mask_for_channel(4, enabled=False)
        self.assertEqual(device.find_i2c_row(4, 6).data[5], "0")

        device.set_input_dac_enable_for_channel(4, enabled=True)
        self.assertEqual(device.find_i2c_row(4, 6).data[1], "1")
        device.set_input_dac_enable_for_channel(4, enabled=False)
        self.assertEqual(device.find_i2c_row(4, 6).data[1], "0")

        device.set_input_dac_value(4, 200)
        self.assertEqual(device.find_i2c_row(4, 0).data, bits(200, 8))
        with self.assertRaises(ValueError):
            device.set_input_dac_value(4, 256)
        with self.assertRaises(ValueError):
            device.set_input_dac_value(64, 0)

        device.set_input_dac_impedance(True)
        self.assertTrue(all(device.find_i2c_row(ch, 6).data[0] == "1" for ch in range(64)))
        device.set_input_dac_impedance(False)
        self.assertTrue(all(device.find_i2c_row(ch, 6).data[0] == "0" for ch in range(64)))

        # Untouched bits on the shared channel-6 register are left alone.
        before = device.find_i2c_row(10, 6).data
        device.set_tq_mask_for_channel(10, enabled=True)
        after = device.find_i2c_row(10, 6).data
        self.assertEqual(after[5], "1")
        self.assertEqual(after[:5] + after[6:], before[:5] + before[6:])

    def test_calibration_dac_bit_positions(self) -> None:
        # subadd=4/5, low 6 bits (position=0, nbbits=6), recovered the same
        # way as test_tq_mask_and_input_dac_bit_positions above; the packaged
        # default config's channel-0 rows for both subadd already carry
        # "00100000" (decimal 32), matching the vendor GUI's default
        # Calibration DAC T1/T2 display value of 32 -- an independent
        # cross-check that subadd 4/5 are the right registers. Not yet
        # independently hardware-validated.
        device = RadiorocDevice(RadiorocMemoryTransport(), dry_run=True)  # type: ignore[arg-type]
        device.load_default_config()

        self.assertEqual(parse_bits(device.find_i2c_row(0, 4).data[2:]), 32)
        self.assertEqual(parse_bits(device.find_i2c_row(0, 5).data[2:]), 32)

        device.set_calibration_dac_for_channel(4, t1=True, value=50)
        self.assertEqual(device.find_i2c_row(4, 4).data[2:], bits(50, 6))
        device.set_calibration_dac_for_channel(4, t1=False, value=10)
        self.assertEqual(device.find_i2c_row(4, 5).data[2:], bits(10, 6))
        with self.assertRaises(ValueError):
            device.set_calibration_dac_for_channel(4, t1=True, value=64)
        with self.assertRaises(ValueError):
            device.set_calibration_dac_for_channel(64, t1=True, value=0)

        # The top 2 (unused/NC) bits are left untouched, not forced to zero.
        before = device.find_i2c_row(5, 4).data
        device.set_calibration_dac_for_channel(5, t1=True, value=63)
        after = device.find_i2c_row(5, 4).data
        self.assertEqual(after[2:], bits(63, 6))
        self.assertEqual(after[:2], before[:2])


class RadiorocAnalysisTests(unittest.TestCase):
    def test_threshold_csv_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "thresholdscan.csv"
            with path.open("w", newline="") as fp:
                writer = csv.writer(fp)
                writer.writerow(["DAC", "ch4"])
                writer.writerow([0, 0])
                writer.writerow([5, 1000])
                writer.writerow([10, 500])
            data = read_threshold_csv(path)
            self.assertEqual(data.dacs, [0.0, 5.0, 10.0])
            self.assertEqual(parse_threshold_channels("4", list(data.series)), ["ch4"])
            summary = summarize_threshold(data)[0]
            self.assertEqual(summary.peak_dac, 5.0)
            self.assertEqual(summary.peak_hz, 1000.0)
            self.assertEqual(threshold_dac_to_mv(data.dacs), [270.0, 271.25, 272.5])
            derivative_dacs, derivative_rates = threshold_derivative(data.dacs, data.series["ch4"])
            self.assertEqual(derivative_dacs, [2.5, 7.5])
            self.assertEqual(derivative_rates, [-200.0, 100.0])
            self.assertEqual(poisson_rate_errors([1000.0], window_ms=100.0, averages=4), [50.0])
            residual_x, residual_derivative = log_profile_residual_derivative(
                [0.0, 1.0, 2.0, 3.0],
                [10.0, 100.0, 10.0, 100.0],
                profile_window=3,
            )
            self.assertEqual(residual_x, [0.5, 1.5, 2.5])
            self.assertEqual(len(residual_derivative), 3)
            attempts = Path(tmp) / "thresholdscan_attempts.csv"
            with attempts.open("w", newline="") as fp:
                writer = csv.writer(fp)
                writer.writerow(["DAC", "channel", "attempt", "rate_hz", "trigger_count"])
                writer.writerow([0, 4, 1, 90, 9])
                writer.writerow([0, 4, 2, 110, 11])
                writer.writerow([5, 4, 1, 1000, 100])
                writer.writerow([5, 4, 2, 1000, 100])
                writer.writerow([10, 4, 1, 400, 40])
                writer.writerow([10, 4, 2, 600, 60])
            stdevs = read_threshold_attempt_std(attempts, data)
            self.assertAlmostEqual(stdevs["ch4"][0], 14.1421356237)
            self.assertEqual(stdevs["ch4"][1], 0.0)

    def test_hold_csv_filter_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "holdscan.csv"
            with path.open("w", newline="") as fp:
                writer = csv.writer(fp)
                writer.writerow(["hold_code", "ch4_hg_mean", "ch4_lg_mean", "ch4_hg_stdev", "ch4_lg_stdev", "ch4_count"])
                writer.writerow([0, 1000, 100, 0, 0, 1])
                writer.writerow([5, 10, 1, 0, 0, 1])
                writer.writerow([10, 20, 2, 0, 0, 1])
            data = read_hold_csv(path)
            self.assertTrue(has_invalid_internal_zero_point(data))
            filtered = filter_hold_data(data, exclude_zero=True)
            self.assertEqual(filtered.x_values, [5.0, 10.0])
            self.assertEqual(parse_hold_channels(None, filtered.series), [4])
            summary = summarize_hold(filtered, channels=[4], gains=("hg",))[0]
            self.assertEqual(summary.peak_x, 10.0)
            self.assertEqual(summary.peak_value, 20.0)

    def test_latest_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "a" / "thresholdscan.csv"
            second = root / "b" / "thresholdscan.csv"
            first.parent.mkdir()
            second.parent.mkdir()
            first.write_text("DAC,ch4\n0,0\n", encoding="utf-8")
            second.write_text("DAC,ch4\n0,1\n", encoding="utf-8")
            self.assertEqual(find_latest_scan(root, "thresholdscan.csv"), second)


if __name__ == "__main__":
    unittest.main()
