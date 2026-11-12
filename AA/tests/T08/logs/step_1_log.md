# T08 Step 1 log (2026-11-12)

- Copied the approved plan verbatim to `tests/T08/PLAN.md` before any code (22,278 bytes, sha256 prefix 76AFFFCA2CC4 equal to the plan file's).
- `python data/check_approved_data.py` exit 0 (52 approved rows, 0 problems; `extended_2026-11-12/SOURCE.md` listed as unregistered, not read).
- `tests/T08/spell_counts.py` (fork of T06's, adds the MAUc1 series, the sleeve-event counts and the gold tables) -> `logs/step_1_spell_counts.json`. Counts only; no price or return read.
- Results: see TRACKER.md and T08.md section 2. Checks that passed: in-or-out states equal T06's on every shared decision (0 mismatches; one date differs, 2026-10-22 -> 2026-10-23); gold series equals D24's weekly file at every decision date; every table feasible; the rule inside every bound.
- Deviation: bar ranges on the raw-fill sessions not read (prices); left to R7.
- `T08.md` section 1-3 written and frozen with `check_prereg.py --freeze`: sha256 17c7615b84f96d4250f4f12d555150ecb129b1044b5bcfeccdfc5969393e8a96. A one-character change was detected (exit 1) and the file restored byte for byte (exit 0).
- Seeds: in-or-out [3, id] and [6, id] as T06; gold [11, 3, id] and [11, 6, id] (first element 11 unused in analysis/ and tests/).
