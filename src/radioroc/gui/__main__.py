"""Launch the optional simulation desktop."""

import argparse


def main(argv=None):
    parser = argparse.ArgumentParser(description="RADIOROC desktop threshold simulation")
    parser.parse_args(argv)
    try:
        from PySide6.QtWidgets import QApplication
        from .threshold_window import ThresholdWindow
    except ModuleNotFoundError as exc:
        if exc.name and (exc.name.startswith("PySide6") or exc.name.startswith("matplotlib")):
            parser.exit(1, "Desktop dependencies are missing. Install radioroc-tools[gui].\n")
        raise
    app = QApplication([])
    app.setApplicationName("RADIOROC")
    window = ThresholdWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
