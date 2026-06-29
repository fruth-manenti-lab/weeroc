from __future__ import annotations

import csv
from pathlib import Path
import tempfile
import unittest

from radioroc_analysis import (
    filter_hold_data,
    find_latest_scan,
    has_invalid_internal_zero_point,
    parse_hold_channels,
    parse_threshold_channels,
    read_hold_csv,
    read_threshold_csv,
    summarize_hold,
    summarize_threshold,
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
