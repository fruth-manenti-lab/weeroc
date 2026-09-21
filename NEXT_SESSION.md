# RADIOROC 27 — Raw register view, or hardware validation if the operator is present

Continuing on `feat/desktop-hardware-threshold`, last commit `e0ef06c`. Working
tree is clean; nothing uncommitted. Read `AGENTS.md` first for delegation,
recording, and offline-testing discipline — it applies in full this time
(the previous session's overnight hardware relaxation was scoped to that one
night only and does not carry over).

## What the last session (RADIOROC 26) did

Two commits, both offline, both with passing tests and screenshotted GUI
review — see `IMPLEMENTATION_STATUS.md`'s RADIOROC 26 entry for full detail:

1. Committed the shared-shell refactor (`MainWindow`, `ConnectionPanel`,
   `ChannelConfigPanel`) that a prior session had left uncommitted, and fixed
   a real intermittent SIGSEGV in GUI test teardown
   (`QObject::killTimer: Timers cannot be stopped from another thread`,
   root-caused to `window.close()` without `window.deleteLater()`).
2. Extended `ChannelConfigOperation`/`apply_channel_config`
   (`src/radioroc/application/channel_config.py`) with per-channel
   independent DAC values and mask states, then added two new ASIC-config
   sub-tabs to `MainWindow` matching the vendor app's tab structure: an
   "input DAC" 64-channel grid (`gui/input_dac_grid_panel.py`) and the
   T1/T2/TQ mask side of "Probes/Masks" (`gui/probes_masks_panel.py`,
   analog/digital probe *routing* deliberately left out — no backend support
   exists for that yet).

260/260 offline tests passing, 3 clean full-suite runs of
`tools/check_development.py` on `.conda-radioroc`.

## What's explicitly still missing from the ASIC-config page

The vendor app's "ASIC config." area has four sub-tabs; only two are built.
The other two need real work before they can be built at all, not just GUI
effort:

- **"Main"** (`F02`: trigger preamp gain/compensation, HG/LG gain and
  shaping, T1/T2/TQ thresholds, delay code/slope, test-input routing) — no
  register mapping exists in `radioroc_client.py` for most of these yet.
- **"Threshold calibration"** (`F04`: per-channel T1/T2 calibration DAC
  trims) — same gap, no register mapping in the codebase at all.

Building either by guessing at register layout from the vendor screenshots
alone would be exactly the kind of uncertain hardware reasoning this project
reserves for the lead working carefully with real documentation/vendor
comparison, not for a fast unsupervised pass — see the "Probes/Masks" probe
routing controls, skipped for the identical reason. Don't attempt these
without either real register documentation or the operator's input.

## Suggested next task (pick with judgment, same as always)

1. **Raw register view (`F06`)** — a well-scoped, purely mechanical next
   step: "CSV defaults and generic I2C primitives exist" per
   `CROSS_PLATFORM_REBUILD_PLAN.md`'s feature table, meaning this is generic
   register access (any `(add, subadd)`, arbitrary binary/hex data), not
   ASIC-semantic interpretation — no hardware-reasoning risk like Main/
   Threshold-calibration above. Start narrow: a panel listing the currently
   loaded `device.i2c_rows` (add/subadd/data, hex and binary side by side),
   with the ability to pick one row, edit its raw bits, and write/verify it
   through the device's existing `read_register_bits`/`write_register`
   (see how `ChannelConfigPanel`/the two new grid panels already use these).
   Full vendor parity (`read/write all`, `default reset`, config
   import/save/drag-drop, embedded field help) is explicitly more than one
   bounded task — do the narrow version first, note what's scoped out the
   same way this session did for the mask grids.
2. **Physically validate the S-curve GUI path** — only if the operator is
   present and grants fresh, per-action hardware authorization (the standing
   `AGENTS.md` rule, not last session's one-night exception). Otherwise
   leave this for a session where they are.
3. Anything else reasonable from `CROSS_PLATFORM_REBUILD_PLAN.md` §3 that
   doesn't need new register mappings or hardware.

## Standing discipline (unchanged)

Offline tests and fake transports only unless the operator is present and
explicitly authorizes a specific hardware action. Never run
`radioroc_env_check.py` as an offline check (it enumerates hardware through
D2XX even when you don't intend to use it). Run `tools/check_development.py`
after every meaningful change — stress-test (5-10 runs) after any change
that touches GUI test teardown or threading, the way RADIOROC 26 did for the
SIGSEGV fix. Delegate bounded, well-specified implementation/test work to
subagents per `AGENTS.md`; keep shared contracts (like the
`ChannelConfigOperation` extension this session did directly) and
integration for the lead. Record what you did, what's next, and any real
findings in `IMPLEMENTATION_STATUS.md` and a fresh `NEXT_SESSION.md` before
you stop.
