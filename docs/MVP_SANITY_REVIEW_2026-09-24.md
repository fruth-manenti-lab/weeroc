# Independent plint MVP sanity review — 24 September 2026

Reviewed checkout: `feat/daq-results-gui`, `4435584`. This is a review of
student readiness, not a replacement for the rebuild plan or the MVP directive.
Production source was not changed. The operator authorized tests, opening the
GUI, and equipment access for this review.

**Conclusion: not yet ready for an independent student calibration/acquisition
session.** Several basic paths work, but the actual experiment requirement,
calibration procedure, and saved-data behavior still disagree in important ways.
The passing tests recorded by prior sessions do not cover the cases below.

## Checks and evidence

- Launched the actual desktop on the lab display, then exercised the real
  `MainWindow` with eight simulated channels, three batches of five events,
  saved-run reopening, HG/LG and log-scale controls, and cancellation after data
  arrived. Completion and cancellation preserved data and reported restored cleanup.
- The GUI exercise produced **15 physical events / 120 channel rows**, but both
  the live title and reopened status said **120 events**. The screenshot also
  shows the histogram collapsed into a thin strip on the actual 1024×768 display.
- Ran independent offline reproductions for append metadata loss, calibration
  record validation/integration, and autocalibration cancellation/partial apply.
- Benchmarked the real live-plot refresh path on synthetic eight-channel CSVs.
  At 100,000 events / 800,000 rows (13.6 MB CSV), one synchronous refresh took
  **6.12 seconds**, with process peak RSS approximately **397 MiB**. These are
  measurements on this machine under audit workload, not a hardware throughput
  estimate or a one-hour endurance test.
- The initial sandboxed full test run reported 461 tests and three failures:
  one main-window run-completion timeout and two subcases of process-lock child
  startup timeout. It then remained alive after printing its result; only these
  audit-owned test processes were stopped. The process-lock test independently
  passed outside the sandbox. Final host-environment check is recorded below.
- No RADIOROC app/acquisition process or serial-port owner was present before
  the audit. Opened one board connection through the GUI worker for a status-only
  request on `/dev/ttyUSB0`, without initialization, defaults, or scans. It failed
  visibly: expected 5 response bytes, received 35 malformed bytes. The worker
  closed the connection and reported `state=error`, `port=null`.
