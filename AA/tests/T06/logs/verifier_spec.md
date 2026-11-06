# Verifier spec for T06 (`AA/analysis/verify_t06.py`)

Written 2026-11-06 by the main agent from `T06.md` §1–§3 and `PLAN_v2.md`. The verifier is written from this file, `T06.md` §1–§3, `tests/T03/logs/verifier_spec.md` (the conventions of the rule, unchanged) and `analysis/verify_t03.py` (an independent verifier of the T03 engine, to be **forked**). **The verifier must not read `analysis/t06_engine.py`, `analysis/t03_engine.py`, `analysis/approved_data.py`, or any other AA analysis module, and must import nothing from them.** It reads raw data files, `data/APPROVED_DATA.md` (parsed by its own code) and the engine's evidence.

## What stays as in `verify_t03.py` / T03's spec
Decisions from the raw Master files and D17's calendar; basket logic, execution at OHLC4, the trade function, the cost, parent rebalances, GOLDBEES de-spiking, NAV, statistics, the comparators (hold the parent, constant mix including the rebalance after T0's decision, 100% sleeve), always-in against the published NAV, the self-test on a corrupted copy. Tolerance 1e-9 relative on NAVs.

## What changes (every difference from T03)
1. **Data files** (all are APPROVED rows of `data/APPROVED_DATA.md`):
   - signals: `Historical Data/extended_2026-10-30/Master/Master_{Nifty100,MC100,SC100}.xlsx` (not the frozen files);
   - GOLDBEES: `analysis/cache/why_gold_ohlc_eikon_extended_2026-11-04.parquet`;
   - cash: `Historical Data/LBES_Adjusted_Price_data_extended_2026-11-05.csv`; R2 cash: `Historical Data/liquidEtfFinal_extended_2026-11-05.csv`;
   - de-spike range: `analysis/evidence/final_strategy/mauc1/mauc1_daily_clean.csv` (ends 2026-09-28; for a session after its last date the fill is the **raw** GOLDBEES OHLC4, no clipping, no scaling, no +0.5%);
   - unchanged: D17 `parent_nav_2026-10-22/SCMO_<p>.csv`, D18 `data/holdings_matrix/SCMO_<p>_ohlc.csv` and `price_corrections.csv`, D19 weight matrices, `_columns.csv`, `_holding_weight_sources.csv`, D05 rebalance history.
   The verifier **parses the table in `data/APPROVED_DATA.md` itself** (rows between `<!-- approved-table:start -->` and `<!-- approved-table:end -->`; columns Status, ID, File, Through, sha256 prefix, Note). Check C-data below.
2. **Window end.** `END` is the last date of D17 (2026-10-22), derived from the files, not typed. T0 as T03 (2019-01-02; 0007 2019-01-04). The decision at the last session is made but not traded.
3. **Cash.** The extended LBES file covers the whole window. As-of level on each session; no accrual beyond the file's last date may occur (assert).
4. **Live window.** T0 = first D17 session on or after 2021-11-01, then the last D17 session of each later ISO week, to END. Own spells and totals.
5. **Nulls.** Two types in `draws.csv`: `N4.9` and `N4.10`. No circular shift, so drop the shift checks. The draws' states are in `draw_states.npz` (below); the verifier does **not** regenerate N4.10 draws from seeds (it checks their structure); for N4.9 it may regenerate with `numpy.random.default_rng([3, draw_id])` (shuffle in-spells with `rng.permutation`, then out-spells with `rng.permutation`, interleave from the rule's first state), as T03's spec says.
6. **Spell structure on the new series (SCMO_0003, 0010, 0029):** 409 weekly decisions, first state OUT, 9 in-spells (lengths 8, 13, 33, 23, 20, 26, 46, 11, 21; sum 201), 10 out-spells (11, 29, 15, 16, 40, 18, 5, 30, 37, 7; sum 208). SCMO_0007: 408 decisions, first out-spell 10 (sum 207). These are derived by the verifier from the raw files and must equal the engine's `decisions.csv`; they are not typed into the verifier.

