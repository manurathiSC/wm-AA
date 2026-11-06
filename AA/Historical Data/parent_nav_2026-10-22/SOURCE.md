# Published parent NAVs, export of 2026-10-22

Four files supplied by Manu on 2026-10-23 as `Downloads/{3,7,10,29}.csv`, copied here byte for byte and renamed to their scid. Columns: `_id.scid, _id.date (YYYY/MM/DD), index`. Newest row first.

| File | scid | First date | Last date | Rows | Base | sha256 |
|---|---|---|---|---|---|---|
| SCMO_0003.csv | SCMO_0003 | 2019-01-02 | 2026-10-22 | 1,926 | 100 on 2019-01-02 | F12DC65DBBA9434328A616D06E046C5F84ED167CFCCF421722AD03747424F591 |
| SCMO_0007.csv | SCMO_0007 | 2019-01-04 | 2026-10-22 | 1,924 | 100 on 2019-01-04 | 4898737391ECF9320FEDE5FE976D14A20CE1827E08BA529E2A3DE9EC209926ED |
| SCMO_0010.csv | SCMO_0010 | 2019-01-02 | 2026-10-22 | 1,926 | 100 on 2019-01-02 | 184BC46F31ACF6F1B911F96AAB9EA15FBC411997B599E0814E2C1795F1132C0E |
| SCMO_0029.csv | SCMO_0029 | 2019-01-02 | 2026-10-22 | 1,926 | 100 on 2019-01-02 | 156FC872D159E0B37A961E6331EB695F22EDBBFF44C58AA59E94AEF51740B158 |

Source system and export query: not recorded (same open question as `parentIndices.csv`, F-AA-D09).

## Checked against the stored `Historical Data/parentIndices.csv` (2021-11-01 → 2026-08-21, base 100 on 2021-11-01)

| scid | Common dates | Dates in one file only | Scale, new ÷ stored (min = max) | Largest daily-return difference |
|---|---|---|---|---|
| SCMO_0003 | 1,186 | 0 | 1.815000 | < 1e-11 bp |
| SCMO_0007 | 1,186 | 0 | 1.653597 | < 1e-11 bp |
| SCMO_0010 | 1,186 | 0 | 2.319671 | < 1e-11 bp |
| SCMO_0029 | 1,186 | 0 | 2.274629 | < 1e-11 bp |

Same series: only the base differs (the stored file is this one ÷ its value on 2021-11-01). To put a level from here on the stored base, divide by the value on 2021-11-01.

## Calendar (against `frozen_2026-09-25/Data/calendar.csv`, the .NSEI list)

- Absent here, present in the .NSEI list (same in all four): 2019-10-27, 2020-11-14, 2021-11-04, 2022-10-24, 2024-11-01, 2025-10-21 (Diwali muhurat sessions) and 2024-05-18 (special Saturday session). The stored file skipped the in-window ones too.
- Present here, absent from the .NSEI list: 2020-02-01, 2025-02-01 (Budget Saturdays), 2026-02-01 (Budget Sunday). Real sessions the .NSEI list misses (F-AA-D02).
- 2024-01-20 (special Saturday session) is in both.
- 22 rows after the list's last date (2026-09-18).
- No duplicates, no blank or non-positive values. Largest daily moves are real market days: 2020-03-23 (−11% to −16%), 2024-06-04 (election results, −8% to −13%), 2020-03-12.

## What this changes

Published parent NAVs now exist from **2019-01-02** (0007: 2019-01-04), not 2021-11-01, and run to 2026-10-22.