- Read the Keysight EDU36311A identity and output states: **channels 1/2/3 all
  OFF (`0,0,0`)**. This agrees with the handoff's unpowered-board state; the
  malformed response is not evidence of a newly introduced board defect.
  No supply setting, output enable, generator setting, or detector bias was changed.
  Query syntax was checked against the manufacturer's
  [programming guide](https://www.keysight.com/us/en/assets/9921-01393/programming-guides/EDU36311A-DC-Power-Supply-Programming-Guide.pdf).
- Both audit GUI instances closed cleanly. Physical coincidence, SiPM calibration,
  and an endurance acquisition were **not** validated by this review.

Local evidence is retained under `radioroc_runs/astra_mvp_audit_20260924/` and
remains ignored/uncommitted. Scripts there are audit reproductions, not supported
production entry points. The GUI reproduction includes a status-only hardware
connection; the data/autocalibration/plot reproductions are offline.
Choose a fresh `ROOT` output directory before repeating the GUI script; its
original output paths already contain the preserved audit runs.

## Findings requiring an explicit decision or fix before student use

### 1. The implemented coincidence is a fixed pair, not any two of 4–8

**Requirement blocker, not a newly demonstrated firmware defect.**
`radioroc_client.py`'s `configure_adc_external_hold` and
`application/acquisition.py:269–277` select and unmask two named channels.
RADIOROC 39's own bench table explicitly confirms the fixed-pair behavior and
rejects a different channel paired with either configured channel.

That is useful progress, but it does not implement the directive's “any two
selected channels.” An OR source or “N triggers in a window” cannot be assumed
to enforce two distinct channels. Do not mark this requirement complete.

There is also a concrete configuration-validation defect even for the fixed-pair
mode: `AcquisitionConfig(channels=[4,5,6,7], trigger_type=1, trigger_source=3,
trigger_source_2=3, trigger_channel=4, trigger_channel_2=4).validate()` succeeds.
The primitive also accepts this and routes the same channel to both slots. A
student-facing distinct-channel mode must reject this self-coincidence setup.
Simply switching the GUI's trigger-type dropdown is insufficient too: source 2
defaults to NORT1. Expose the effective trigger expression so “2 channels
coincidence” cannot be mistaken for a verified distinct-channel selection.

Next: settle supported hardware/firmware semantics and either implement/evidence
the required multiplicity or obtain an explicit experiment-scope decision to use
a fixed pair or another supported scheme. Record its selection bias. The previously
deferred outside-window test remains deferred, not passed; this audit does not
silently reopen or close that operator decision.

### 2. The written gain-calibration step cannot run through Acquisition as described

**High — directly blocks the student procedure.**
`docs/plint_calibration_procedure.md:86–105` instructs the student to enable Ctest
through the channel-config panel and collect HG/LG amplitudes in Acquisition.
The panel has no such Ctest control and Acquisition has no Ctest setup option.
An important distinction: `prepare_trigger_masks(..., use_ctest=False)` in
`application/acquisition.py:266` **leaves existing Ctest bits alone**; it does
not clear them. A separately prepared injection state could therefore work,
but the documented student-facing panel action is absent and the preparation
must be specified and preserved explicitly.

The handoff's proposed Step-4 “plateau values” are threshold-scan **rates**;
they are not the per-channel HG/LG **amplitudes** required by that procedure.
Do not relabel those units or count the amplitude calibration as complete.

Next: provide one supported injected-amplitude workflow, possibly using the
existing hold-scan injection path, and rewrite the student instructions to match.
Distinguish ASIC injection response from optical/SiPM gain characterization.
Acceptance needs measured per-channel amplitudes and units, not equal count rates.

### 3. Step 5 asks for coincidence controls the hold-scan GUI does not expose

**High — next handoff task is not executable as written.**
`hold_scan_window.py:192–207` exposes the first trigger source/type only;
`operation()` at lines 630–653 omits `trigger_source_2` and `trigger_channel_2`.
The resulting configuration retains source 2 = NORT1 and channel 2 = 0.
The procedure and `NEXT_SESSION.md` ask for both named channels in Individual
mode, which this GUI cannot configure.

Next: expose/wire/validate the second slot, or explicitly define a different
supported timing-calibration procedure and justify its applicability to acquisition.
Do not treat a simple-trigger hold scan as already verifying the coincidence path.

### 4. Cancelling autocalibration after correction can leave unverified trims ready for use

**High — reproduced offline using the real job and scripted transport.**
`application/autocalibration.py:430–459` applies persistent corrections before
the final scan. Cancelling at final-scan entry changed channels 4/5 from 32/32
to 42/22, returned `status=cancelled`, `reference_restored=True`, and
`ConnectionWorker._autocalibration_fault(...) == None`. The shared worker can
therefore return to connected/unfaulted although final verification never completed.

A separate disconnect on the second correction left channel 4 changed but
`calibration_after={}` because that field is assigned only after the loop.
The worker **does** fault-gate the disconnect; the defect in that case is the
missing partial-apply record, not an absent error indication.

Next: record each applied correction and its certainty; on cancellation/failure
after mutation, restore and verify the original state or explicitly latch an
unverified-calibration condition before allowing acquisition. Preserve the intended
persistent-calibration behavior on success. Also replace the reference-restoration
cache check (`find_i2c_row`, lines 386–398) with actual readback if claiming
hardware verification.

### 5. The saved calibration workflow does not join up

**High — reproduced format mismatch and inspected missing result fields.**
`save_calibration_record` requires `<run>/metadata.json`, but top-level
autocalibration writes `autocalibration_metadata.json`. Passing the actual Step-2
run directory therefore fails. Referencing its nested `final/` directory instead
only identifies that subscan, not the complete calibration operation.

Furthermore, top-level autocalibration `persist()` at lines 309–314 saves status,
error, warnings and sub-run paths, but omits the result's before/after trims,
crossings, mean and LSB ratio. Those values exist in memory but are not retained
as explicit top-level results for reopening. The record CLI does not support the
API's HG/LG shaper-gain field, and the procedure still says no record tool exists.

Next: make the record accept the real calibration artifact, persist computed and
partially applied results, expose required record fields, and update the procedure.
An acquisition should identify its calibration and channel-to-sensor layout, either
through an explicit supported artifact or a documented student-managed sidecar.
Existing register tables/snapshots are useful but are not a complete substitute:
the acquisition snapshot excludes trim subaddresses 4/5, and CLI default tables
need not represent calibrated hardware values already applied to the board.

### 6. Live plotting grows with the entire run and blocks GUI input

**High for sustained collection — measured, not just inferred.**
`acquisition_window.py:101–126,908–918` reparses the entire CSV into dictionaries
on each refresh, retains it in `_spectra_rows`, and builds per-channel lists for
histograms on the GUI thread. The bounded worker mailbox does not bound this
separate storage. A once-per-second timer does not make that work asynchronous.

The measured 6.12-second refresh means the same GUI thread cannot handle Cancel
or other input for that interval. Both memory and parsing cost grow with run length.
Next: incremental/bounded plot data, parsing outside the GUI thread, and a bounded
rendering cost. Recheck responsiveness on a representative run, then do endurance
acceptance; do not use the tiny default simulation as its substitute.

### 7. Event counts are inflated and the lab display cannot show a useful spectrum

**High for rate interpretation; medium for layout.**
`acquisition_window.py:915,1030–1049` uses `len(rows)` as “events.” Eight channels,
three batches, five events per batch displayed 120 instead of 15, live and reopened.
The CSV itself retained the expected 15 `(batch,event)` groups; this is a display
error, not evidence of duplicated physical events.

Count physical events separately from channel rows and preserve segment identity
when appending. Also fix the demonstrated 1024×768 layout: eight-channel legend,
status, controls and diagnostic panes leave the plot effectively collapsed, with
a matplotlib constrained-layout warning. Keep diagnostic panes collapsible or
resizeable and test this actual display size with all eight channels enabled.

### 8. Append keeps earlier samples but overwrites their only segment manifest

**High if append is allowed in the student workflow — reproduced.**
`data/acquisition.py:29–38` replaces metadata on append. In the repro, the first
segment used channel 4 / threshold 500 and the second used channel 5 / threshold
700. Both CSV segments survived; metadata retained only the latter configuration.
This is existing behavior, but it conflicts with M2 and the MVP provenance gate.

Next: retain per-segment manifests and validate compatibility. Until then, make
the supported student workflow use a fresh directory per run and explicitly
exclude append from MVP acceptance. Do not remove the existing CLI flag silently.

## Additional reliability gaps

- **Calibration records accept failed verification:** `status=completed` alone
  passes even with `verification.status=failed`; real scan jobs can produce that
  combination. Saving also accepts invalid threshold/timing values and empty
  evidence; loading validates only the schema number. Validate required evidence
  and clearly distinguish incomplete drafts from accepted calibration records.
- **Short batches lack explicit accounting:** acquisition accepts the FPGA's
  returned count without comparing/persisting requested versus received physical
  events. Record the count and expose mismatches. Do not assume requested batches
  × requested events proves the number actually saved.
- **Corrupt saved event groups:** a duplicate `(batch,event,channel)` and a missing
  channel can reopen as `completed` without warnings. This is corruption/truncation
  hardening; normal serial decoding does produce equal-length channel arrays.
- **Sparse-event behavior remains to validate:** defaults request 50 events per
  batch with a 5-second ready timeout. If a batch does not fill, acquisition faults.
  Test realistic quiet periods and partial batches before muon collection; agree
  the expected idle/stop behavior rather than assuming a pulser test establishes it.
- **An individual-event view and complete calibration/layout association remain
  absent.** Current plots are marginal channel histograms. Offline analysis can be
  an acceptable MVP route if it is supplied, documented, and rehearsed by the student.

## Recommended next sequence for Claude

1. Resolve the fixed-pair versus any-pair requirement; do not report Priority 0
   complete while this distinction remains unsettled.
2. Fix autocalibration cancellation/partial-apply state and persistence, and join
   the calibration-record formats. Add focused regression tests for these cases.
3. Make Steps 4/5 actually executable with the supported UI/core configuration,
   and preserve calibration units and provenance correctly.
4. Correct physical-event counts, bound live plotting, and repair the eight-channel
   layout on the lab display. Keep append outside student use until provenance is fixed.
5. After the offline checks pass, run the authorized powered-board path, realistic
   low-rate collection, and the complete student rehearsal. Then perform the
   one-hour representative run. None of the broader deferred parity work needs to
   displace these MVP blockers.

## Final verification result

The host-environment command completed with **exit code 0**:

```bash
MPLCONFIGDIR=/tmp/radioroc-matplotlib QT_QPA_PLATFORM=offscreen \
  timeout 600 .conda-radioroc/bin/python tools/check_development.py
```

**461 tests passed, no skips (178.845 seconds), plus 18 legacy CLI help checks.**
The initial sandbox timeout failures did not recur in this host run; their logs
remain preserved rather than being replaced with the successful result.
The host log is `radioroc_runs/astra_mvp_audit_20260924/development_host.log`.
These tests passing does not invalidate the separately reproduced review findings.
No production fixes or packaging changes were made during this audit.
