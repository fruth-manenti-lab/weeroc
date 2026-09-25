from __future__ import annotations

import csv
from pathlib import Path
import tempfile
import unittest

from radioroc_analysis import (
    estimate_scurve_crossings,
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
    format_channels,
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

    def test_format_channels(self) -> None:
        self.assertEqual(format_channels([]), "none")
        self.assertEqual(format_channels([0, 1, 2, 3, 5]), "0-3,5")
        self.assertEqual(format_channels([5, 1, 9]), "1,5,9")
        self.assertEqual(format_channels([4, 4, 5]), "4-5")

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

    def test_main_tab_per_channel_front_end_bit_positions(self) -> None:
        # Bit positions recovered from radioroc2UI.pyc's retranslateUi
        # tooltips (add: [0:63] - subadd: N - bit: [a:b]); see
        # IMPLEMENTATION_STATUS.md RADIOROC 30.
        device = RadiorocDevice(RadiorocMemoryTransport(), dry_run=True)  # type: ignore[arg-type]
        device.load_default_config()

        # Packaged default (channel 0): compensation = 0, gain = 8 (subadd 1).
        self.assertEqual(device.find_i2c_row(0, 1).data, "00001000")

        device.set_trigger_preamp_gain_for_channel(4, 30)
        self.assertEqual(device.find_i2c_row(4, 1).data[2:8], bits(30, 6))
        with self.assertRaises(ValueError):
            device.set_trigger_preamp_gain_for_channel(4, 64)

        before = device.find_i2c_row(4, 1).data
        device.set_trigger_preamp_compensation_for_channel(4, 2)
        after = device.find_i2c_row(4, 1).data
        self.assertEqual(after[0:2], bits(2, 2))
        self.assertEqual(after[2:8], before[2:8])
        with self.assertRaises(ValueError):
            device.set_trigger_preamp_compensation_for_channel(4, 4)

        device.set_high_gain_for_channel(4, 12)
        self.assertEqual(device.find_i2c_row(4, 2).data[4:8], bits(12, 4))
        before = device.find_i2c_row(4, 2).data
        device.set_low_gain_for_channel(4, 9)
        after = device.find_i2c_row(4, 2).data
        self.assertEqual(after[0:4], bits(9, 4))
        self.assertEqual(after[4:8], before[4:8])

        device.set_high_gain_shaping_for_channel(4, 7)
        self.assertEqual(device.find_i2c_row(4, 3).data[4:8], bits(7, 4))
        before = device.find_i2c_row(4, 3).data
        device.set_low_gain_shaping_for_channel(4, 3)
        after = device.find_i2c_row(4, 3).data
        self.assertEqual(after[0:4], bits(3, 4))
        self.assertEqual(after[4:8], before[4:8])

        # Shaping LSB selects and Ctest/injection-cap bits share subadd 7;
        # setting one leaves the others alone.
        device.set_ctest_for_channel(4, True)
        before = device.find_i2c_row(4, 7).data
        device.set_high_gain_shaping_slow_for_channel(4, True)
        after = device.find_i2c_row(4, 7).data
        self.assertEqual(after[1], "1")
        self.assertEqual(after[3], before[3])  # Ctest bit untouched
        device.set_low_gain_shaping_slow_for_channel(4, True)
        after = device.find_i2c_row(4, 7).data
        self.assertEqual(after[0], "1")
        self.assertEqual(after[1], "1")

    def test_main_tab_common_threshold_and_trigger_selection(self) -> None:
        # Bit positions recovered the same way; see IMPLEMENTATION_STATUS.md
        # RADIOROC 30. The default subadd-12 value independently confirms the
        # selTrig[3:0] position: it decodes to 0b0100, the exact "global_t1"
        # code enumerated from the "Trigger selection" combo box tooltip.
        device = RadiorocDevice(RadiorocMemoryTransport(), dry_run=True)  # type: ignore[arg-type]
        device.load_default_config()

        self.assertEqual(device.find_i2c_row(65, 12).data[4:8], bits(0b0100, 4))

        device.set_t1_threshold_dac(0x2AB)
        self.assertEqual(device.find_i2c_row(65, 1).data, bits(0x2AB & 0xFF, 8))
        self.assertEqual(device.find_i2c_row(65, 2).data[0:2], bits((0x2AB >> 8) & 0x3, 2))
        with self.assertRaises(ValueError):
            device.set_t1_threshold_dac(1024)

        device.set_t2_threshold_dac(0x155)
        self.assertEqual(device.find_i2c_row(65, 2).data[2:8], bits(0x155 & 0x3F, 6))
        self.assertEqual(device.find_i2c_row(65, 3).data[0:4], bits((0x155 >> 6) & 0xF, 4))
        # Setting T2 preserved T1's bits already written into subadd 2.
        self.assertEqual(device.find_i2c_row(65, 2).data[0:2], bits((0x2AB >> 8) & 0x3, 2))

        device.set_tq_threshold_dac(0x3D0)
        self.assertEqual(device.find_i2c_row(65, 3).data[4:8], bits(0x3D0 & 0xF, 4))
        self.assertEqual(device.find_i2c_row(65, 4).data[2:8], bits((0x3D0 >> 4) & 0x3F, 6))
        # Setting TQ preserved T2's bits already written into subadd 3.
        self.assertEqual(device.find_i2c_row(65, 3).data[0:4], bits((0x155 >> 6) & 0xF, 4))

        device.set_trigger_selection("local_tq")
        after = device.find_i2c_row(65, 12).data
        self.assertEqual(after[4:8], bits(0b0011, 4))
        self.assertEqual(after[0:4], "1110")  # hysteresis/EN_delay/selHoldExt untouched
        with self.assertRaises(ValueError):
            device.set_trigger_selection("not_a_mode")

        device.set_delay_code(200)
        self.assertEqual(device.find_i2c_row(65, 8).data, bits(200, 8))
        with self.assertRaises(ValueError):
            device.set_delay_code(256)

        before = device.find_i2c_row(65, 9).data
        device.set_delay_slope(9)
        after = device.find_i2c_row(65, 9).data
        self.assertEqual(after[0:4], bits(9, 4))
        self.assertEqual(after[4:8], before[4:8])  # internal bias bits untouched

    def test_adc_two_channel_coincidence_bit_positions(self) -> None:
        # FPGA word layout recovered from radioroc2UI.pyc/adc.pyc disassembly
        # (start_adc): word 22 = T1 individual channel, word 23 = T2
        # individual channel (shared with the unrelated peak_sensing path),
        # word 25[0:3] = T1 mode, word 25[6:8] = trigger_type, word
        # 30[4:7] = T2 mode. See IMPLEMENTATION_STATUS.md RADIOROC 39.
        # Word 4 bit 7 (I2C FIFO ready) must read "1" or the I2C write this
        # method performs to ASIC 65/12 times out waiting for the FPGA.
        device = RadiorocDevice(RadiorocMemoryTransport({4: bits(1)}), dry_run=False)  # type: ignore[arg-type]
        device.load_default_config()

        device.configure_adc_external_hold(
            trigger_channel=5, hold_delay_ns=100, conversion_delay_ns=80, nb_acq=10,
            trigger_type=1, trigger_source=3, rstn_manual=False, ext_trig=False,
            peak_sensing=False, adc_window_ns=25, adc_nb_trig=1,
            trigger_source_2=3, trigger_channel_2=2,
        )
        self.assertEqual(device.read_word(22)[2:8], bits(5, 6))
        self.assertEqual(device.read_word(23)[2:8], bits(2, 6))
        self.assertEqual(device.read_word(25)[0:3], bits(3, 3))
        self.assertEqual(device.read_word(25)[6:8], bits(1, 2))
        self.assertEqual(device.read_word(30)[4:7], bits(3, 3))

        # Omitting trigger_source_2/trigger_channel_2 reproduces the prior,
        # pre-RADIOROC-39 behavior exactly (T2 hardcoded to NORT1/OR-of-all).
        device.configure_adc_external_hold(
            trigger_channel=5, hold_delay_ns=100, conversion_delay_ns=80, nb_acq=10,
            trigger_type=1, trigger_source=3, rstn_manual=False, ext_trig=False,
            peak_sensing=False, adc_window_ns=25, adc_nb_trig=1,
        )
        self.assertEqual(device.read_word(23), "00000000")
        self.assertEqual(device.read_word(30)[4:7], bits(0, 3))

        with self.assertRaises(ValueError):
            device.configure_adc_external_hold(
                trigger_channel=5, hold_delay_ns=100, conversion_delay_ns=80, nb_acq=10,
                trigger_type=1, trigger_source=3, rstn_manual=False, ext_trig=False,
                peak_sensing=True, adc_window_ns=25, adc_nb_trig=1,
                trigger_source_2=3, trigger_channel_2=2,
            )

    def test_unmask_channel_for_individual_coincidence_sets_all_three_levels(self) -> None:
        # Which discriminator level (T1, T2, or TQ) "Individual trigger"
        # mode taps is not recovered from disassembly (RADIOROC 39/40), so
        # this unmasks all three for the named channel rather than guessing.
        device = RadiorocDevice(RadiorocMemoryTransport(), dry_run=True)  # type: ignore[arg-type]
        device.load_default_config()
        # Force channel 5's mask bits to a known "everything masked out"
        # state directly (write_register, not the multi-row write_fifo path
        # prepare_trigger_masks uses -- select_i2c_rows returns copies, so a
        # write_fifo call never updates find_i2c_row's own cache).
        device.write_register(5, 6, "00000000")
        row = device.find_i2c_row(5, 6).data
        self.assertEqual(row[3], "0")  # T1 masked out
        self.assertEqual(row[4], "0")  # T2 masked out
        self.assertEqual(row[5], "0")  # TQ masked out

        device.unmask_channel_for_individual_coincidence(5)
        row = device.find_i2c_row(5, 6).data
        self.assertEqual(row[3], "1")  # T1 mask
        self.assertEqual(row[4], "1")  # T2 mask
        self.assertEqual(row[5], "1")  # TQ mask

        device.unmask_channel_for_individual_coincidence(5, enabled=False)
        row = device.find_i2c_row(5, 6).data
        self.assertEqual(row[3], "0")
        self.assertEqual(row[4], "0")
        self.assertEqual(row[5], "0")


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

    def test_estimate_scurve_crossings(self) -> None:
        # Same algorithm as scripts/radioroc_standard_scurves.py's legacy
        # autocalibrate_scurve/_estimate_crossings (see IMPLEMENTATION_STATUS.md's
        # F08/autocalibration entry), decoupled from CSV file I/O.
        rows = [
            {"DAC": 0, "ch4": 100.0, "ch5": 100.0},
            {"DAC": 10, "ch4": 100.0, "ch5": 80.0},
            {"DAC": 20, "ch4": 0.0, "ch5": 20.0},
            {"DAC": 30, "ch4": 0.0, "ch5": 0.0},
        ]
        crossings = estimate_scurve_crossings(rows, [4, 5])
        # ch4 falls 100 -> 0 between DAC 10 and 20: crosses 50 at DAC 15.
        self.assertAlmostEqual(crossings[4], 15.0)
        # ch5 falls 80 -> 20 between DAC 10 and 20: crosses 50 at DAC 15 too.
        self.assertAlmostEqual(crossings[5], 15.0)

        # Never crosses target_percent -> None, not an exception.
        flat_rows = [{"DAC": 0, "ch4": 100.0}, {"DAC": 10, "ch4": 100.0}]
        self.assertIsNone(estimate_scurve_crossings(flat_rows, [4])[4])

        # Channel absent from every row -> None.
        self.assertIsNone(estimate_scurve_crossings(rows, [6])[6])

        # An exact match at a row short-circuits the interpolation.
        exact_rows = [{"DAC": 0, "ch4": 100.0}, {"DAC": 10, "ch4": 50.0}, {"DAC": 20, "ch4": 0.0}]
        self.assertEqual(estimate_scurve_crossings(exact_rows, [4])[4], 10.0)

        # A non-default target_percent is honored.
        self.assertAlmostEqual(estimate_scurve_crossings(rows, [4], target_percent=25.0)[4], 17.5)

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
