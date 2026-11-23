# T10 Step 3 log: independent verifier (2026-11-12)

`AA/analysis/verify_t10.py` (about 2,000 lines), written from `logs/verifier_spec.md`, `logs/evidence_contract.md` and `T10.md` §1-§3 (frozen) by an agent that did **not** read `t10_engine.py`, `t07_engine.py`, `t06_engine.py` or `tag_lookup.py` and imports nothing from them, from `approved_data.py`, `check_approved_data.py` or any module of `AA/analysis/` (grep: the only mentions of those names are in its docstring). The previous attempt (agent a87ca103507a3300b) wrote nothing, so this started from scratch. For style and the shape of loaders I read `verify_t07.py` (another verifier, allowed); the loaders, tag lookup, event builder, simulator and every check are written for T10 and were tested here. Files read: the APPROVED rows of `data/APPROVED_DATA.md` (parsed by the script itself: D17 extended, D03, D18 + corrections, D19, D09, D12, D11 both files, D20-D22, D23 panels, D15 AA books for `published_aa`), T06's `daily_nav.csv` and `decisions.csv` (test evidence, for the anchor), and the engine's evidence files (`evidence/smoke4/`, `evidence/smoke/`). Nothing else was read; no data was edited, extended or re-fetched; the engine was not run.

CLI: `python -I analysis/verify_t10.py --run <name> [--evidence-dir DIR] [--no-selftest] [--corrupt-dir DIR] [--books ...]`, from `AA/`. It writes `verify_t10.json` into the evidence directory and exits 0 only if every gated check compared at least one row with no failure and no missing row, no required evidence file is missing, and the C-corrupt self-test detected every corruption. About 25-35 s for the checks, about 70 s more for the self-test.

## The independent anchor (C-t06): passes

With the state set to "IN iff all three SIGN cells are BUY", the verifier's own simulator reproduces T06's `evidence/headline/daily_nav.csv` on every shared session up to 2026-10-22: `strategy` against `switch`, and also `hold_parent` and `sleeve_only`, at 0, 20.8 and 50 bps, four books (23,106 sessions each series, 78,651 comparisons including the rebased published NAV and 1,631 decisions); **max relative difference 4.4e-16** (limit 1e-12), decisions equal on every shared date (1,631 of T06's 1,635; the four missing ones are T06's last decision, 2026-10-22, a Thursday, which is not a weekly decision date of the longer calendar). It settled the NAV conventions at the first attempt: weights renormalised to row sums, T0 basket drifted from its availableDate's first D18 session at OHLC4 and scaled to NAV 1.000 at T0's close, trade value V at the trade session's fills, cost on Σ|target − held| over stocks, GOLDBEES and cash, positions scaled by (V − cost) ÷ V, de-spiked GOLDBEES fill, cash as-of. No ambiguity was found in T06 §3 / T07 §3 for these.

## Result on the engine's scratch evidence: no disagreement

