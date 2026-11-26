# T16 Step 1 log: pre-registration (2026-11-26)

- Manu's "lets execute T16" (chat 2026-11-26) taken as approval of `PLAN_v2.md` (D1-D4 already settled by him).
- `python data/check_approved_data.py` exit 0 (98 approved rows, 0 problems, 5 PENDING, 5 superseded; numpy/numexpr warning on import is noise).
- `tests/T16/spell_counts.py` (fork of T15's; ten rules; W2 inputs of `extended_2026-11-25` / `extended_2026-11-20`; W2 end = min of the signal roles = 2026-11-20, asserted; asserts `-all` trades equal `-liq`'s) -> `logs/step_1_spell_counts.json`.
  - W1 equals T15's and the plan: 228 decisions, IN 93 / OUT-BUY 81 / OUT-SELL 54 in 8 spells, k0/k1/k2 21/18/15, `-all` trades 24 (`-idx` 32).
  - W2: **1,946 sessions (SCMO_0007 1,944), not the plan's 1,947** (the plan said "Step 1 counts them"; the count wins and `T16.md` §2/§3 say 1,946); 413 decisions (412); IN 201 / OUT-BUY 163 / OUT-SELL 49 in 8 spells (1, 4, 10, 2, 12, 11, 4, 5); k0/k1/k2 24/3/22; `-idx` index weeks 25 in 7 spells; B changes 8; trades `-all` 27 (`-idx` 35, T15 33, +2 from the new weeks' B changes).
  - R3: W1 from 2015-01-02 44 OUT-SELL weeks in 7 spells, 21 trades; W2 live 34 / 5, 16 trades.
  - The three new weeks equal the plan: 2026-11-06 BUY/SELL/SELL, 11-13 and 11-20 BUY/BUY/SELL, MAUc1 SELL; last spell 2026-10-23 -> 11-20 = 5 weeks (B: cash 2, Nifty100 1, Nifty100+MC100 2).
- `T16.md` §1-§3 written (T15.md layout; adds §2.0, the rules-and-runs table in words, AGENT.md R10 item 1; C1-C6; V4(a) cut at 2026-10-30). `check_prereg.py --freeze`: sha256 `eda7321d73b71455f1df8442e99989f4bbb376912e8ee22a80cc4c08862f1ebc`.
- `AA/CLAUDE.md`: test-in-progress line added.
