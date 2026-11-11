"""Offline tests for comparing settings with the board's register table."""

import contextlib
import io
import unittest

# Bootstrap the checkout package when test discovery sees an older installed wheel.
import radioroc_client  # noqa: F401
from radioroc_client import RadiorocDevice

from radioroc.application.board_state import board_value, operation_matches, rows_by_address
from radioroc.application.channel_config import ChannelConfigOperation


def default_rows():
    return ChannelConfigOperation().load_rows()


def rows_after(setter_name, *args, **kwargs):
    """The packaged table after one real setter call (dry run, no transport)."""
    device = RadiorocDevice(None, dry_run=True)
    device.i2c_rows = default_rows()
    with contextlib.redirect_stdout(io.StringIO()):
        getattr(device, setter_name)(*args, **kwargs)
    return rows_by_address(device.i2c_rows)


class BoardStateTests(unittest.TestCase):
    def test_board_value_recovers_the_packaged_defaults(self):
        rows = rows_by_address(default_rows())
        self.assertEqual(board_value(rows, "trigger_preamp_gain_values", range(64), 5), 8)
        self.assertEqual(board_value(rows, "t1_threshold_dac", range(1024)), 512)
        self.assertEqual(board_value(rows, "delay_code", range(256)), 255)
        self.assertEqual(board_value(rows, "trigger_selection",
                                     ["external", "local_t1", "global_t1"]), "global_t1")

    def test_matches_only_the_value_the_board_holds(self):
        rows = rows_after("set_trigger_preamp_gain_for_channel", 7, 21)
        op = lambda ch, v: ChannelConfigOperation(trigger_preamp_gain_values={ch: v})
        self.assertTrue(operation_matches(rows, op(7, 21)))
        self.assertFalse(operation_matches(rows, op(7, 8)))
        self.assertTrue(operation_matches(rows, op(6, 8)))  # neighbour untouched
        self.assertEqual(board_value(rows, "trigger_preamp_gain_values", range(64), 7), 21)

    def test_shared_register_fields_do_not_mask_each_other(self):
        # T1 and T2 thresholds share address 65 subaddress 2.
        rows = rows_after("set_t2_threshold_dac", 300)
        self.assertTrue(operation_matches(rows, ChannelConfigOperation(t1_threshold_dac=512)))
        self.assertTrue(operation_matches(rows, ChannelConfigOperation(t2_threshold_dac=300)))
        self.assertFalse(operation_matches(rows, ChannelConfigOperation(t2_threshold_dac=512)))

    def test_missing_register_counts_as_not_matching(self):
        rows = rows_by_address(default_rows())
        del rows[(7, 1)]
        self.assertFalse(operation_matches(
            rows, ChannelConfigOperation(trigger_preamp_gain_values={7: 8})))
        self.assertIsNone(board_value(rows, "trigger_preamp_gain_values", range(64), 7))

    def test_comparison_does_not_modify_the_rows(self):
        rows = rows_by_address(default_rows())
        before = dict(rows)
        operation_matches(rows, ChannelConfigOperation(t1_calibration_dac_values={3: 40}))
        self.assertEqual(rows, before)


if __name__ == "__main__":
    unittest.main()
