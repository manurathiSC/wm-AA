# T03 Steps 5 and 6 log: run and nulls (2026-11-05)

Both are one engine run: `python analysis/t03_engine.py --run headline` (82 s). Evidence in `tests/T03/evidence/headline/`.

## Step 5: strategy and comparators, 4 books x 3 costs

CAGR / worst fall at 20.8 bps, full window 2019 -> 2026-08-21:

| Book | Rule | Hold parent | Constant mix (49.8% in) | 50/50 sleeve | Published NAV |
|---|---|---|---|---|---|
| SCMO_0003 | 30.11% / -18.42% | 18.01% / -46.32% | 16.08% / -24.82% | 15.86% / -19.31% | 18.44% / -46.12% |
| SCMO_0007 | 21.61% / -19.54% | 11.24% / -54.65% | 12.57% / -27.23% | 15.87% / -19.31% | 11.50% / -54.63% |
| SCMO_0010 | 31.41% / -15.22% | 25.85% / -44.98% | 19.36% / -24.23% | 15.86% / -19.31% | 26.24% / -44.88% |
| SCMO_0029 | 27.78% / -15.22% | 24.83% / -36.92% | 19.40% / -21.45% | 15.86% / -19.31% | 25.22% / -36.92% |

The engine's hold-parent after 20.8 bps runs 0.2 to 0.4 pp/yr below the published NAV, which pays no cost. 0010 and 0029 share a worst fall of -15.22%: it happens in the sleeve, which is the same in every book.

## Step 6: nulls

- N4.9: 9 in-spells and 9 out-spells per book (18 spells, 9 round trips), 2,000 seeded draws per book and cost (40,000 in all at the headline window and LBES cash), plus R3 (LIQUIDCASE cash) and R4 (live window, 5 round trips) at 20.8 bps.
- Circular shift: 308 shifts per book and cost (307 for SCMO_0007, which has 399 decisions).
- V3: 0 signature mismatches over 40,000 draws, 0 invested-week mismatches; shifts keep invested weeks identical, with a largest spell-count gap of 1 (the wrap).
- MDE (2.8 x null SD), CAGR / worst fall, pp: 0003 19.4 / 26.9, 0007 17.8 / 30.3, 0010 17.3 / 29.4, 0029 15.3 / 19.8.
- `rerun_draw.py --book SCMO_0003 --type N4.9 --id 17 --cost 20.8` reproduces its stored row exactly.
- Curves: `draw_curves_20.8.npz` holds every headline draw at 20.8 bps (float32); curves at 0 and 50 bps are not stored because `rerun_draw.py` reproduces any draw.
