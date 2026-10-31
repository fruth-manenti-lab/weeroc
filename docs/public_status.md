# Public project status

This page states what the repository demonstrates today and where its limits
are. It is intentionally shorter than `IMPLEMENTATION_STATUS.md`, which is the
detailed engineering record.

## Verified on hardware

- USB serial communication with the lab's RADIOROC 2 evaluation board on macOS
- FPGA status reads and ASIC slow-control configuration
- ADC acquisition, threshold scans, S-curves and hold scans
- saved metadata and events that can be reopened without the board
- operator-run tests involving an Aim-TTi signal generator, Tektronix
  oscilloscope and Keysight power supply in documented bench sessions

Hardware observations apply to the board, firmware and cabling available to the
lab. They should not be read as a compatibility guarantee for every RADIOROC
revision.

## Verified offline

- more than 700 offline tests in 64 test files
- simulation workflows for acquisition and calibration
- saved-run replay, plotting and analysis
- package and wheel installation checks
- headless desktop checks on Ubuntu 24.04 and macOS 14 in CI
- Python 3.11 and 3.13 in CI

The offline suite never operates real hardware.

## Experimental or incomplete

- Windows installation and COM-port behaviour have not been tested.
- Linux CI verifies the software and simulated desktop, but routine real-board
  operation on Linux is not yet established.
- Some calibration and detector-analysis workflows remain research tools rather
  than polished end-user features.
- The repository records failed measurements and unresolved hardware questions
  where they are scientifically relevant. A clean CI run does not imply that
  every bench configuration is understood.

## AI-assisted bench work

AI agents were used for code development, documentation search, log inspection,
test execution and some instrument-assisted debugging. In documented sessions,
an agent queried or controlled an oscilloscope, signal generator and power
supply after the operator established the physical setup, limits and permitted
actions.

This does **not** mean the system was allowed to operate a lab unattended.
Physical setup, authorization and safety remained human responsibilities, and
the repository's automated CI is entirely offline. The instrument automation
was session-level rather than a packaged tool, and its limits were procedural;
the repository does not contain reusable instrument-control code or a
machine-enforced safety layer for those instruments.

## Evidence

The detailed, dated evidence is kept in:

- [`IMPLEMENTATION_STATUS.md`](../IMPLEMENTATION_STATUS.md)
- [`docs/bench_runbook.md`](bench_runbook.md)
- [`docs/hardware/`](hardware/)
- [`docs/project/SMOKE_TESTS.md`](project/SMOKE_TESTS.md)
- [`logbooks/`](../logbooks/)

These records include failures and open questions as well as successful runs.
