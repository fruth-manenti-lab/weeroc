import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

GUI_AVAILABLE = importlib.util.find_spec("PySide6") is not None
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

if GUI_AVAILABLE:
    from PySide6.QtWidgets import QApplication
    from radioroc_client import RadiorocDevice
    from radioroc.application.acquisition import AcquisitionJob
    from radioroc.application.acquisition_worker import AcquisitionWorkerOutcome, AcquisitionWorkerSnapshot
    from radioroc.data.pedestals import compute_pedestals, find_pedestals_for_run
    from radioroc.gui.calibration_selection import CalibrationSelection
    from radioroc.gui.pedestal_window import PedestalWindow
    from test_acquisition_jobs import AcquisitionTransport, adc_payload

    _APP = QApplication.instance() or QApplication([])

    class FakeConnectionWorker:
        """Runs the real acquisition job synchronously on the fake ADC transport."""

        def __init__(self, sd=0.0, state="connected"):
            self.state = state
            self.sd = sd
            self.ops = []
            self.outcome = None
            self.cancelled = False

        def snapshot(self):
            return SimpleNamespace(state=self.state, fault=None)

        def run_acquisition(self, operation):
            self.ops.append(operation)
            nb = operation.acquisition.acquisitions_per_batch
            hg = [95.0 + (self.sd if i % 2 else -self.sd) for i in range(nb)]
            batches = [adc_payload(nb, {ch: (hg, [89.0] * nb) for ch in operation.acquisition.channels})
                       for _ in range(operation.acquisition.batches)]
            transport = AcquisitionTransport(nb_acq=nb, adc_batches=batches)
            result = AcquisitionJob().run(RadiorocDevice(transport), operation, verify_restoration=True)
            self.outcome = AcquisitionWorkerOutcome(result)

        def cancel_acquisition(self):
            self.cancelled = True

        def acquisition_snapshot(self):
            return AcquisitionWorkerSnapshot(None, (), 0, self.outcome)


@unittest.skipUnless(GUI_AVAILABLE, "PySide6 is not installed")
class PedestalWindowTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def window(self, worker):
        sel = CalibrationSelection((6, 32))
        sel.set_hold_delay_ns(35)
        sel.set_trigger_gain(3)
        return PedestalWindow(selection=sel, connection_worker=worker, runs_root=Path(self._tmp.name))

    def test_run_stores_pedestals_and_fills_table(self):
        worker = FakeConnectionWorker()
        win = self.window(worker)
        win.events.setValue(40)
        self.assertEqual(win.events.value(), 40)
        self.assertTrue(win.run_button.isEnabled())
        win.start_run()
        a = worker.ops[0].acquisition
        self.assertEqual((a.channels, a.hold_delay_ns, a.trigger_preamp_gain, a.batches), ([6, 32], 35, 3, 2))
        self.assertTrue(a.synchro_trigger)
        win.poll_worker()
        ps = win.shared_selection.pedestals
        self.assertEqual(ps.hg(), {6: 95.0, 32: 95.0})
        self.assertEqual(win.table.rowCount(), 2)
        self.assertEqual(win.table.item(0, 1).text(), "95.0")
        self.assertTrue(win.warning.isHidden())
        self.assertFalse(win.cancel_button.isEnabled())
        self.assertEqual(find_pedestals_for_run(a.out_dir), ps)

    def test_default_events_and_disabled_when_disconnected(self):
        win = self.window(FakeConnectionWorker(state="idle"))
        self.assertEqual(win.events.value(), 200)
        self.assertFalse(win.run_button.isEnabled())
        win.start_run()
        self.assertFalse(win._running)

    def test_warns_on_large_sd(self):
        worker = FakeConnectionWorker(sd=10.0)
        win = self.window(worker)
        win.start_run()
        win.poll_worker()
        self.assertFalse(win.warning.isHidden())
        self.assertIn("pulses present", win.warning.text())

    def test_cancel_and_shown_on_existing_pedestals(self):
        sel_ps = compute_pedestals([{"channel": 6, "hg": 90 + i, "lg": 80} for i in range(6)])
        worker = FakeConnectionWorker()
        win = self.window(worker)
        win._running = True
        win.cancel_run()
        self.assertTrue(worker.cancelled)
        win.shared_selection.pedestals = sel_ps
        self.assertEqual(win.table.rowCount(), 1)

    def test_main_window_registers_tab_in_order(self):
        from radioroc.gui.main_window import MainWindow
        main = MainWindow()
        tabs = [main.calibration_tabs.tabText(i) for i in range(main.calibration_tabs.count())]
        self.assertEqual(tabs, ["Threshold scan", "Autocalibration", "Pedestals", "Hold scan", "S-curve"])
        main.close()


if __name__ == "__main__":
    unittest.main()
