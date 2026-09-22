"""Offline tests for the shared raw-register read/write core (F06)."""

import csv
from pathlib import Path
import tempfile
import unittest

from radioroc_client import I2CRow, RadiorocDevice, bits
from radioroc.application.raw_registers import RawRegisterWrite, read_all_registers, write_raw_register
from tests.test_threshold_jobs import ThresholdTransport


class RawRegisterWriteTests(unittest.TestCase):
    def test_validate_rejects_out_of_range_and_malformed_data(self):
        with self.assertRaises(ValueError):
            RawRegisterWrite(256, 0, "00000000").validate()
        with self.assertRaises(ValueError):
            RawRegisterWrite(0, 256, "00000000").validate()
        with self.assertRaises(ValueError):
            RawRegisterWrite(0, 0, "0000000").validate()  # 7 bits
        with self.assertRaises(ValueError):
            RawRegisterWrite(0, 0, "0000000x").validate()  # not binary
        RawRegisterWrite(0, 0, "00000000").validate()  # does not raise


class RawRegistersHardwareTests(unittest.TestCase):
    def setUp(self):
        # ThresholdTransport faithfully round-trips arbitrary ASIC I2C
        # register reads/writes (unlike the plain RadiorocMemoryTransport,
        # which only simulates FPGA words), matching test_channel_config.py's
        # own convention for this same reason.
        self.transport = ThresholdTransport()
        self.device = RadiorocDevice(self.transport, dry_run=False)
        # A small, deliberately narrow row set: ThresholdTransport's synthetic
        # ASIC map only covers add 0..66 / subadd 0..63, and the real
        # packaged default config CSV also carries reserved
        # (add, subadd>=64) probe-block rows that fake transport was never
        # built to answer for a bulk multi-row FIFO read -- stay within rows
        # it actually supports rather than extend a fixture shared by other
        # test files.
        self.device.i2c_rows = [
            I2CRow(4, 0, bits(0, 8)), I2CRow(4, 6, bits(0, 8)),
            I2CRow(5, 0, bits(0, 8)), I2CRow(5, 6, bits(0, 8)),
        ]

    def test_read_all_reflects_real_hardware_values(self):
        rows = read_all_registers(self.device)
        self.assertEqual(len(rows), 4)
        # Independently write one register underneath read_all_registers,
        # then confirm a second read reflects that -- not a stale value.
        self.device.write_register(4, 6, bits(0b10101010, 8))
        rows = read_all_registers(self.device)
        row = next(r for r in rows if r.add == 4 and r.subadd == 6)
        self.assertEqual(row.data, bits(0b10101010, 8))

    def test_write_raw_register_writes_and_verifies(self):
        result = write_raw_register(self.device, RawRegisterWrite(4, 0, bits(200, 8)))
        self.assertEqual(result.written, bits(200, 8))
        self.assertEqual(result.observed, bits(200, 8))
        self.assertFalse(result.mismatch)
        self.assertEqual(self.device.read_register_bits(4, 0), bits(200, 8))

    def test_write_raw_register_without_verify_leaves_observed_none(self):
        result = write_raw_register(self.device, RawRegisterWrite(4, 0, bits(1, 8), verify=False))
        self.assertIsNone(result.observed)
        self.assertFalse(result.mismatch)

    def test_write_raw_register_catches_a_readback_mismatch(self):
        original_read_register_bits = self.device.read_register_bits

        def flaky_read_register_bits(add, subadd):
            if (add, subadd) == (4, 0):
                return bits(0, 8)
            return original_read_register_bits(add, subadd)

        self.device.read_register_bits = flaky_read_register_bits
        result = write_raw_register(self.device, RawRegisterWrite(4, 0, bits(200, 8)))
        self.assertTrue(result.mismatch)
        self.assertEqual(result.observed, bits(0, 8))

    def test_read_all_loads_a_custom_config_path_when_no_rows_are_loaded(self):
        self.device.i2c_rows = []
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "small.csv"
            with path.open("w", newline="") as fp:
                writer = csv.writer(fp)
                writer.writerow(["add", "subadd", "data"])
                writer.writerow([4, 0, bits(0, 8)])
                writer.writerow([4, 6, bits(0, 8)])
            rows = read_all_registers(self.device, config_path=path)
        self.assertEqual(len(rows), 2)

    def test_write_raw_register_loads_default_config_when_device_has_no_rows(self):
        self.device.i2c_rows = []
        write_raw_register(self.device, RawRegisterWrite(4, 0, bits(7, 8)))
        self.assertTrue(self.device.i2c_rows)


if __name__ == "__main__":
    unittest.main()
