# T16 Step 2 log: engine (2026-11-26)

`analysis/t16_engine.py`, a fork of `t15_engine.py`: copied, not imported. The trade / simulate / stats arithmetic, the Book construction, the identities and the regression helpers are **byte-identical** to T15's (V4(d) requires 27 functions identical; the 16 that differ are the input paths, the new rule's targets and trigger, the gates' reference and the run plumbing). Command: `python analysis/t16_engine.py [--run NAME] [--window w1|w2|both] [--quick] [--books ...] [--workers N] [--outdir DIR]` (from `AA/`); default output `tests/T16/evidence/<run>/{w1,w2}/`.

## Result of the smoke runs (no result number read; gates and counts only)

- Scratch directory `C:\Users\manur\AppData\Local\Temp\claude\d384933f9ddb0ecb\2a47066e-8a25-4836-b88e-f853d8a0d20f\scratchpad\smoke4\{w1,w2}` (all four books, both windows, 35 seconds in all): exit 0, V2 / V3 / V4 / V5, the data self-test and the step-1 counts all pass.
  - **V4(a) exact on the extended data:** the eight T15 rules and hold-the-parent reproduce T15's stored `daily_nav.csv` (108 rows per window: 4 books x 9 runs x 3 costs) and `trades.csv` (108 rows) with worst relative differences W1 **0.0**, W2 **2.2e-16** (NAV) and **0.0** (trades), W2 on sessions and trade dates to 2026-10-30. The decisions up to 2026-10-30 equal T15's stored decisions (410 of 410 for SCMO_0003); the three later decisions (2026-11-06, 11-13, 11-20) are new.
  - W1's `inputs.csv` equals T15's (34 files, same sha256). W2's lists the 21 files shared with T15 and 19 extended ones (D03 / D24c / D25d 2026-11-20, D17 / D18 / D11 2026-11-25, D09 2026-11-23).
  - V4(b)/(c): `-all` and `-idx` priced on cash equal `-liq` (worst 1.8e-15); V4(f): the one-instrument identity and W2's G0 pass on the extended window (SCMO_0003 overall +0.046 pp/yr, worst year 2022 +0.43 pp, 2026 -1.3e-8 pp), the 2019 seam -0.22 pp.
  - V5: 4,122 (W1) and 5,559 (W2) trades checked at worst 5.8e-16; after the 192 `-all` regime entries per window (4 books x 2 rules x 3 costs x 8 spells) cash and each index are 0.25 of the value after cost to 5e-17, no parent and no GOLDBEES; 0 `-all` trades inside a spell, 0 `index_set_change` trades for `-all`. SCMO_0003 `50-all` at 20.8 bps: W1 8 regime entries, 8 exits; W2 8 entries and 7 exits (the last spell, 2026-10-23 -> 11-20, is open at the window end), regime and switch trades 27 = `-liq`'s.
  - V3: the Master `Index` column equals the D25 / D25d close on every label date used (W1 681 labels, W2 1,224, 0 violations).
  - Step 1's counts are reproduced for every book and both R3 windows (`-all` trades equal `-liq`'s).
  - Stand-ins (SCMO_0003): W2 GOLDBEES trades filled at the raw OHLC4 (no D12 range) 97 over all runs; 0 stock lines priced by a stand-in in a trade; 0 GOLDBEES trades priced at a previous close; the three Budget weekend sessions carry the last index close and are decision sessions only; two carried stock bars in the whole W2 D18 (not in the new sessions).
- Run time is **about 35 seconds for both windows** (the plan guessed 2 minutes).

## Engine readings (decided here, written into `evidence_contract.md`)

1. **`-all` target key** = the regime alone (IN / OUT-BUY / OUT-SELL), so an index SIGN change or a B change inside OUT-SELL never trades; entries and exits are `regime_in` / `regime_out` trades (an OUT-BUY -> OUT-SELL week is `regime_in`), as for `-idx`.
2. **R4** runs the two `-all` rules only, with target cash 1 on the spell's decisions (`cash_mask` in `rule_targets`); the spell's entry and exit still trade (the key is unchanged), which is `-liq`'s arithmetic for the spell. R2, R3 and R5 run all ten rules.
3. **W2 inputs** are per-window in `WINDOWS` (Master dir, GOLDBEES parquet, cash files, MAUc1, index dir); the extended D18 is chosen in `raw_parent` by the window's end (`end > 2019-01-02` -> `extended_2026-11-25/holdings_ohlc`). W2's END is the earliest of the three D03 files' and MAUc1's last SIGN dates and **must equal 2026-11-20** (asserted).
4. **V4(a) boundary (E17):** W2 is compared with T15 on sessions and trade dates up to 2026-10-30 only; the decisions up to then must equal T15's stored decisions, the three later ones are the only unmatched ones.
5. **Comparator `eq3_index_basket`** (the plan's "equal-weight three-index basket alone"): one third each, rebalanced at every weekly decision's next session like the constant mixes, 20.8 bps (E18). Plain buy-and-hold of each index is `hold_<index>`.
6. **Ledger** gains `all_minus_idx_50` / `all_minus_idx_80` per spell and per stretch (the k = 0 / k >= 1 split is the sum over stretches by `k`; the analysis does the summing).
7. **V5** gained `all_*` identities and worked examples (`50-all|regime_in`, `regime_in_k0`, `regime_in_k1`, `regime_out`, `B_change_not_traded` showing 0 `-all` trades and 1 `-idx` trade on the session after the first inside-spell B change, 2019-05-27).

## Not done / untested

- The independent verifier (Step 3) and the analysis scripts (Step 4) do not exist yet.
- The headline run directory `tests/T16/evidence/headline/` is not written yet (Step 5); the scratch directory above is not evidence.
