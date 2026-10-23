# Linux USB permissions for the RADIOROC board (Debian and Ubuntu)

This page helps a student on Debian or Ubuntu get the app to open the board.

**What was tested.** The board was used on a Raspberry Pi as `/dev/ttyUSB0`
(see RADIOROC 24 in `IMPLEMENTATION_STATUS.md`). That run recorded the port
name only. It did not test the group, udev or ModemManager steps below. Those
are standard Linux advice and were **not tested here**.

## How the board appears

- The board has an FTDI chip with USB ID `0403:6010`.
- It shows up as two serial ports (two interfaces of one chip).
- The control port is the lower-numbered one. On Linux this is
  `/dev/ttyUSB0` (the second is `/dev/ttyUSB1`). On the lab Mac it is
  `/dev/cu.usbserial-RD3_320`, and `..._321` is the second one.
- The app finds candidates by USB ID with `src/radioroc/transport/discovery.py`.
  It does not open them to do so.
- `docs/bench_runbook.md` names the Mac control port. It does not describe Linux.
- The board also needs its external 5 V supply. USB power alone gave garbage
  replies on the Pi run.

## Give your user access (standard advice, not tested here)

```bash
sudo usermod -aG dialout $USER
```

Then log out and log in again. Check with `groups`: it must list `dialout`.

## Optional udev rule (standard advice, not tested here)

Create `/etc/udev/rules.d/99-radioroc.rules` with this line:

```text
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6010", MODE="0660", GROUP="dialout"
```

Reload and re-plug the board:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

## ModemManager and brltty (standard advice, not tested here)

These services can grab FTDI ports and make them busy. If the port opens and
then fails, remove or mask them:

```bash
sudo systemctl mask --now ModemManager
sudo apt remove brltty
```

## Check that the board is visible

```bash
ls -l /dev/ttyUSB*
dmesg | tail
python scripts/radioroc_list_ports.py
```

- `ls -l` should show group `dialout` and mode `crw-rw----`.
- `dmesg | tail` should show an FTDI device attached as `ttyUSB0` and `ttyUSB1`.
- `scripts/radioroc_list_ports.py` is read-only. It lists candidates with USB ID
  `0403:6010` and does not open them. Choose the port yourself, and confirm
  with a status reply before any scan.

## Rules for the bench

- Only one program may own the board at a time. Close the app, scripts and any
  serial terminal before you start another.
- Keep the board on its own USB port, not a shared hub. Hub sharing is
  suspected as a cause of board hangs, and a direct port stopped them.
