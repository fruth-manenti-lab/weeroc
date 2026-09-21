"""Launch the optional threshold, hold-scan and connection desktop.

Threshold and hold-scan are two independent workflow verticals (each owns its
own worker/session lifecycle); this module hosts both as tabs of one window
rather than unifying them into a shared shell. See
CROSS_PLATFORM_REBUILD_PLAN.md for that longer-term direction.
"""

import argparse


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="RADIOROC desktop: threshold/hold-scan simulation and hardware connection")
    parser.parse_args(argv)
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QTabWidget
        from .threshold_window import ThresholdWindow
        from .hold_scan_window import HoldScanWindow
    except ModuleNotFoundError as exc:
        if exc.name and (exc.name.startswith("PySide6") or exc.name.startswith("matplotlib")):
            parser.exit(1, "Desktop dependencies are missing. Install radioroc-tools[gui].\n")
        raise
    app = QApplication([])
    app.setApplicationName("RADIOROC")
    tabs = QTabWidget()
    tabs.setWindowTitle("RADIOROC")
    tabs.resize(1200, 860)
    # Each workflow window owns its own timers/worker/connection-worker
    # lifecycle; embedding the whole window as a tab page (rather than only
    # its central widget) keeps that lifecycle and its own closeEvent intact.
    threshold_window = ThresholdWindow()
    hold_scan_window = HoldScanWindow()
    tabs.addTab(threshold_window, "Threshold")
    tabs.addTab(hold_scan_window, "Hold Scan")

    def busy():
        return any(sub_window.worker is not None or sub_window.connection_worker is not None
                   for sub_window in (threshold_window, hold_scan_window))

    finish_timer = QTimer()
    finish_timer.setInterval(150)

    def finish_when_idle():
        if not busy():
            finish_timer.stop()
            app.quit()

    finish_timer.timeout.connect(finish_when_idle)

    def closeEvent(event):
        # Give each workflow window's own closeEvent a chance to cancel an
        # in-flight job or disconnect hardware before the shell exits; poll
        # until both are idle, then actually quit.
        for sub_window in (threshold_window, hold_scan_window):
            if sub_window.worker is not None or sub_window.connection_worker is not None:
                sub_window.close()
        if busy():
            finish_timer.start()
            event.ignore()
        else:
            event.accept()

    tabs.closeEvent = closeEvent
    tabs.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
