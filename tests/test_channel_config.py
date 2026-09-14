"""Offline tests for the shared input DAC / TQ mask channel-config core."""

import unittest

from radioroc_client import I2CRow, RadiorocDevice, bits
from radioroc.application.channel_config import ChannelConfigOperation, apply_channel_config
from tests.test_threshold_jobs import ThresholdTransport


class ChannelConfigOperationTests(unittest.TestCase):
    def test_validate_rejects_missing_value_and_bad_channel(self):
        with self.assertRaises(ValueError):
            ChannelConfigOperation(input_dac_value_channels=(4,)).validate()
        with self.assertRaises(ValueError):
            ChannelConfigOperation(input_dac_value_channels=(4,), input_dac_value=256).validate()
        with self.assertRaises(ValueError):
            ChannelConfigOperation(tq_mask_channels=(64,)).validate()
        with self.assertRaises(ValueError):
            ChannelConfigOperation().validate()  # no operation requested

    def test_load_rows_reuses_existing_when_config_path_is_none(self):
        existing = [I2CRow(4, 6, "11111111")]
        rows = ChannelConfigOperation().load_rows(existing)
        self.assertEqual(rows[0].data, "11111111")
        self.assertIsNot(rows, existing)  # deep-copied, not aliased


class ApplyChannelConfigTests(unittest.TestCase):
    def setUp(self):
        # ThresholdTransport faithfully round-trips arbitrary ASIC I2C
        # register reads/writes (unlike the plain RadiorocMemoryTransport,
        # which only simulates FPGA words), so verify/restore here exercise
        # a real read-after-write, not just in-memory row state.
        self.transport = ThresholdTransport()
        self.device = RadiorocDevice(self.transport, dry_run=False)

    def test_loads_defaults_when_device_has_no_rows(self):
        self.assertEqual(self.device.i2c_rows, [])
        apply_channel_config(self.device, ChannelConfigOperation(tq_mask_channels=(4,)))
        self.assertTrue(self.device.i2c_rows)
        self.assertEqual(self.device.find_i2c_row(4, 6).data[5], "1")

    def test_applies_verifies_and_restores(self):
        self.device.load_default_config()
        # The pre-run *hardware* state (what restore must reproduce), not
        # the CSV default -- ThresholdTransport's fake ASIC store starts
        # from its own synthetic seed, independent of the loaded CSV rows.
        before_channel6 = self.device.read_register_bits(4, 6)
        before_channel0 = self.device.read_register_bits(4, 0)

        result = apply_channel_config(self.device, ChannelConfigOperation(
            tq_mask_channels=(4,), tq_mask_value=True,
            input_dac_value_channels=(4,), input_dac_value=200,
            input_dac_impedance=True,
            verify=True, restore=True,
        ))

        self.assertEqual(result.touched_rows, 65)  # 64 impedance rows + channel 4's DAC row
        self.assertEqual(result.verify_mismatches, ())
        self.assertTrue(result.restored)
        self.assertEqual(result.restore_mismatches, ())
        self.assertIn("tq_mask channel=4 -> 1", result.applied)
        self.assertIn("input_dac_value channel=4 -> 200", result.applied)
        self.assertIn("input_dac_impedance -> low", result.applied)
        # Restored to the real pre-run hardware value, independently reread.
        self.assertEqual(self.device.read_register_bits(4, 6), before_channel6)
        self.assertEqual(self.device.read_register_bits(4, 0), before_channel0)

    def test_without_restore_the_change_persists(self):
        self.device.load_default_config()
        apply_channel_config(self.device, ChannelConfigOperation(
            input_dac_value_channels=(4,), input_dac_value=200, verify=True,
        ))
        self.assertEqual(self.device.read_register_bits(4, 0), bits(200, 8))

    def test_verify_catches_a_readback_mismatch(self):
        self.device.load_default_config()
        original_read_register_bits = self.device.read_register_bits

        def flaky_read_register_bits(add, subadd):
            # Simulate a write that silently didn't take (e.g. a bad
            # transaction): the post-write readback disagrees with what was
            # actually committed, for this one register only.
            if (add, subadd) == (4, 6):
                return "00000000"
            return original_read_register_bits(add, subadd)

        self.device.read_register_bits = flaky_read_register_bits
        result = apply_channel_config(self.device, ChannelConfigOperation(
            tq_mask_channels=(4,), tq_mask_value=True, verify=True,
        ))
        self.assertEqual(len(result.verify_mismatches), 1)
        mismatch = result.verify_mismatches[0]
        self.assertEqual((mismatch.add, mismatch.subadd), (4, 6))


if __name__ == "__main__":
    unittest.main()