| check | smoke4 compared | failed | worst rel. difference | smoke (SCMO_0003) compared |
|---|---|---|---|---|
| C-data (inputs.csv rows: APPROVED, sha256 on disk and in the registry, through-date) | 41 | 0 | 0 | 41 |
| C-dec (decisions: dates, trade date, SIGN cells, label dates, pattern, basket_eff, n_held, idx) | 2,687 | 0 | 0 | 672 |
| C-tag (every weekly tag read: band, tag_source, tag_snapshot, listed_weight, on, band_signal, row order) | 32,326 | 0 | 0 | 7,115 |
| C-fs (n, band counts, k, FS, weight FS, states, extra, tie, floats; no rule-OUT-while-switch-IN; v4_exact.json fields) | 2,753 | 0 | 2.5e-16 | 690 |
| C-events (events.csv 269 + skipped_baskets.csv 76) | 345 | 0 | 4.2e-16 | 83 |
| C-nav (stats 124 rows x 14 columns, daily_nav 123,616 rows, trades 1,239 rows) | 124,979 | 0 | 3.9e-15 | 31,249 |
| C-thr (thr_2/5, 1/2, 7/10, 4/5, weight_fs) | 20 | 0 | 1.8e-15 | 5 |
| C-t06 (anchor, above) | 78,651 | 0 | 4.4e-16 | 19,668 |
| C-always-in (G0, 4 books: overall, yearly, g_engine.csv) | 40 | 0 | 1.2e-13 | 10 |
| C-r7 (stretches.csv, both windows) | 76 | 0 | 9.7e-12 | 15 |
| C-boot (bootstrap.csv, 1,000 resamples, 2 comparators x 4 books) | 8 | 0 | 5.6e-14 | 2 |
| C-r4 (r4_tag_error.csv draws) | 80 | 0 | 2.0e-14 | 20 |
| C-v5 (500-pair D23 sample per book + tag reads = Σ n_held per book and window) | 2,008 | 0 | 0 | 502 |
| C-pit (decision labels, tag snapshots, trade sessions; verifier's derivation and the evidence's own columns) | 86,652 | 0 | 0 | 19,720 |
| **total gated** | **330,666** | **0** | | **79,792** |

Both runs exit 0 (`verify_t10.json` written in each evidence directory). Everything the engine wrote in these two runs was re-derived and agrees: **no failure, so no engine bug suspected**. The numbers behind: rule IN weeks 237 / 244 / 251 / 258, extra weeks 36 / 43 / 50 / 57 in 8 / 9 / 11 / 13 stretches (live 18 / 18 / 32 / 33 in 5 / 5 / 8 / 9: every realisation clears the 5-stretch reportability gate), ties 1 / 4 / 3 / 6, float formula never differs, rule never OUT while the switch is IN, engine events 38 / 40 / 41 / 45 for the rule (my own count agrees, so the one-above in SCMO_0029 against Step 1's coarse bound is the bound's, not an error), V5: own tag lookup and the engine both agree with a direct read of the D23 panels on all 2,000 sampled pairs; every tag read in both runs (32,325 / 7,115) equals the engine's, including `tag_via` and the rank (information columns, not gated: 0 differences).

## C-corrupt (self-test): passes

