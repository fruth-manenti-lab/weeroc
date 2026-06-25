from __future__ import annotations

import glob
import importlib
import os
import sys


MODULES = [
    "numpy",
    "pandas",
    "scipy",
    "matplotlib",
    "serial",
    "pyvisa",
    "usb",
    "yaml",
    "PyQt6",
]


def check_imports() -> None:
    print(sys.version)
    for name in MODULES:
        try:
            importlib.import_module(name)
            print(f"{name}: OK")
        except Exception as exc:
            print(f"{name}: {type(exc).__name__}: {exc}")


def check_ftd2xx() -> None:
    try:
        import ftd2xx as ftd

        print("ftd2xx: Python import OK")
        print(f"ftd2xx device count: {ftd.createDeviceInfoList()}")
        print(f"ftd2xx devices: {ftd.listDevices()}")
    except Exception as exc:
        print(f"ftd2xx: {type(exc).__name__}: {exc}")
        print("ftd2xx note: macOS still needs FTDI's native libftd2xx.dylib.")


def check_serial_ports() -> None:
    ports = sorted(glob.glob("/dev/cu.usbserial-*"))
    print(f"serial ports: {ports or 'none'}")


def main() -> None:
    print(f"RADIOROC_WORKSPACE={os.environ.get('RADIOROC_WORKSPACE', '')}")
    print(f"RADIOROC_EXTRACTED={os.environ.get('RADIOROC_EXTRACTED', '')}")
    check_imports()
    check_ftd2xx()
    check_serial_ports()


if __name__ == "__main__":
    main()
