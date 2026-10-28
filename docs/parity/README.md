# docs/parity

Date: 2026-10-22 (RADIOROC 46).

This folder holds the vendor feature-parity table that `docs/project/CROSS_PLATFORM_REBUILD_PLAN.md` (milestone M0, section 3)
asked for and that `IMPLEMENTATION_STATUS.md` recorded as never built.

- `parity_table.md`: one row per plan feature F01..F17, with sub-rows (F04a, F05b, ...) where the plan or the code
  splits a feature. Columns: ID, Feature, Vendor screen / control, Registers or protocol (pointer), Our CLI, Our GUI,
  Tests, Hardware-validated, Status.
- `gaps.md`: the Partial, Not started and Needs hardware rows, split into what can be done offline and what needs the
  board, plus features that exist in the app but not in the plan.

## How to read it

Every cell comes from something that was found: a source path, a test module, a section of `docs/register_map.md`,
a section of the vendor user guide (UG), or an entry of `IMPLEMENTATION_STATUS.md`. The word `unknown` means no
evidence was found; it does not mean "no". Log entries are cited by title (for example "Log: RADIOROC 24") rather
than by line number, because the log is edited by several people and line numbers move.

Status words:

| Status | Meaning |
|---|---|
| Delivered | Core, CLI or API, and GUI exist with offline tests, and the main behavior was exercised on the board (or the feature has no hardware side). Delivered does not mean compared against the running Windows app; no row has been (plan section 4, M4 gate). |
| Partial | Some of the row works; the Hardware and Gap cells say what is missing. |
| Not started | No code, or the code explicitly says it is not covered. |
| Needs hardware | The software exists, but the evidence that it is correct needs the board, a scope or a pulser and has not been collected. |
| Excluded | Out of scope by decision (only F15: no CAEN A7585 in the lab, 2026-09-22). |

Parent rows (F01, F02, F04, ...) with sub-rows carry an overall status; the counts in `gaps.md` and the status log use
the leaf rows (sub-rows, or the row itself when it has none).

Caveat for every row: vendor evidence so far is static bytecode, the user guide and screenshots. The plan's M0 step
"inventory the running Windows 2.2.0.5 app" has not been done, so vendor screen and control names come from the guide
(2.1.0.x) and the extracted bytecode.

## How to update it

1. When a feature changes, edit its row in `parity_table.md` in the same commit as the code or log entry.
2. Change a Status only with evidence: a test module for code claims, a status-log entry for hardware claims. Never
   upgrade a row to Delivered on offline tests alone if it writes registers that have not been read back on the board;
   use Needs hardware.
3. Add a sub-row when a feature splits (use the next letter); keep the parent row's status as the summary.
4. Move the row between sections of `gaps.md` when its status changes, and refresh the counts.
5. Hardware runs are done only by the designated operator (see `AGENTS.md`); workers update rows from saved
   evidence only.
