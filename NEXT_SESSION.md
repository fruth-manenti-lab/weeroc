# RADIOROC 29 — Extend the register-mapping method to "Main", or hardware follow-up

Continuing on `feat/desktop-hardware-threshold`. Working tree clean once this
handoff is committed. Read `AGENTS.md` first for delegation, recording, and
offline-testing discipline; the standing per-action hardware-authorization
rule applies as always (RADIOROC 27/28's operator granted hardware access
directly, in-conversation, for that session only — that doesn't carry over
to a new chat by default).

## What RADIOROC 28 did

See `IMPLEMENTATION_STATUS.md`'s RADIOROC 28 entry for full detail. Summary:

1. Fixed a real CI bug that had failed every single push since RADIOROC 26:
   `tests/test_main_window.py` imported PySide6 unconditionally instead of
   guarding it like every other GUI test file, so CI's test *loader*
   couldn't even import the module. Reproduced the exact CI steps end-to-end
   in a clean venv before fixing, to confirm the real cause.
2. Built the raw-register view (`F06`) suggested as RADIOROC 27's next task:
   `src/radioroc/application/raw_registers.py` (generic
   `(add, subadd, byte)` read-all/write-one, batched through the existing
   multi-row FIFO), two new `ConnectionWorker` commands, and a new
   `RawRegisterPanel` GUI sub-tab ("Registers", fifth on the ASIC-config
   page). Deliberately narrow (no vendor read/write-all-beyond-loaded,
   default reset, or config import/export/drag-drop).
3. Fixed a SIGSEGV that resurfaced deterministically (3/3) once this
   session's new tests shifted GC timing: swept the remaining
   `deleteLater()` gap RADIOROC 26 had explicitly flagged as pending
   (`test_channel_config_panel.py` and this session's own new panel test
   files never called `deleteLater()` on the bare `QWidget`s they
   construct).
4. Found and fixed a real, empirically-confirmed (not theoretical) async
   race: all four channel-config-family panels (`ChannelConfigPanel`,
   `InputDacGridPanel`, `ProbesMasksPanel`, `ThresholdCalibrationPanel`)
   called `show_snapshot()` the instant an operation was submitted, before
   the worker thread had any chance to process it — 0/50 correct against a
   real `ConnectionWorker` with a faithful fake transport, confirmed before
   fixing. Fixed all four with a submit-then-poll pattern.

   **Correction to RADIOROC 27's own handoff:** that document guessed these
   four panels were "probably fine" based on reading the code, since their
   Apply buttons aren't gated on connection state the way the scan windows'
   run buttons are. That reasoning was about a different failure mode and
   missed this one entirely — a reminder that "code inspection suggests
   it's fine" is not the same as testing it, and RADIOROC 28 found this only
   because it happened to build a fifth panel with the same shape and
   noticed the pattern was suspect.

286/286 offline tests, 5 clean full-suite runs of `tools/check_development.py`.

## What's explicitly still missing from the ASIC-config page

Only the vendor app's "Main" sub-tab (`F02`: trigger preamp gain/compensation,
HG/LG gain and shaping, T1/T2/TQ thresholds, delay code/slope, test-input
routing) remains unbuilt. Its controls are a mix of per-channel and
shared/common (`add >= 64`) registers, and the "common block" register
semantics weren't as cleanly self-describing in the vendor bytecode's
embedded strings as the per-channel ones were (see RADIOROC 27's entry for
what was tried). The reverse-engineering *method* is proven and repeatable
(`strings` on the raw `.pyc`, or `marshal.loads()` + `dis` for anything not
literally spelled out as plain text) — this needs someone to spend more time
on the "Main" tab specifically, not a new technique. Don't guess at these
registers without doing that work first.

## Suggested next task (pick with judgment, same as always)

1. **Extend the register-mapping technique to "Main"** — the natural next
   step now that `F06`'s raw register view exists: it can act as a live
   diagnostic aid for this work too (read a suspected register, compare
   against what the vendor bytecode's strings claim). Disassemble more of
   `radioroc2UI.pyc`'s `setupUi` (or `strings` it more thoroughly)
   specifically around the `add >= 64` common-block registers and the
   Main-tab widget property assignments, to pin down trigger preamp
   gain/compensation, HG/LG gain/shaping, T1/T2/TQ threshold DACs, and delay
   code/slope with the same three-way-cross-check rigor RADIOROC 27 used for
   Threshold calibration.
2. **Full vendor `F06` parity, if there's appetite for it:** `read/write
   all` beyond the currently-loaded table, `default reset`, config
   import/save/drag-drop, embedded field help. RADIOROC 28 built the narrow
   version deliberately; this is the natural continuation if wanted, not a
   gap that needs fixing.
3. **Hardware follow-up:** none of RADIOROC 27/28's new panels (input DAC
   grid, mask grids, threshold calibration grid, raw registers) have been
   validated against the *real* board yet — only the pre-existing S-curve/
   Hold-scan/Threshold-scan GUI paths have real hardware evidence. If the
   operator is present with the board connected, exercising these for real
   (not just the offline/fake-transport tests) would close that gap, and
   is a good candidate to actually watch for more of the kind of bug
   RADIOROC 28 found (that one was found by careful code reading + an
   empirical repro script, not a real board — a real board wouldn't have
   caught the async-race bug either, since faked or real, the timing issue
   is about GUI polling, not about what the hardware does).
4. Anything else reasonable from `CROSS_PLATFORM_REBUILD_PLAN.md` §3 that
   doesn't need new register mappings.

## Standing discipline (unchanged)

Offline tests and fake transports only unless the operator is present and
explicitly authorizes a specific hardware action, per-action (a grant given
in one conversation is for that conversation only — don't assume it
forward). Never run `radioroc_env_check.py` as an offline check (it
enumerates hardware through D2XX even when you don't intend to use it). Run
`tools/check_development.py` after every meaningful change — after touching
anything connection/threading-related, don't just check it prints "OK": wrap
it in a hard `timeout` and confirm the process itself exits (RADIOROC 27/28
both found real hang-at-exit bugs that would have looked like a pass under
a naive "did it print OK" check). When a panel or window submits work to
`ConnectionWorker` and then reads a result, remember that submission is
asynchronous — verify with a real (or faithfully fake) transport under
timing, not just a synchronous test double, before trusting that the
result shown is fresh. Delegate bounded, well-specified implementation/test
work to subagents per `AGENTS.md`; keep shared contracts, uncertain hardware
reasoning, and integration for the lead. Record what you did, what's next,
and any real findings in `IMPLEMENTATION_STATUS.md` and a fresh
`NEXT_SESSION.md` before you stop.
