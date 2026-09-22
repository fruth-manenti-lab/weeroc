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
        with self.assertRaises(ValueError):
            ChannelConfigOperation(t1_mask_channels=(64,)).validate()
        with self.assertRaises(ValueError):
            ChannelConfigOperation(input_dac_values={64: 10}).validate()
        with self.assertRaises(ValueError):
            ChannelConfigOperation(input_dac_values={4: 256}).validate()
        with self.assertRaises(ValueError):
            ChannelConfigOperation(input_dac_value_channels=(4,), input_dac_value=10,
                                   input_dac_values={4: 20}).validate()  # overlapping channel
        with self.assertRaises(ValueError):
            ChannelConfigOperation(tq_mask_channels=(4,),
                                   tq_mask_states={4: True}).validate()  # overlapping channel
        with self.assertRaises(ValueError):
            ChannelConfigOperation(t1_mask_states={64: True}).validate()
        with self.assertRaises(ValueError):
            ChannelConfigOperation(t1_calibration_dac_values={4: 64}).validate()
        with self.assertRaises(ValueError):
            ChannelConfigOperation(t2_calibration_dac_values={64: 0}).validate()
        with self.assertRaises(ValueError):
            ChannelConfigOperation(trigger_preamp_gain_values={4: 64}).validate()
        with self.assertRaises(ValueError):
            ChannelConfigOperation(trigger_preamp_compensation_values={64: 0}).validate()
        with self.assertRaises(ValueError):
            ChannelConfigOperation(high_gain_shaping_slow_states={64: True}).validate()
        with self.assertRaises(ValueError):
            ChannelConfigOperation(t1_threshold_dac=1024).validate()
        with self.assertRaises(ValueError):
            ChannelConfigOperation(delay_code=256).validate()
        with self.assertRaises(ValueError):
            ChannelConfigOperation(delay_slope=16).validate()
        with self.assertRaises(ValueError):
            ChannelConfigOperation(trigger_selection="not_a_mode").validate()

    def test_validate_accepts_mask_and_per_channel_values_alone(self):
        ChannelConfigOperation(t1_mask_channels=(4,)).validate()
        ChannelConfigOperation(t2_mask_channels=(4,)).validate()
        ChannelConfigOperation(input_dac_values={4: 10, 5: 20}).validate()
        ChannelConfigOperation(tq_mask_states={4: True, 5: False}).validate()
        ChannelConfigOperation(t1_mask_states={4: True}).validate()
        ChannelConfigOperation(t2_mask_states={4: True}).validate()
        ChannelConfigOperation(t1_calibration_dac_values={4: 63}).validate()
        ChannelConfigOperation(t2_calibration_dac_values={4: 0}).validate()
        ChannelConfigOperation(trigger_preamp_gain_values={4: 63}).validate()
        ChannelConfigOperation(high_gain_shaping_slow_states={4: True}).validate()
        ChannelConfigOperation(t1_threshold_dac=1023).validate()
        ChannelConfigOperation(trigger_selection="global_t1").validate()
        ChannelConfigOperation(delay_code=255, delay_slope=15).validate()

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

    def test_t1_and_t2_mask_channels_write_distinct_bits(self):
        self.device.load_default_config()
        result = apply_channel_config(self.device, ChannelConfigOperation(
            t1_mask_channels=(4,), t1_mask_value=True,
            t2_mask_channels=(4,), t2_mask_value=False,
            verify=True,
        ))
        self.assertIn("t1_mask channel=4 -> 1", result.applied)
        self.assertIn("t2_mask channel=4 -> 0", result.applied)
        row = self.device.find_i2c_row(4, 6).data
        self.assertEqual(row[3], "1")  # T1 bit
        self.assertEqual(row[4], "0")  # T2 bit
        self.assertEqual(result.verify_mismatches, ())

    def test_per_channel_input_dac_values_write_independent_codes(self):
        self.device.load_default_config()
        result = apply_channel_config(self.device, ChannelConfigOperation(
            input_dac_values={4: 200, 5: 10}, verify=True,
        ))
        self.assertEqual(self.device.read_register_bits(4, 0), bits(200, 8))
        self.assertEqual(self.device.read_register_bits(5, 0), bits(10, 8))
        self.assertIn("input_dac_value channel=4 -> 200", result.applied)
        self.assertIn("input_dac_value channel=5 -> 10", result.applied)
        self.assertEqual(result.verify_mismatches, ())

    def test_per_channel_mask_states_write_independent_bits(self):
        self.device.load_default_config()
        result = apply_channel_config(self.device, ChannelConfigOperation(
            tq_mask_states={4: True, 5: False},
            t1_mask_states={4: True, 5: False},
            t2_mask_states={4: False, 5: True},
            verify=True,
        ))
        row4 = self.device.find_i2c_row(4, 6).data
        row5 = self.device.find_i2c_row(5, 6).data
        self.assertEqual((row4[3], row4[4], row4[5]), ("1", "0", "1"))  # T1, T2, TQ
        self.assertEqual((row5[3], row5[4], row5[5]), ("0", "1", "0"))
        self.assertEqual(result.verify_mismatches, ())

    def test_per_channel_calibration_dac_values_write_independent_codes(self):
        self.device.load_default_config()
        result = apply_channel_config(self.device, ChannelConfigOperation(
            t1_calibration_dac_values={4: 50, 5: 0},
            t2_calibration_dac_values={4: 10, 5: 63},
            verify=True,
        ))
        self.assertEqual(self.device.find_i2c_row(4, 4).data[2:], bits(50, 6))
        self.assertEqual(self.device.find_i2c_row(5, 4).data[2:], bits(0, 6))
        self.assertEqual(self.device.find_i2c_row(4, 5).data[2:], bits(10, 6))
        self.assertEqual(self.device.find_i2c_row(5, 5).data[2:], bits(63, 6))
        self.assertIn("t1_calibration_dac channel=4 -> 50", result.applied)
        self.assertIn("t2_calibration_dac channel=5 -> 63", result.applied)
        self.assertEqual(result.verify_mismatches, ())

    def test_per_channel_main_tab_front_end_values_write_independent_codes(self):
        self.device.load_default_config()
        result = apply_channel_config(self.device, ChannelConfigOperation(
            trigger_preamp_gain_values={4: 30, 5: 10},
            trigger_preamp_compensation_values={4: 2},
            high_gain_values={4: 12},
            low_gain_values={4: 9},
            high_gain_shaping_values={4: 7},
            low_gain_shaping_values={4: 3},
            high_gain_shaping_slow_states={4: True},
            low_gain_shaping_slow_states={4: True},
            verify=True,
        ))
        self.assertEqual(self.device.find_i2c_row(4, 1).data[2:8], bits(30, 6))
        self.assertEqual(self.device.find_i2c_row(5, 1).data[2:8], bits(10, 6))
        self.assertEqual(self.device.find_i2c_row(4, 1).data[0:2], bits(2, 2))
        self.assertEqual(self.device.find_i2c_row(4, 2).data[4:8], bits(12, 4))
        self.assertEqual(self.device.find_i2c_row(4, 2).data[0:4], bits(9, 4))
        self.assertEqual(self.device.find_i2c_row(4, 3).data[4:8], bits(7, 4))
        self.assertEqual(self.device.find_i2c_row(4, 3).data[0:4], bits(3, 4))
        self.assertEqual(self.device.find_i2c_row(4, 7).data[1], "1")
        self.assertEqual(self.device.find_i2c_row(4, 7).data[0], "1")
        self.assertIn("trigger_preamp_gain channel=4 -> 30", result.applied)
        self.assertIn("trigger_preamp_gain channel=5 -> 10", result.applied)
        self.assertEqual(result.verify_mismatches, ())

    def test_common_threshold_and_trigger_selection_fields_round_trip(self):
        self.device.load_default_config()
        result = apply_channel_config(self.device, ChannelConfigOperation(
            t1_threshold_dac=0x2AB,
            trigger_selection="local_tq",
            delay_code=200,
            delay_slope=9,
            verify=True,
        ))
        self.assertEqual(self.device.find_i2c_row(65, 1).data, bits(0x2AB & 0xFF, 8))
        self.assertEqual(self.device.find_i2c_row(65, 2).data[0:2], bits((0x2AB >> 8) & 0x3, 2))
        self.assertEqual(self.device.find_i2c_row(65, 12).data[4:8], bits(0b0011, 4))
        self.assertEqual(self.device.find_i2c_row(65, 8).data, bits(200, 8))
        self.assertEqual(self.device.find_i2c_row(65, 9).data[0:4], bits(9, 4))
        self.assertIn("t1_threshold_dac -> 683", result.applied)
        self.assertIn("trigger_selection -> local_tq", result.applied)
        self.assertIn("delay_code -> 200", result.applied)
        self.assertIn("delay_slope -> 9", result.applied)
        self.assertEqual(result.verify_mismatches, ())

    def test_t1_threshold_dac_alone_does_not_touch_t2_or_tq_independent_bits(self):
        self.device.load_default_config()
        before_t2_high = self.device.find_i2c_row(65, 3).data[0:4]  # dac2[9:6]
        before_tq_low = self.device.find_i2c_row(65, 3).data[4:8]  # dacQ[3:0]
        before_tq_high = self.device.find_i2c_row(65, 4).data  # dacQ[9:4]
        result = apply_channel_config(self.device, ChannelConfigOperation(
            t1_threshold_dac=0x155, verify=True,
        ))
        self.assertEqual(self.device.find_i2c_row(65, 1).data, bits(0x155 & 0xFF, 8))
        self.assertEqual(self.device.find_i2c_row(65, 2).data[0:2], bits((0x155 >> 8) & 0x3, 2))
        # T2's low 6 bits, sharing subadd 2 with T1's high bits, are untouched.
        self.assertEqual(self.device.find_i2c_row(65, 2).data[2:8], "000010")
        self.assertEqual(self.device.find_i2c_row(65, 3).data[0:4], before_t2_high)
        self.assertEqual(self.device.find_i2c_row(65, 3).data[4:8], before_tq_low)
        self.assertEqual(self.device.find_i2c_row(65, 4).data, before_tq_high)
        self.assertEqual(result.touched_rows, 2)  # only (65, 1) and (65, 2)
        self.assertEqual(result.verify_mismatches, ())


if __name__ == "__main__":
    unittest.main()
