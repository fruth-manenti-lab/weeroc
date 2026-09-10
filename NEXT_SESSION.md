# RADIOROC 05 — Physical threshold restoration checks

RADIOROC 04 implemented the opt-in threshold restoration verifier on
`feat/bare-board-threshold-verification` at `4c6d254`, package version `0.5.0`. Read
`AGENTS.md`, `IMPLEMENTATION_STATUS.md`, `DEVELOPMENT.md` and
`docs/hardware/bare_board_threshold_validation.md`; verify the recorded
implementation checkpoint, branch and working tree before editing.

Delegate bounded code/tests/docs to smaller models (Luna for simple tasks,
Sol/Terra for coding), with focused context and non-overlapping files. The lead
owns hardware reasoning, contracts and integration. Keep token use bounded.

The next task is to review and perform the physical card with the designated
operator. No board was enumerated, opened or scanned in RADIOROC 04. Historical
port names and status word 5 are stale evidence. Desktop hardware Run remains
disabled. Do not infer physical validation from passing fake tests.

The existing threshold CLI now accepts `--verify-restoration`. Default preview
is offline. With `--execute`, one session owner performs the job, cleanup,
independent verification and close. Verification compares measured FPGA 0/1/6
and the exact T1/T2 ASIC snapshot rows under the same job lock. Its ASIC reads
are followed by idle word 60, restoration of the observed post-job word 0, and
FPGA rereads. It never repairs a job mismatch. Word 60 readback semantics remain
unresolved; only its idle write is recorded. The result and metadata.json keep
a separate verification field; CLI close failures remain console evidence.

Acceptance checks:

- Explicitly review the card with the user before any physical scan. Confirm
  operator, powered bare board/no detector or pulser, fresh control port/status,
  intended commands and output paths. Only one designated operator accesses the
  board; agent workers use fakes and never run hardware diagnostics.
- Preview each intended command offline first. Use `--skip-fpga-init`, omit
  `--apply-defaults`, include `--verify-restoration`, and use unique run folders.
- Record T1, T2, cancellation inside a long counter window and cancellation after
  a completed point, including snapshots, comparison, errors and console output.
  The CLI does not expose exact counter-window start; establish phase evidence
  before claiming the inside-window case. Do not infer it from Ctrl-C timing alone.
- Require passing readback and verifier cleanup plus successful job cleanup and
  close. Treat every mismatch, incomplete read, transport/storage/close failure
  as an abort; stop subsequent scans and preserve evidence for review.
- Keep measured data in ignored `radioroc_runs`; do not delete local experiments.
  If equipment or authorization is unavailable, record physical checks pending.
- Record actual hardware state, limitations, completed checks and one next task.
  Commit locally on a bounded branch; do not push or change `main`.

Enabling desktop hardware Run is a separate slice after reviewed physical checks
pass. Acquisition/autocalibration migration, automatic interface detection,
register editing, Windows parity expansion, Linux USB validation and application
bundling remain outside this task.

The preceding chat name is **RADIOROC 04 — Bare-board threshold validation**.
