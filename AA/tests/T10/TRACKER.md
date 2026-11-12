# T10 Progress Tracker

**Overall status: IN PROGRESS (2026-11-12).** Steps 0 and 1 are done; the pre-registration is frozen (sha256 `dcd2dbb3648f`). Steps 2-4 can start in parallel; Step 5 needs all three. Plan: `PLAN.md` (approved by Manu, "approved", 2026-11-12). The frozen design is `T10.md` §1-§3 and wins where they differ. Read this file before starting any step; update it when you finish.
Status values: `NOT_STARTED` → `IN_PROGRESS` → `DONE` (or `DONE_WITH_NOTES`).
**Data boundary:** read `AA/data/APPROVED_DATA.md`; use only its `APPROVED` rows; run `python data/check_approved_data.py` first; if anything is stale, missing or unclear, stop and ask Manu.
**No null (Manu's waiver, 2026-11-12).** No finding may say the rule beats chance; no finding is stronger than PROVISIONAL; the negative control and oracle are not run (`T10.md` §2, §6).

| Step | Status | Blocked by | Agent / Date | Output summary |
|---|---|---|---|---|
| 0 Setup | DONE | — | Claude / 2026-11-12 | `AA/tests/T10/` created; `PLAN.md` (written in this folder directly, not copied from the plan-mode folder; approved by Manu); `check_approved_data.py` exits 0 (64 approved rows, 0 problems); this tracker |
| 1 Pre-registration | DONE | 0 | Claude / 2026-11-12 | `T10.md` §1-§3 written and frozen, sha256 `dcd2dbb3648f2d210681ba3397628d9cbeb06fb584843da053134ff93cacecd5` (`python tests/T10/check_prereg.py` verifies). Counts only (`step1_counts.py`, `logs/step_1_counts.json`, no price or return read): rule IN 237 / 244 / 251 / 258 weeks of 410 (0007: 409) against the switch's 201; extra weeks 36 / 43 / 50 / 57 in 8 / 9 / 11 / 13 stretches (live 18-33 in 5-9, so every realisation clears the 5-stretch gate); rule OUT while switch IN 0 everywhere; exact FS = 0.60 ties 1 / 4 / 3 / 6, the float formula agrees in all; rule flips with no signal flip 0 / 0 / 0 / 4; SCMO_0003's decision is exactly "Smallcap 100 is BUY" |
| 2 Engine | NOT_STARTED | 1 | — | `analysis/t10_engine.py`: fork of `t07_engine.py`; inputs only through `approved_data.require()`; tags through `tag_lookup.py` **at every weekly decision**; FS in integers (IN iff 5k ≥ 3n); comparators (switch, parent, 100% sleeve, constant mix, T07's rule descriptive); R1-R8 (R4's 500 tag-error draws, seeds `[10, draw_id, book_no]`; bootstrap `[11, …]`; V5 sample `[12, book_no]`); `decisions.csv`, `events.csv`, `audit.json` (counts for V2, readings); V3 regression (decision rule AND reproduces T06's NAV to 1e-12) and V4 exact facts |
| 3 Independent verifier | NOT_STARTED | 1 | — (a different agent) | `analysis/verify_t10.py` from a written spec, not reading `t10_engine.py` or `tag_lookup.py` (V1) |
| 4 Test scripts | NOT_STARTED | 1 | — | `analyse.py` (exits 1 on a failed gate V1-V5), `fill_writeup.py` (§1-§3 byte-identical, F-AA-M02), `report.py`, `check_page.py`, `run.sh` |
| 5 Run and gate | NOT_STARTED | 2, 3, 4 | — | `bash tests/T10/run.sh` |
| 6 Analyse, report, write-up | NOT_STARTED | 5 | — | `T10.md` §4-§8 (the plain-words walkthrough with one real weekly decision worked by hand), results page, `AA/ARTIFACTS.md`, `AA/CLAUDE.md`; finding IDs from the counter at closing (next free are held by T07 and T08's pending findings; T10 takes the ones after them) |

## Step-level notes

- **⚠ AFFECTS STEP 2: reuse T06's `trade()` exactly.** No cash account: stock target V × w_i (weights renormalised to row sum 1), GOLDBEES and cash V ÷ 2 each when OUT, then every position scaled by (V − cost) ÷ V; basket events traded only while IN; state events only when the state changes. Reproduce it exactly or V3 fails.
- **⚠ AFFECTS STEPS 2 AND 3: tags at every weekly decision, not at events.** T07 reads tags at events only. In T10 the decision at d uses the basket in force at d (latest non-skipped basket with availableDate ≤ d) and `tag_lookup.tag(ISIN, d)`; the targets at an event on session s use the basket in force at s; at a basket event the state is that of the latest decision made before s (not re-evaluated until the next weekly decision).
- **⚠ AFFECTS STEPS 2 AND 3: integers.** k = stocks whose band is on, n = stocks held (listed weight > 0); IN iff 5k ≥ 3n. R5's thresholds are fractions (2/5, 1/2, 3/5, 7/10, 4/5); R6 uses listed weights with threshold 0.60.
- **Step 1 counts are coarse upper bounds for events** (any decision flip, or a basket change while the rule is IN); the engine's own counts are lower or equal. Do not copy them as expectations.
- **Not decided in the frozen text and left to the engine author to fix and log in `audit.json` (`readings`):** the exact shape of `decisions.csv` columns beyond those named in `T10.md`'s header, the order of ISINs for R4 (increasing ISIN string), and how a basket change while OUT is logged (nothing is traded; the new basket is the one read at the next weekly decision).

## Files created or modified

### Steps 0 and 1
- `AA/tests/T10/PLAN.md`, `T10.md` (§1-§3 frozen; §4-§8 skeleton), `check_prereg.py`, `step1_counts.py`, `logs/step_1_counts.json`, `TRACKER.md`; `AA/CLAUDE.md` (one bullet)
