"""Hold-scan profile fit and raw-sample persistence."""

import tempfile
import unittest
from pathlib import Path

from radioroc.data.hold_profile import fit_hold_profile
from radioroc.data.hold_reader import read_hold_samples
from radioroc.data.hold_scan import HoldRunWriter


class HoldProfileTests(unittest.TestCase):
    def test_peak_found_near_true_maximum(self):
        xs = list(range(0, 101, 10))
        ys = [1000 - (x - 40) ** 2 / 2 for x in xs]
        fit = fit_hold_profile(xs, ys, [5] * len(xs))
        self.assertAlmostEqual(fit["x_peak"], 40, delta=2)
        self.assertAlmostEqual(fit["y_peak"], 1000, delta=10)

    def test_too_few_points_gives_no_fit(self):
        self.assertIsNone(fit_hold_profile([1, 2, 3], [1, 2, 1]))

    def test_zero_stdev_falls_back_to_unweighted(self):
        xs = list(range(8))
        self.assertIsNotNone(fit_hold_profile(xs, [0, 1, 4, 6, 6, 4, 1, 0], [0] * 8))

    def test_samples_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "run"
            writer = HoldRunWriter(directory, [4], {}, x_name="hold_delay_ns")
            writer.append_samples([
                {"hold_delay_ns": 30, "event": 0, "channel": 4, "hg": 100.0, "lg": 10.0},
                {"hold_delay_ns": 30, "event": 1, "channel": 4, "hg": 110.0, "lg": 11.0}])
            self.assertEqual(read_hold_samples(directory),
                             {30: {"ch4_hg": [100.0, 110.0], "ch4_lg": [10.0, 11.0]}})
            self.assertEqual(read_hold_samples(Path(tmp) / "missing"), {})


class CleanupRunnerTests(unittest.TestCase):
    def test_board_timeout_skips_remaining_cleanup(self):
        from radioroc.application.jobs import CleanupRunner
        from radioroc.transport.errors import TransportTimeoutError
        errors, calls = [], []

        def dead():
            calls.append("dead")
            raise TransportTimeoutError("no response")
        runner = CleanupRunner(errors, str)
        runner("first", dead)
        runner("second", lambda: calls.append("second"))
        runner("third", lambda: calls.append("third"))
        self.assertEqual(calls, ["dead"])
        self.assertTrue(runner.dead)
        self.assertEqual(len(errors), 2)

    def test_ordinary_failure_does_not_stop_cleanup(self):
        from radioroc.application.jobs import CleanupRunner
        errors, calls = [], []

        def bad():
            raise ValueError("x")
        runner = CleanupRunner(errors, str)
        runner("a", bad)
        runner("b", lambda: calls.append("b"))
        self.assertEqual(calls, ["b"])
        self.assertFalse(runner.dead)


if __name__ == "__main__":
    unittest.main()