14 corruptions, each applied alone to a copy of the evidence in scratch space (`C:\Users\manur\AppData\Local\Temp\claude\...\scratchpad\corrupt_smoke4\`), each must make its relevant check fail: a flipped tag band (C-tag), a flipped `state_rule` (C-fs), a changed `basket_eff` (C-dec), a changed trade cost and a scaled NAV (C-nav), a deleted event (C-events), a changed stretch span (C-r7), a changed R4 CAGR (C-r4), a changed bootstrap bound (C-boot), a changed threshold-run `end_nav` (C-thr), a changed sha256 in `inputs.csv` (C-data), a changed G0 gap (C-always-in), a tag snapshot dated after its decision (C-pit), a changed V5 count in `audit.json` (C-v5). All 14 detected. Then all 14 in one copy: the in-process run fails (1,947 failures) and the script itself, run as a subprocess on a full copy with every corruption applied, **exits with status 1**. C-t06 is not self-tested because it compares the verifier with T06's files, not with the engine's evidence.

## Readings and ambiguities (none changed a result)

1. **G0 annual gap** (T10.md §2 V3, spec check 9): the unit "pp/yr" is read in calendar years, (end NAV)^(1/years) with years = days ÷ 365.25; that is what `g_engine.csv` holds (0.04486851256428892 for SCMO_0003, matched to 1e-13). With years = (sessions − 1) ÷ 252, as in the strategy statistics, the gaps are 0.0460, 0.1052, 0.1028 and 0.0394 pp/yr instead of 0.0449, 0.1028, 0.1002 and 0.0384; both pass the ±0.25 limit. The yearly gaps (worst 2022: 0.4255, 2019: 0.3909, 2019: 0.4469, 2019: 0.1889 pp, limit 0.5) are the same under either reading. The frozen text does not say which; the verifier uses the engine's reading and prints both.
2. **R3 cash leg.** Spec: LBES to the session before 2024-01-24, then chained with LIQUIDCASE returns. The verifier builds exactly that. A plain LIQUIDCASE as-of level differs from the chained one by 8e-11 relative in the end NAV (SCMO_0003: 6.65257411060 against 6.65257411114); the evidence matches the chained one to 1e-15 (a plain one would also have passed at 1e-9, so the choice is not tested by the tolerance, only by the 1e-15 agreement).
3. **Skipped baskets** (a basket change on a session where the book is OUT after the latest decision). Read as skipped even if an IN-to-OUT state event falls on the same session. In both evidence runs no such coincidence occurs (0 of 76 rows), so the reading is not tested.
4. **Tag lookup.** Built from D20-D22 with ISIN links through D22 (`isin`, `new_isin`) only; a variant that also links through D20's own (isin, quote_id) pairs gives identical tags on every row (tested; `USE_D20_PAIRS` switch in the script, default off, the spec's reading). No multi-band membership row occurs. The `tag_detail` text for membership rows differs in wording from the engine's (the engine writes the index name, the verifier `isin=...`); not compared, not part of the contract.
5. **R4 uniforms.** Draws are taken as one `rng.random((R, 2))` block (R = rank-sourced reads of the full window in decision then ISIN order), which is the same stream as two sequential `random()` calls; it reproduces the engine's draws to 2e-14 (the CAGR path), `weeks_changed`, `flipped` and `rank_tag_reads` exactly.
6. **R4 coverage in the scratch runs.** The spec asks for the first 20 and 20 random draws per book (`default_rng([13, book_no]).choice(500, 20, replace=False)`). The scratch runs hold 20 draws per book, ids 0-19, so only the first 20 per book (80 in smoke4) could be compared; of the 80 random ids, 77 were not in the shorter evidence files and are listed as not compared (3 random ids fall inside 0-19). In a 500-draw headline run an absent id is a failure.
7. **Stretch summary rows.** `weeks` of the `stretch_no = 0` row is read as the total number of extra weeks (the engine's choice; the contract does not say); compared and equal. The span end of a run reaching the last decision is the window's last session, as the contract says.
8. **`published_parent` and `published_aa` statistics.** `invested_weeks` of `published_parent` is the number of decisions (410 / 409 / 262 / 262 ...), `published_aa` has none; the published AA books are read from the D15 rows (live window, rebased to 1.000 on the first session of the window), and the 4 rows agree with the engine's.
9. **Constant mix.** f = mean over the rule's sessions of stock value ÷ NAV at the same cost, window and cash; the T0 position is the drifted basket scaled to f (free), later events set stocks f × w_i and (1 − f) ÷ 2 in each of GOLDBEES and cash. Equal to the engine on every NAV, trade and `mix_share_f`.
10. **Not covered, by the spec:** `t07_rule` rows (23,178 daily NAV rows and 20 stats rows in smoke4) are descriptive and not verified; the verifier says so in `verify_t10.json` (C-nav notes).

## Limits of what this verifier can tell

It shares the frozen design with the engine, so a wrong design would pass both; the T06 anchor is the only check against an independently produced number set, and it covers the switch, the parent, the 100% sleeve and the published NAV to 2026-10-22, not the FS rule or the sessions 2026-10-23 → 2026-10-30. The D23 cross-check is of the tag data's derivation (D20 → D23), not of its accuracy against reality (the review's 92.07%). It does not check `positions`, which are not in the contract.

## Files

Written: `AA/analysis/verify_t10.py`, this log, `AA/tests/T10/evidence/smoke/verify_t10.json`, `AA/tests/T10/evidence/smoke4/verify_t10.json`, the Step 3 row of `TRACKER.md`. Scratch (not in the repo): corrupted copies and helper scripts in the session scratchpad.
