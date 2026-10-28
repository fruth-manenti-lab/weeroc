# Installing the RADIOROC app

Written for students and lab users who want to run the RADIOROC desktop app
(`radioroc-desktop`) and the `radioroc` command-line tools. You do not need the
WEEROC Windows installer.

## What was tested

| Platform | Status |
| --- | --- |
| macOS (lab Mac) | Used with the real board. |
| Raspberry Pi / Debian / Ubuntu | Board seen as `/dev/ttyUSB0`; permission steps untested (see `linux_usb_permissions.md`). |
| Windows | Not tested. The package is pure Python, so the install steps should work, but the COM port and driver behaviour are unverified. |

You can install and try everything in **Simulation** mode with no board.

## 1. Requirements

- Python **3.11 or newer** (CI uses 3.11 and 3.13). Check with `python3 --version`.
- Git, to download the code.
- For real measurements: the RADIOROC 2 board, its **external 5 V supply**
  (USB power alone gives garbage replies), and a USB cable. Plug the board
  directly into the computer, not through a hub.

## 2. Get the code

```bash
git clone git@github.com:fruth-manenti-lab/weeroc.git
cd weeroc
```

(Use the HTTPS URL if you have no SSH key set up.)

## 3. Create an environment and install

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e '.[gui,analysis]'
```

Extras:

- `gui`: the desktop app (PySide6 and Matplotlib).
- `analysis`: plotting for the command-line tools.
- `dev`: test and build tools, only needed if you change the code.

For the command-line tools only, `python -m pip install -e .` is enough.

## 4. Check the install (no hardware needed)

```bash
radioroc --help
radioroc-desktop
```

The desktop window should open. Choose **Simulation** and run a threshold scan.
Simulated results are labelled **SIMULATION** throughout. Nothing here touches
the board.

Developers can also run `python tools/check_development.py`.

## 5. Connect the board

1. Power the board from its external 5 V supply, then connect USB.
2. List candidate ports without opening them:

   ```bash
   radioroc ports --json
   ```

   The board has an FTDI chip (USB ID `0403:6010`) and appears as **two** serial
   ports. The control port is the lower-numbered one.

   | OS | Control port |
   | --- | --- |
   | macOS | `/dev/cu.usbserial-RD3_320` (the `_321` one is the second port) |
   | Linux | `/dev/ttyUSB0` |
   | Windows | A `COM` port; the lower-numbered of the pair (untested) |

3. **Linux only:** add yourself to the serial group, then log out and in:

   ```bash
   sudo usermod -aG dialout $USER
   ```

   Details and an optional udev rule are in
   [linux_usb_permissions.md](linux_usb_permissions.md).
4. In the app choose **Hardware connection**, select the control port, and
   press **Connect**. Or from the command line:

   ```bash
   python scripts/radioroc_check_connection.py --help
   ```

Only one program can use the board at a time. Close the vendor app and any other
RADIOROC tool before connecting. Commands that change the board are dry-run
unless you add `--execute`, so check cabling first.

## 6. Where results go

Runs are saved under `radioroc_runs/` in the folder you launch from. This folder
holds measured data: do not delete it, and it is not committed to git.

## Updating

```bash
git pull
python -m pip install -e '.[gui,analysis]'
```

## Troubleshooting

- **`radioroc-desktop: command not found`**: the environment is not active.
  Run `source .venv/bin/activate`, or install with the `gui` extra.
- **`No module named PySide6`**: reinstall with `'.[gui]'`.
- **No port listed**: try another cable or a direct USB port (not a hub), and
  check the 5 V supply is on.
- **Permission denied on the port (Linux)**: see step 5.3.
- **Port busy / lock error**: another program holds the board. Close it. Leave
  files in `~/.radioroc/locks` alone.
- **Garbage or no replies**: the external 5 V supply is probably off.

For the first measurements, follow [bench_runbook.md](bench_runbook.md).
