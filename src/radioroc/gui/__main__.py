"""Launch the RADIOROC desktop: one shared connection over ASIC config and
the threshold/hold-scan/S-curve Calibration workflows.

See ``radioroc.gui.main_window.MainWindow`` for the shell itself.
"""

import argparse


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="RADIOROC desktop: shared connection, ASIC config, and calibration workflows")
    parser.parse_args(argv)
    try:
        from PySide6.QtWidgets import QApplication
        from .main_window import MainWindow
    except ModuleNotFoundError as exc:
        if exc.name and (exc.name.startswith("PySide6") or exc.name.startswith("matplotlib")):
            parser.exit(1, "Desktop dependencies are missing. Install radioroc-tools[gui].\n")
        raise
    app = QApplication([])
    app.setApplicationName("RADIOROC")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
