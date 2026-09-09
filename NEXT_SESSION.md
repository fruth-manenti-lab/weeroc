# Next session: threshold-scan job lifecycle

Start a fresh chat now that transport/ownership is committed and tested. Copy
the prompt below. The implementation checkpoint is `6c44092` on
`feat/transport-ownership`; its following documentation commit contains this handoff.

---

Read `AGENTS.md`, `IMPLEMENTATION_STATUS.md`, `DEVELOPMENT.md` and Delivery 3 in
`CROSS_PLATFORM_REBUILD_PLAN.md`. Continue from `feat/transport-ownership` in a
new local feature branch. Keep this session limited to a shared job lifecycle
for the existing threshold scan, usable by the CLI and a future desktop UI.

First inspect the current threshold implementation, then define the small job
API and acceptance criteria before editing. Preserve existing CLI arguments,
scan settings and successful measurement behavior. Introduce validated operation
configuration, structured progress, cooperative cancellation, whole-job
serialization and durable partial results/metadata. CLI and API must use the
same runner. Make this workflow's dry-run genuinely offline.

Acceptance checks:

- The API and existing threshold CLI exercise the same operation.
- Fake-transport success produces existing result values plus explicit terminal
  status; progress identifies completed points.
- Cancellation, disconnect and cleanup failure preserve completed points and
  truthful run/cleanup status. Restore only state actually captured, and report
  restoration failure without masking the original error.
- A second job on the same session is rejected or queued by an explicit policy;
  it cannot interleave with a running scan. Validate cross-process board locking
  remains intact without duplicating the transport layer.
- Dry-run does not open serial or require connected hardware.
- Relevant offline tests, existing development checks and installed-wheel smoke
  checks pass. Update status/handoff and commit the bounded result locally.

Exclude GUI work, acquisition/autocalibration migration, complete Windows parity,
automatic device selection and unrelated refactoring. Record discoveries as
follow-up tasks. Preserve ignored experiment folders and other local results.
Do not push or rewrite main as part of this task.

The board last answered status 5 at `/dev/cu.usbserial-RD3_320`; both interfaces
share USB serial `RD3_32`. It is powered with no SiPM or pulse generator attached,
and was closed after the last check. Keep hardware checks optional and bounded.
Tell me if a proposed validation needs a sensor, pulse generator or different
wiring, with the specific check it enables.

You may delegate bounded offline test/review work to a smaller agent once the
shared contract is defined. One editor owns the core API; only the lead accesses
hardware. Recommend the next chat boundary when this milestone is committed.

---

Use another fresh chat for the desktop shell after this job API is stable.
A new chat is also appropriate after a major change of objective; first save
any unfinished work as an explicitly labelled checkpoint with remaining checks.
