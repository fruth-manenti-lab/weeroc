"""Offline tests for the opt-in "S-curve clock on IO0" option (IO mux index 4)."""

from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

from radioroc_client import RadiorocDevice, ScurveConfig
from radioroc.application import CancellationToken
from radioroc.application.autocalibration import AutocalibrationJob, AutocalibrationJobConfig
from radioroc.application.scurve import ScurveJob, ScurveJobConfig
from radioroc.transport.errors import TransportIOError
from test_scurve_jobs import ScurveTransport

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
GUI_AVAILABLE = (importlib.util.find_spec("PySide6") is not None
                 and importlib.util.find_spec("matplotlib") is not None)

# io1 = 3, io0 = 5 (the original, non-default IO0 mux that must be restored).
WORD77, WORD78 = "00011101", "00000000"


def mux_writes(transport):
    return [entry for entry in transport.trace if entry[0] == "write" and entry[1] in (77, 78)]


class ScurveClockIo0Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / "run"
        self.scan = ScurveConfig(channels=[4], dac_min=0, dac_max=1, dac_step=1,
                                 out_dir=self.directory, scurve_clock_io0=True)
        self.transport = ScurveTransport()
        self.transport.words[77], self.transport.words[78] = WORD77, WORD78
        self.device = RadiorocDevice(self.transport)

    def run_job(self, **kwargs):
        return ScurveJob().run(self.device, ScurveJobConfig(self.scan), **kwargs)

    def manifest(self):
        return json.loads((self.directory / "metadata.json").read_text())

    def test_writes_index_4_then_restores_original(self):
        result = self.run_job(verify_restoration=True)
        self.assertEqual((result.status, result.cleanup_status), ("completed", "restored"))
        self.assertEqual(result.verification["status"], "passed")
        writes = mux_writes(self.transport)
        # io0 -> 4 keeps io1 = 3: low 6 bits 011 100.
        self.assertEqual(writes[:2], [("write", 77, "00011100"), ("write", 78, "0000000")])
        self.assertEqual((self.transport.words[77], self.transport.words[78]), (WORD77, WORD78))
        self.assertEqual(self.manifest()["snapshot"]["fpga"]["77"], WORD77)

    def test_restored_when_scan_raises(self):
        self.transport.fail_point_read = TransportIOError("lost")
        result = self.run_job()
        self.assertEqual(result.status, "disconnected")
        self.assertEqual(mux_writes(self.transport)[:1], [("write", 77, "00011100")])
        self.assertEqual((self.transport.words[77], self.transport.words[78]), (WORD77, WORD78))

    def test_restored_when_cancelled(self):
        token = CancellationToken()
        self.transport.cancel_after_reads = (token, 1)
        result = self.run_job(cancellation=token)
        self.assertEqual(result.status, "cancelled")
        self.assertEqual((self.transport.words[77], self.transport.words[78]), (WORD77, WORD78))

    def test_default_off_touches_no_mux_words(self):
        self.scan = replace(self.scan, scurve_clock_io0=False)
        result = self.run_job(verify_restoration=True)
        self.assertEqual(result.status, "completed")
        self.assertEqual(mux_writes(self.transport), [])
        self.assertNotIn(77, [e[1] for e in self.transport.trace if e[0] == "read"])
        self.assertEqual(set(self.manifest()["snapshot"]["fpga"]), {"1", "3", "6"})
        self.assertIs(self.manifest()["operation"]["scan"]["scurve_clock_io0"], False)

    def test_manifest_records_option_and_footprint(self):
        self.run_job()
        manifest = self.manifest()
        self.assertIs(manifest["operation"]["scan"]["scurve_clock_io0"], True)
        self.assertEqual(set(manifest["snapshot"]["fpga"]), {"1", "3", "6", "77", "78"})

    def test_validation_requires_bool(self):
        with self.assertRaises(ValueError):
            replace(self.scan, scurve_clock_io0=1).validate()
        with self.assertRaises(ValueError):
            AutocalibrationJobConfig(channels=[4], scurve_clock_io0="yes").validate()

    def test_autocalibration_passes_option_to_each_sub_scan(self):
        out = Path(self.tmp.name) / "auto"
        config = AutocalibrationJobConfig(
            channels=[4], out_dir=out, scurve_clock_io0=True,
            probe_dac_min=0, probe_dac_max=20, probe_dac_step=10,
            transition_dac_step=10, transition_margin=5, transition_dac_floor=20,
            transition_dac_cap=20, final_window_before=5, final_window_after=5, final_dac_step=5)
        AutocalibrationJob().run(self.device, config)
        writes = [e for e in mux_writes(self.transport) if e[1] == 77]
        self.assertTrue(len(writes) >= 4)
        self.assertEqual((self.transport.words[77], self.transport.words[78]), (WORD77, WORD78))
        manifests = [json.loads(p.read_text()) for p in out.rglob("metadata.json")]
        self.assertTrue(manifests)
        self.assertTrue(all(m["operation"]["scan"]["scurve_clock_io0"] for m in manifests))


@unittest.skipUnless(GUI_AVAILABLE, "install [gui] for desktop acceptance checks")
class ClockIo0GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def check(self, window, checkbox, get_flag):
        self.addCleanup(window.deleteLater)
        window.output.setText(str(Path(tempfile.gettempdir()) / "radioroc_clock_io0_nonexistent"))
        self.assertFalse(checkbox.isChecked())
        self.assertFalse(get_flag(window.operation()))
        checkbox.setChecked(True)
        self.assertIs(get_flag(window.operation()), True)

    def test_scurve_checkbox_maps_to_operation(self):
        from radioroc.gui.scurve_window import ScurveWindow
        window = ScurveWindow()
        window.mode.setCurrentIndex(0)
        self.check(window, window.clock_io0, lambda op: op.scan.scurve_clock_io0)

    def test_autocalibration_checkbox_maps_to_operation(self):
        from radioroc.gui.autocalibration_window import AutocalibrationWindow
        window = AutocalibrationWindow()
        self.check(window, window.clock_io0, lambda op: op.scurve_clock_io0)


if __name__ == "__main__":
    unittest.main()
