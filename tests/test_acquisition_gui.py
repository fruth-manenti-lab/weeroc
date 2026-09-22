"""Optional Qt acceptance checks; all sessions are simulated and offscreen."""

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

GUI_AVAILABLE = (importlib.util.find_spec("PySide6") is not None
                 and importlib.util.find_spec("matplotlib") is not None)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@unittest.skipUnless(GUI_AVAILABLE, "install [gui] for desktop acceptance checks")
class AcquisitionGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from radioroc.gui.acquisition_window import AcquisitionWindow
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / "run"
        self.window = AcquisitionWindow()
        self.window.mode.setCurrentIndex(0)  # this suite only exercises simulation
        self.window.output.setText(str(self.directory))
        self.window.batches.setValue(3)
        self.window.acquisitions_per_batch.setValue(2)
        self.serial = patch("serial.Serial", side_effect=AssertionError("GUI opened hardware"))
        self.serial.start()
        self.addCleanup(self.serial.stop)
        self.addCleanup(self.cleanup_window)

    def cleanup_window(self):
        if self.window.worker:
            self.window.cancel_run()
            self.wait_idle()
        self.window.close()
        # deleteLater routes destruction through Qt's own thread-safe
        # mechanism instead of leaving it to Python's cyclic GC, which can
        # run on any thread and crashes destroying a main-thread QTimer.
        self.window.deleteLater()
        self.app.processEvents()

    def wait_idle(self):
        deadline = time.monotonic() + 15
        while self.window.worker is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertIsNone(self.window.worker, "worker failed to finish and release session")

    def test_preview_and_invalid_input_are_offline(self):
        self.assertIsNotNone(self.window.preview())
        self.assertIn("temporary_asic_registers", self.window.details.toPlainText())
        self.assertFalse(self.directory.exists())
        self.window.channel_select.set_channels([])
        self.window.start_run()
        self.assertIsNone(self.window.worker)
        self.assertIn("at least one channel is required", self.window.status.text())
        self.assertFalse(self.directory.exists())

    def test_operation_uses_selected_channels(self):
        self.window.channel_select.set_channels([1, 3, 6])
        self.window.trigger_channel.setValue(3)
        operation = self.window.operation()
        self.assertEqual(operation.acquisition.channels, [1, 3, 6])
        self.assertEqual(operation.acquisition.trigger_channel, 3)

    def test_optional_fields_default_to_keep_current(self):
        operation = self.window.operation()
        self.assertIsNone(operation.acquisition.threshold_dac)
        self.assertIsNone(operation.acquisition.trigger_preamp_gain)
        self.assertIsNone(operation.acquisition.high_gain_code)
        self.assertIsNone(operation.acquisition.low_gain_code)

    def test_configure_finish_and_reopen(self):
        self.window.discriminator.setCurrentIndex(1)
        self.window.threshold_dac.setValue(300)
        self.window.start_run()
        self.assertFalse(self.window.controls.isEnabled())
        self.wait_idle()
        self.assertIn("completed", self.window.status.text())
        self.assertIn("3 batches", self.window.status.text())
        self.assertIn("ch4_hg", self.window.batch_summary.toPlainText())
        manifest = json.loads((self.directory / "metadata.json").read_text())
        self.assertFalse(manifest["operation"]["acquisition"]["t1"])
        self.assertEqual(manifest["operation"]["acquisition"]["threshold_dac"], 300)
        rows_path = self.directory / "events.csv"
        self.assertTrue(rows_path.exists())

        self.window.open_saved(self.directory)
        self.assertIn("SAVED RUN", self.window.banner.text())
        self.assertIn("SIMULATION", self.window.status.text())
        self.assertIn("completed", self.window.status.text())

    def test_cancel_close_keeps_event_loop_responsive_and_waits_for_cleanup(self):
        from PySide6.QtCore import QTimer
        ticks = []
        heartbeat = QTimer()
        heartbeat.setInterval(1)
        heartbeat.timeout.connect(lambda: ticks.append(1))
        heartbeat.start()
        self.window.show()
        self.window.batches.setValue(100000)
        self.window.start_run()
        # Wait for actual running state before closing.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self.app.processEvents()
            snap = self.window.worker.snapshot()
            if snap.event and snap.event.status == "running":
                break
            time.sleep(0.005)
        self.assertIsNotNone(snap.event)
        self.assertEqual(snap.event.status, "running")
        self.window.close()
        self.assertTrue(self.window.isVisible())
        self.wait_idle()
        heartbeat.stop()
        self.assertGreater(len(ticks), 0)
        self.assertFalse(self.window.isVisible())
        manifest = json.loads((self.directory / "metadata.json").read_text())
        self.assertEqual(manifest["status"], "cancelled")
        self.assertEqual(manifest["cleanup"]["status"], "restored")

    def test_reopen_nonterminal_manifest_is_incomplete(self):
        self.window.start_run()
        self.wait_idle()
        path = self.directory / "metadata.json"
        manifest = json.loads(path.read_text())
        manifest["status"] = "running"
        manifest["cleanup"]["status"] = "pending"
        path.write_text(json.dumps(manifest))
        self.window.open_saved(self.directory)
        self.assertIn("incomplete", self.window.status.text())
        self.assertIn("SIMULATION", self.window.status.text())

    def test_hardware_mode_cannot_start(self):
        self.window.mode.setCurrentIndex(1)
        self.assertFalse(self.window.run_button.isEnabled())
        self.window.start_run()
        self.assertIsNone(self.window.worker)
        self.assertFalse(self.directory.exists())

    def test_open_missing_run_reports_an_error_without_raising(self):
        self.window.open_saved(self.directory / "does-not-exist")
        self.assertIn("Cannot open result", self.window.status.text())

    # -- spectra: histogram of raw per-channel HG/LG values. -----------

    def test_histogram_renders_after_completed_simulation_run(self):
        self.window.channel_select.set_channels([2, 4])
        self.window.start_run()
        self.wait_idle()
        self.assertTrue(self.window._spectra_rows)
        self.assertGreater(len(self.window.axes.patches), 0)

    def test_channel_visibility_toggle_changes_what_is_plotted(self):
        self.window.channel_select.set_channels([2, 4])
        self.window.start_run()
        self.wait_idle()
        self.assertEqual(set(self.window.spectra_channel_checks), {2, 4})
        _, labels = self.window.axes.get_legend_handles_labels()
        self.assertIn("ch2", labels)
        self.assertIn("ch4", labels)

        self.window.spectra_channel_checks[2].setChecked(False)
        _, labels = self.window.axes.get_legend_handles_labels()
        self.assertNotIn("ch2", labels)
        self.assertIn("ch4", labels)

    def test_bins_and_scale_controls_affect_the_rendered_histogram(self):
        self.window.channel_select.set_channels([4])
        self.window.start_run()
        self.wait_idle()

        self.window.spectra_bins.setValue(5)
        few_bins_patches = len(self.window.axes.patches)
        self.window.spectra_bins.setValue(200)
        many_bins_patches = len(self.window.axes.patches)
        self.assertGreater(many_bins_patches, few_bins_patches)

        self.assertEqual(self.window.axes.get_yscale(), "linear")
        self.window.spectra_log_y.setChecked(True)
        self.assertEqual(self.window.axes.get_yscale(), "log")

    def test_clear_plot_resets_display_without_touching_saved_data(self):
        self.window.channel_select.set_channels([4])
        self.window.start_run()
        self.wait_idle()
        self.assertTrue((self.directory / "events.csv").exists())

        self.window.clear_spectra()
        self.assertEqual(self.window._spectra_rows, ())
        self.assertEqual(len(self.window.axes.patches), 0)
        self.assertTrue((self.directory / "events.csv").exists())

    def test_open_saved_run_renders_its_data(self):
        self.window.channel_select.set_channels([4])
        self.window.start_run()
        self.wait_idle()
        self.window.clear_spectra()
        self.assertEqual(len(self.window.axes.patches), 0)

        self.window.open_saved(self.directory)
        self.assertTrue(self.window._spectra_rows)
        self.assertGreater(len(self.window.axes.patches), 0)

    def test_import_vendor_file_renders_through_the_same_path(self):
        fixture = (Path(__file__).parent / "fixtures" /
                  "vendor_readable_adc_acq_sample.txt")
        self.window.import_vendor_file(fixture)
        self.assertIn("Imported vendor file", self.window.status.text())
        self.assertEqual(set(self.window.spectra_channel_checks), set(range(64)))
        for channel in range(64):
            if channel not in (4, 5):
                self.window.spectra_channel_checks[channel].setChecked(False)
        _, labels = self.window.axes.get_legend_handles_labels()
        self.assertEqual(set(labels), {"ch4", "ch5"})
        self.assertGreater(len(self.window.axes.patches), 0)

    def test_live_refresh_is_throttled_not_every_poll_tick(self):
        # A fake worker that always reports "still running", decoupled from
        # real background-thread timing, so the throttle count is exact and
        # not a race against how fast the simulator actually completes.
        class _FakeSnapshot:
            rows = ()
            event = None
            outcome = None

        class _FakeWorker:
            is_alive = True

            def snapshot(self):
                return _FakeSnapshot()

        (self.directory).mkdir(parents=True, exist_ok=True)
        csv_path = self.directory / "events.csv"
        csv_path.write_text("batch,event,channel,hg,lg\n")
        self.window._active_directory = self.directory
        self.window._live_csv_path = csv_path
        self.window._live_refresh_tick = 0
        self.window.worker = _FakeWorker()
        try:
            with patch("radioroc.gui.acquisition_window._read_live_events",
                      return_value=()) as reread:
                ticks = self.window._LIVE_REFRESH_EVERY_TICKS
                for _ in range(3 * ticks - 1):
                    self.window.poll_worker()
                self.assertEqual(reread.call_count, 2)
        finally:
            self.window.worker = None

    def test_close_failure_remains_visible(self):
        from radioroc.application.acquisition_worker import AcquisitionWorker
        from radioroc.transport.acquisition_simulator import create_acquisition_simulator

        class BrokenClose:
            def __init__(self, operation, simulation):
                self.inner = create_acquisition_simulator(operation, simulation)

            def __enter__(self):
                return self.inner.__enter__()

            def __exit__(self, *args):
                self.inner.__exit__(*args)
                raise OSError("injected session close failure")

        self.window.worker_factory = lambda op, sim: AcquisitionWorker(op, sim, session_factory=BrokenClose)
        self.window.show()
        self.window.start_run()
        self.window.close()
        self.wait_idle()
        self.assertTrue(self.window.isVisible())
        self.assertIn("Review errors", self.window.status.text())
        self.assertIn("injected session close failure", self.window.details.toPlainText())


if __name__ == "__main__":
    unittest.main()
