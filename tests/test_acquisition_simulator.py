"""Acceptance tests for the labelled synthetic acquisition simulator."""

from __future__ import annotations

import csv
from pathlib import Path
import random
import tempfile
import unittest

from radioroc_client import AcquisitionConfig, RadiorocDevice
from radioroc.application.acquisition import AcquisitionJob, AcquisitionJobConfig
from radioroc.transport.acquisition_simulator import (
    AcquisitionSimulationConfig,
    create_acquisition_simulator,
)


def event_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


class AcquisitionSimulatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.model = AcquisitionSimulationConfig(hg_mean=800.0, hg_stdev=40.0, lg_mean=120.0, lg_stdev=15.0)

    def operation(self, name: str, **changes) -> AcquisitionJobConfig:
        acquisition = AcquisitionConfig(channels=[4, 5], trigger_channel=4, batches=3,
                                        acquisitions_per_batch=20, timeout_s=1.0,
                                        out_dir=self.root / name, **changes)
        return AcquisitionJobConfig(acquisition)

    def test_real_job_produces_seeded_reproducible_events_and_manifest_metadata(self):
        operation = self.operation("first")
        transport = create_acquisition_simulator(operation, self.model, rng=random.Random(42))
        with transport:
            result = AcquisitionJob().run(RadiorocDevice(transport), operation)

        self.assertEqual((result.status, result.points), ("completed", 3))
        rows = event_rows(result.csv_path)
        self.assertEqual(len(rows), 3 * 20 * 2)  # batches * acquisitions_per_batch * channels
        self.assertEqual(sorted({row["channel"] for row in rows}), ["4", "5"])
        self.assertEqual(transport.simulation_metadata, {
            "model": "synthetic-fixed-point-acquisition-v1",
            "warning": "qualitative offline-exercise shape, not a physics-validated ASIC model",
            **self.model.as_dict(),
        })

        repeat_operation = self.operation("repeat")
        repeat_transport = create_acquisition_simulator(repeat_operation, self.model, rng=random.Random(42))
        with repeat_transport:
            repeat_result = AcquisitionJob().run(RadiorocDevice(repeat_transport), repeat_operation)
        self.assertEqual(event_rows(repeat_result.csv_path), rows)

    def test_different_seeds_produce_different_events(self):
        operation_a = self.operation("seed-a")
        transport_a = create_acquisition_simulator(operation_a, self.model, rng=random.Random(1))
        with transport_a:
            result_a = AcquisitionJob().run(RadiorocDevice(transport_a), operation_a)

        operation_b = self.operation("seed-b")
        transport_b = create_acquisition_simulator(operation_b, self.model, rng=random.Random(2))
        with transport_b:
            result_b = AcquisitionJob().run(RadiorocDevice(transport_b), operation_b)

        self.assertNotEqual(event_rows(result_a.csv_path), event_rows(result_b.csv_path))

    def test_values_are_clamped_and_produce_a_non_degenerate_spread(self):
        operation = self.operation("clamp")
        # A large stdev exercises the [0, 65535/4] clamp on both tails.
        model = AcquisitionSimulationConfig(hg_mean=100.0, hg_stdev=500.0, lg_mean=50.0, lg_stdev=200.0)
        transport = create_acquisition_simulator(operation, model, rng=random.Random(7))
        with transport:
            result = AcquisitionJob().run(RadiorocDevice(transport), operation)

        rows = event_rows(result.csv_path)
        hg_values = [float(row["hg"]) for row in rows]
        lg_values = [float(row["lg"]) for row in rows]
        self.assertTrue(all(0.0 <= value <= 65535 / 4 for value in hg_values))
        self.assertTrue(all(0.0 <= value <= 65535 / 4 for value in lg_values))
        # Not a delta spike: repeated batches at the same fixed point still vary.
        self.assertGreater(len(set(hg_values)), 1)
        self.assertGreater(len(set(lg_values)), 1)

    def test_invalid_model_parameters_are_rejected(self):
        with self.assertRaises(ValueError):
            AcquisitionSimulationConfig(hg_stdev=-1.0).validate()
        with self.assertRaises(ValueError):
            AcquisitionSimulationConfig(hg_mean=float("nan")).validate()


if __name__ == "__main__":
    unittest.main()
