# Solo execution plan (RADIOROC 43, 2026-10-19)

Standing rule from the operator: no branched decisions. This file is the plan; execute
it in order, record results in `IMPLEMENTATION_STATUS.md`, interrupt the operator only
for urgent safety issues (a board hang needs a power cycle: stop touching the board,
leave notes, continue offline work).

Bench state: SiPMs 29 V on ch 4/6/32 on the plint; LED through a hole; generator CH1 in
triggered burst from board IO1 (mux 5); DSO C1 = ASIC analog probe (ch6 HG shaper),
C2 = generator. Hold ~600 ns for the synced LED pulse (threshold 520, HG code 15).

## Tasks
1. Read the generator's settings and find the working SCPI for amplitude and pulse width
   (CH1 only, `LOCAL` afterwards). Log the commands that work.
2. Dim the LED (amplitude, then width) until the shaper pulse is a few photoelectrons;
   check each step on the DSO, take short synced acquisitions on ch 4/6/32, look for
   resolved p.e. peaks; keep the best setting as the LED operating point.
3. Take a final longer synced acquisition at that point and record spectra and paths.
4. Desktop launcher: macOS `.app` on the Desktop with an intuitive icon that starts
   `radioroc-desktop` without a terminal.
5. Update `IMPLEMENTATION_STATUS.md` / `NEXT_SESSION.md`, commit explicit paths.
6. Reset the analog probe on ch6 when the DSO is no longer needed.
