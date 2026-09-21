# RADIOROC 28 — Raw register view, or extend the register-mapping method to "Main"

Continuing on `feat/desktop-hardware-threshold`. Working tree clean once this
handoff is committed. Read `AGENTS.md` first for delegation, recording, and
offline-testing discipline; the standing per-action hardware-authorization
rule applies as always (this session's operator was present and granted
hardware access directly, in-conversation — that authorization doesn't carry
over to a new chat by default).

## What this session (RADIOROC 27) did

See `IMPLEMENTATION_STATUS.md`'s RADIOROC 27 entry for full detail. Summary:

1. Recovered the Threshold-calibration T1/T2 trim-DAC register mapping by
   disassembling the vendor Windows app's own shipped Python bytecode
   (`local_artifacts/extracted/RadiorocUI_2_2_0_5.exe_extracted/` — genuine
   CPython 3.13, readable via `marshal`+`dis`, no decompiler needed), cross-
   checked three independent ways before trusting it. Built
   `RadiorocDevice.set_calibration_dac_for_channel`, extended
   `ChannelConfigOperation` with per-channel dict fields, and shipped a
   fourth ASIC-config sub-tab (`gui/threshold_calibration_panel.py`).
2. Physically validated the S-curve GUI path on real hardware for the first
   time (RADIOROC 25 left this pending) — `status: completed`, `cleanup:
   restored`, `verification: passed`, curve shape matching an earlier same-day
   CLI diagnostic run closely. Evidence local under `radioroc_runs/hardware/`
   (uncommitted, per policy).
3. Found and fixed two real bugs surfaced by that hardware run: (a)
   `MainWindow`'s embedded scan windows never learned the shared connection
   reached "connected" (their run buttons stayed disabled forever) — fixed by
   wiring `connection_panel.status_changed` to each scan window's
   `poll_connection_worker`; (b) `tests/test_main_window.py`'s `_FakeSession`
   fixture didn't match the session contract every other GUI test fixture
   uses, silently hanging the test process at interpreter exit the moment
   anything actually connected through it (nothing had, until this session's
   new regression test tried to).

269/269 offline tests, 3 clean full-suite runs of `tools/check_development.py`
on `.conda-radioroc`, confirmed via a hard-timeout wrapper that the process
itself now exits cleanly (not just that pytest/unittest printed "OK").

## What's explicitly still missing from the ASIC-config page

Only the vendor app's "Main" sub-tab (`F02`: trigger preamp gain/compensation,
HG/LG gain and shaping, T1/T2/TQ thresholds, delay code/slope, test-input
routing) remains unbuilt. Unlike Threshold-calibration, this session did not
fully pin down its register addresses in the time available — its controls
are a mix of per-channel and shared/common (`add >= 64`) registers, and the
"common block" register semantics weren't as cleanly self-describing in the
vendor bytecode's embedded strings as the per-channel ones were. The
reverse-engineering *method* is proven and repeatable (see RADIOROC 27's
entry for the exact technique: `strings` on the raw `.pyc`, or
`marshal.loads()` + `dis` for anything not literally spelled out as plain
text) — a future session with more time budget could extend it to "Main"
specifically. Don't guess at these registers without doing that work first;
see the Probes/Masks routing controls and (until this session) Threshold
calibration for what got deliberately deferred for the identical reason.

## Suggested next task (pick with judgment, same as always)

1. **Raw register view (`F06`)** — a well-scoped, purely mechanical next
   step, unaffected by the "Main" gap above since it's generic register
   access (any `(add, subadd)`, arbitrary binary/hex data), not ASIC-semantic
   interpretation. Start narrow: a panel listing the currently loaded
   `device.i2c_rows` (add/subadd/data, hex and binary side by side), with the
   ability to pick one row, edit its raw bits, and write/verify it through
   the device's existing `read_register_bits`/`write_register`. Full vendor
   parity (`read/write all`, `default reset`, config import/save/drag-drop,
   embedded field help) is more than one bounded task — do the narrow
   version first.
2. **Extend the register-mapping technique to "Main"** — pick up where this
   session left off: disassemble more of `radioroc2UI.pyc`'s `setupUi`
   (or `strings` it more thoroughly) specifically around the `add >= 64`
   common-block registers and the Main-tab widget property assignments, to
   pin down trigger preamp gain/compensation, HG/LG gain/shaping, T1/T2/TQ
   threshold DACs, and delay code/slope with the same three-way-cross-check
   rigor RADIOROC 27 used for Threshold calibration.
3. **A hardware follow-up flagged but not checked this session:** verify
   whether the input-DAC-grid/mask-grid/threshold-calibration-grid panels
   (built earlier the same day as RADIOROC 27, never yet hardware-validated)
   have the same "shared connection state never reaches an embedded control"
   failure class the S-curve run just found and fixed. Code inspection
   suggests they're fine (their Apply buttons aren't gated on connection
   state at all, unlike the scan windows' run buttons — they just fail
   gracefully if not actually connected), but that's reasoning from reading
   the code, not from physically exercising it; if the operator is present
   with the board connected, a quick real click-through would settle it
   properly.
4. Anything else reasonable from `CROSS_PLATFORM_REBUILD_PLAN.md` §3 that
   doesn't need new register mappings.

## Standing discipline (unchanged)

Offline tests and fake transports only unless the operator is present and
explicitly authorizes a specific hardware action, per-action (this session's
grant was given directly in conversation, for this session only — don't
assume it forward). Never run `radioroc_env_check.py` as an offline check (it
enumerates hardware through D2XX even when you don't intend to use it). Run
`tools/check_development.py` after every meaningful change — after touching
anything connection/threading-related, don't just check it prints "OK": wrap
it in a hard `timeout` and confirm the process itself exits (this session
found a real hang-at-exit bug that would have looked like a pass under a
naive "did it print OK" check). Delegate bounded, well-specified
implementation/test work to subagents per `AGENTS.md`; keep shared contracts,
uncertain hardware reasoning, and integration for the lead. Record what you
did, what's next, and any real findings in `IMPLEMENTATION_STATUS.md` and a
fresh `NEXT_SESSION.md` before you stop.