## Evidence files the verifier reads (`tests/T06/evidence/<run>/`)
`inputs.csv` (`file, through, bytes, sha256, approved_row`), `decisions.csv`, `stats.csv`, `draws.csv`, `draw_states.npz`, `draw_curves_20.8.npz`, `trades.csv`, `positions.csv`, `daily_nav.csv`, `g_engine.csv`, `count_table.json`, `audit.json`. Formats as T03's (`tests/T03/evidence/headline/*`) except:
- `draws.csv`: T03's columns, `draw_type` in {`N4.9`, `N4.10`}, plus `sessions_invested`, `in_lengths`, `out_lengths` (lengths in order, joined by `|`).
- `draw_states.npz`: one `uint8` array per key `"<book>|<window>|<type>"` (window `full` or `live`; type `N4.9` or `N4.10`), shape (draws, weeks): the in-or-out state of every draw in every week (1 = parent). The LIQUIDCASE run reuses the `full` states.
- `draw_curves_20.8.npz`: key `"<book>|<type>_<id>"`, daily NAV float32, headline window, 20.8 bps.
- `count_table.json`: per book, window and state: `k`, `S`, `lo`, `hi`, `n_ways` (an exact integer as a string).

## Checks (all must pass; the verifier exits 0 only if rows were compared and none failed)
- **C-data (new):** every file in `inputs.csv` is an APPROVED row; its sha256 starts with the row's prefix; the row's Through covers END (or is "n/a"); no file in `inputs.csv` is SUPERSEDED or PENDING.
- **C-dec, C-pit, C-nav0, C-cost, C-comp, C-always-in, C-corrupt:** as `verify_t03.py`, on the new data and window. C-always-in compares the engine's always-in NAV with the published NAV over the whole window within the G0 tolerance (±0.25 pp/yr overall, ±0.5 pp in every calendar year).
- **C-t03 (new, regression to T03 on the overlap):** the verifier's own decisions equal `tests/T03/evidence/headline/decisions.csv` on every shared decision date; its own strategy and comparator NAVs equal T03's `daily_nav.csv` up to 2026-08-07 (relative 1e-12).
- **C-states (new):** for every draw of every book, window and type in `draw_states.npz`: length equals the book's weeks (live: the live weeks); first state equals the rule's; spell counts equal the rule's; invested weeks equal the rule's; for `N4.9`: sorted in- and out-lengths equal the rule's; for `N4.10`: in-lengths in [2, HI_in] and out-lengths in [2, HI_out] with HI_in, HI_out = the rule's longest in- and out-spell on the full window (46, 40), in-lengths sum to S_in and out-lengths to S_out, spells alternate. Compare the draw's `invested_weeks`, `n_in_spells`, `n_out_spells`, `in_lengths`, `out_lengths` in `draws.csv` with the states. Recompute `sessions_invested` (sessions between a week's trade date and the next week's, summed over IN weeks; as the engine defines it for the first week and the last) and compare.
- **C-draw-nav (new):** from the saved states, simulate with the verifier's own simulator the first 20 and 20 random draws per book and type (seeded), at each cost, full window LBES; end NAV and CAGR within relative 1e-9 of `draws.csv`; for the headline 20.8 bps also compare the whole curve with `draw_curves_20.8.npz` (float32 tolerance 1e-5). Also 10 draws per book of the LIQUIDCASE run and of the live window.
- **C-count (new):** count the allowed N4.10 tuples with the inclusion–exclusion formula Σ_j (−1)^j C(k, j) C(S − k·lo − j·(hi − lo + 1) + k − 1, k − 1) (terms with a negative top argument are zero) for every book, window and state, and compare with `count_table.json`.
- **C-support (new):** the rule's own in- and out-lengths lie within the bounds (so every N4.9 draw is an allowed N4.10 configuration).
- **C-percentile (new):** recompute each C1 and C2 percentile and p-value from `draws.csv` (ties within a relative 1e-12; percentile = (worse + 0.5 × tied) ÷ draws × 100; p = (1 + at least as good) ÷ (draws + 1)) for each book, cost and type, and compare with `analysis.log` if it exists and with the `stats` the analysis wrote.
- **C-corrupt (self-test):** a copy of the evidence with decisions flipped, a NAV scaled **and one N4.10 draw's lengths changed out of bounds** must make the verifier exit non-zero.

## CLI and output
`python analysis/verify_t06.py [--evidence DIR] [--no-selftest] [--out FILE]`, run from `AA/`; default evidence `tests/T06/evidence/headline`; writes `verify_t06.json` there with the counts per check (compared, failed, missing, worst relative difference) and `exit_ok`, `gate_compared`, `gate_failures_and_missing`, `selftest.detected` (the keys `check_page.py` reads in T03). Prints a table.
