# RADIOROC 22 — Next hardware slice: Stage C/D, or remaining deferred items

Read `AGENTS.md`, `IMPLEMENTATION_STATUS.md`, `DEVELOPMENT.md`,
`CROSS_PLATFORM_REBUILD_PLAN.md`, `docs/hardware/stage_b_completion.md`, and
`docs/hardware/stage_c_io_sync_validation.md`. The preceding chat is
**RADIOROC 21 — First physical validation of the GUI channel-config panel
(PASSED)**.

Branch: `feat/desktop-hardware-threshold`, version `0.5.0`. Verify current
commit and working tree.

**RADIOROC 17-21 summary — input DAC / TQ mask feature is now complete and
evidenced end to end:** register mapping recovered from vendor bytecode
(17); CLI wiring via a shared `radioroc.application.channel_config` core
(18); first physical validation, CLI path (19, passed); GUI wiring reusing
the same shared core, catching and fixing a real bug (the GUI worker never
loaded the ASIC config table) along the way (20); first physical validation,
GUI path (21, passed — same 65-rows/0-mismatches result as the CLI run).
Both entry points now have independent hardware evidence. Nothing further
is planned for this feature unless new gaps turn up.

**Hardware state (Stage C, unchanged since RADIOROC 16):** IO1 (mux index 5)
confirmed at ~10-13ms period, ~1.44V amplitude under 50-ohm termination.
Stage D (pulse generator, signal injection) hasn't started.

**Still open from earlier sessions:**
1. Item 7 — persistent defaults/FPGA init. Code exists but makes changes
   with no automatic restoration; explicitly deferred by the operator's own
   choice (RADIOROC 14), not attempted since.
2. TQ mask and input DAC now have code and hardware evidence, but per-channel
   input DAC *enable* specifically was only wired/tested via impedance and
   value so far — the enable bit itself hasn't been physically exercised in
   isolation (low risk, same mechanism, but not literally run).
3. Non-hardware backlog: branch/CI review before publishing, Windows-parity
   inventory expansion (both already queued from early sessions).

Next bounded task: with the designated operator, choose a direction:

1. **Resume the Stage C/D hardware track**: extend Stage C (pulse
   width/rise-time on IO1, an untermination-corrected amplitude, or probing
   io0/io2-io4/`IO_FPGA6`/`IO_FPGA7`) or move to Stage D if a pulse generator
   is available — bigger step, needs an attenuator, injects a signal into
   the ASIC, needs its own setup review before authorization (this is what
   the historical 2026-06-26 logbook workflow actually built toward: IO1
   triggering a generator for real S-curve/hold-scan signal response).
2. **Close the small input-DAC-enable gap** if useful: a quick bounded card
   (CLI or GUI, `--restore --verify`) exercising `--input-dac-enable`
   specifically.
3. **Persistent defaults/FPGA init (item 7)**: if the operator wants this
   done now, it needs its own deliberate framing (what state to apply, how
   to independently confirm the resulting persistent state, explicit
   sign-off that persistence is intended) — not a routine variation.
4. **Non-hardware work**: branch/CI review, or Windows-parity inventory
   expansion.

Whatever is chosen, follow the RADIOROC 09-21 discipline: confirm
preconditions before any hardware access, get an explicit authorization
statement (operator, host, UTC start time, exact scope) for the exact
action, reuse/extend an existing bounded, evidenced harness where one fits,
and stop immediately on any error, fault, or mismatch rather than retrying
or improvising.

Acceptance: the chosen direction is authorized/scoped, executed, and its
outcome recorded with the same evidence rigor as RADIOROC 09-21 in both
`IMPLEMENTATION_STATUS.md` and this file, along with the next task. No
ASIC/FIFO access, verifier, scan, persistent configuration write (without
explicit authorization as such), defaults, repair, power-cycle, signal
injection, or detector connection beyond what is explicitly authorized for
that exact action; no push or change to `main`.
