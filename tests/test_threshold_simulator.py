"""Acceptance tests for the labelled deterministic threshold simulator."""

from __future__ import annotations

import csv
from dataclasses import replace
import math
from pathlib import Path
import tempfile
import unittest

from radioroc_client import RadiorocDevice, ThresholdScanConfig
from radioroc.application.threshold import ThresholdJob, ThresholdJobConfig
from radioroc.transport.threshold_simulator import (
    ThresholdSimulationConfig,
    create_threshold_simulator,
)


def point_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


class ThresholdSimulatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.model = ThresholdSimulationConfig(midpoint=500, width=20,
                                               plateau_hz=100000, channel_spacing=3)

    def operation(self, name: str, **changes) -> ThresholdJobConfig:
        scan = ThresholdScanConfig([0, 1], dac_min=450, dac_max=550, dac_step=50,
                                   trigger_window_ms=1, out_dir=self.root / name)
        return ThresholdJobConfig(replace(scan, **changes))

    @staticmethod
    def expected_rate(model, *, dac, channel, window_ms):
        fraction = 1 / (1 + math.exp((dac - (model.midpoint + channel * model.channel_spacing)) / model.width))
        count = round(model.plateau_hz * fraction * window_ms / 1000)
        return count * 1000 / window_ms

    def test_real_job_produces_repeatable_logistic_curve_and_manifest_metadata(self):
        operation = self.operation("first")
        transport = create_threshold_simulator(operation, self.model)
        with transport:
            result = ThresholdJob().run(RadiorocDevice(transport), operation)

        self.assertEqual((result.status, result.points, result.attempts), ("completed", 3, 6))
        values = point_rows(result.csv_path)
        self.assertEqual([int(row["DAC"]) for row in values], [450, 500, 550])
        self.assertGreater(float(values[0]["ch0"]), float(values[1]["ch0"]))
        self.assertGreater(float(values[1]["ch0"]), float(values[2]["ch0"]))
        self.assertEqual(float(values[1]["ch1"]), self.expected_rate(self.model, dac=500, channel=1, window_ms=1))
        self.assertEqual(transport.simulation_metadata, {
            "model": "deterministic-logistic-v1", **self.model.as_dict(),
        })

        repeat = self.operation("repeat")
        with create_threshold_simulator(repeat, self.model) as second:
            repeated_result = ThresholdJob().run(RadiorocDevice(second), repeat)
        self.assertEqual(repeated_result.csv_path.read_bytes(), result.csv_path.read_bytes())

    def test_t1_and_t2_register_encodings_drive_the_same_selected_dac(self):
        for t1 in (True, False):
            with self.subTest(t1=t1):
                operation = self.operation(f"threshold-{t1}", channels=[3], dac_min=525,
                                           dac_max=525, dac_step=1, trigger_window_ms=10, t1=t1)
                with create_threshold_simulator(operation, self.model) as transport:
                    result = ThresholdJob().run(RadiorocDevice(transport), operation)
                value = float(point_rows(result.csv_path)[0]["ch3"])
                self.assertEqual(value, self.expected_rate(self.model, dac=525, channel=3, window_ms=10))

    def test_real_cleanup_restores_seeded_asic_and_fpga_state(self):
        operation = self.operation("cleanup", use_ctest=True, trigger_preamp_gain=12)
        transport = create_threshold_simulator(operation, self.model)
        original_asic = dict(transport.asic)
        original_words = {address: transport.words[address] for address in (0, 1, 6)}
        with transport:
            result = ThresholdJob().run(RadiorocDevice(transport), operation)

        self.assertEqual((result.status, result.cleanup_status), ("completed", "restored"))
        self.assertEqual(transport.asic, original_asic)
        self.assertEqual({address: transport.words[address] for address in (0, 1, 6)}, original_words)

    def test_model_validation_rejects_invalid_values_and_accepts_signed_spacing(self):
        for changes in (
            {"midpoint": float("nan")}, {"width": 0}, {"width": float("inf")},
            {"plateau_hz": -1}, {"plateau_hz": float("nan")},
            {"channel_spacing": float("inf")}, {"channel_spacing": True},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                ThresholdSimulationConfig(**changes).validate()
        model = ThresholdSimulationConfig(channel_spacing=-2)
        self.assertEqual(model.as_dict()["channel_spacing"], -2)
