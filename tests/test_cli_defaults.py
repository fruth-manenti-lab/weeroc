"""Offline tests: CLI scripts print an 'Effective settings' block marking script defaults."""

import contextlib
import io
import json
import unittest
from unittest.mock import patch

import radioroc_client
from scripts import (
    radioroc_acquire,
    radioroc_autocalibrate,
    radioroc_channel_config,
    radioroc_hold_scan,
    radioroc_scurve,
    radioroc_threshold_scan,
)
from scripts.radioroc_cli_common import print_effective_settings


def run_main(module, argv):
    out, err = io.StringIO(), io.StringIO()
    with patch("sys.argv", ["prog", *argv]), \
            patch.object(radioroc_client.RadiorocSerial, "from_config",
                         side_effect=AssertionError("serial port opened")) as opener, \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = module.main()
    return code, out.getvalue(), err.getvalue(), opener


class CliDefaultsTest(unittest.TestCase):
    def test_helper_marks_defaults_and_none(self):
        buf = io.StringIO()
        print_effective_settings("t", {"a": 1, "b": None, "c": 3}, {"a": "why", "b": None}, file=buf)
        text = buf.getvalue()
        self.assertIn("a: 1 (script default; why)", text)
        self.assertIn("b: chip as is (script default)", text)
        self.assertIn("c: 3\n", text)

    def test_acquire_dry_run_defaults(self):
        code, out, err, opener = run_main(radioroc_acquire, [])
        self.assertEqual(code, 0)
        json.loads(out)  # stdout stays valid JSON
        opener.assert_not_called()
        self.assertIn("Effective settings", err)
        self.assertIn("threshold DAC: 530 (script default; not the chip's current threshold", err)
        self.assertIn("desktop app uses the operating threshold from the Calibration bar", err)
        self.assertIn("trigger preamp gain code (paT): 1 (script default", err)
        self.assertIn("hold delay ns: 530 (script default", err)
        self.assertIn("note: long hold for a self-triggered run", err)

    def test_acquire_explicit_values_not_marked(self):
        code, out, err, _ = run_main(radioroc_acquire, [
            "--channels", "6", "--threshold-dac", "40", "--pat-gain", "8", "--hold-delay-ns", "30",
            "--conversion-delay-ns", "400", "--acquisitions-per-batch", "5", "--batches", "2",
            "--timeout-s", "3", "--adc-trigger-type", "0", "--adc-trigger-source", "3",
            "--adc-trigger-source-2", "0", "--trigger-channel-2", "0", "--adc-window-ns", "50",
            "--adc-nb-trig", "1", "--trigger-channel", "6",
        ])
        self.assertEqual(code, 0)
        self.assertIn("threshold DAC: 40\n", err)
        self.assertIn("trigger preamp gain code (paT): 8\n", err)
        self.assertNotIn("script default", err.replace("(values marked 'script default'", ""))
        self.assertNotIn("long hold", err)

    def test_acquire_synchro_suppresses_long_hold_note(self):
        _, _, err, _ = run_main(radioroc_acquire, ["--synchro-trigger"])
        self.assertNotIn("long hold", err)

    def test_other_scripts_dry_run(self):
        cases = [
            (radioroc_threshold_scan, "DAC max: 600 (script default)"),
            (radioroc_scurve, "DAC step: 50 (script default)"),
            (radioroc_hold_scan, "hold max ns: 800 (script default)"),
            (radioroc_autocalibrate, "channels: 4 (script default)"),
        ]
        for module, expected in cases:
            with self.subTest(module=module.__name__):
                code, out, err, opener = run_main(module, [])
                self.assertEqual(code, 0)
                json.loads(out)
                opener.assert_not_called()
                self.assertIn("Effective settings", err)
                self.assertIn(expected, err)
                self.assertIn("trigger preamp gain code (paT): chip as is", err)

    def test_hold_scan_threshold_left_unchanged(self):
        _, _, err, _ = run_main(radioroc_hold_scan, [])
        self.assertIn("threshold DAC: chip as is (script default", err)

    def test_channel_config_block_before_transport(self):
        out, err = io.StringIO(), io.StringIO()
        with patch("sys.argv", ["prog", "--tq-mask", "3"]), \
                patch.object(radioroc_client.RadiorocSerial, "from_config",
                             side_effect=RuntimeError("no port")), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = radioroc_channel_config.main()
        self.assertEqual(code, 1)
        self.assertIn("TQ mask value: 1 (script default)", err.getvalue())
        self.assertIn("input DAC enable value: 1 (script default)", err.getvalue())


if __name__ == "__main__":
    unittest.main()
