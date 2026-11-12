# T07 Plan v2: segment holding against a random exclusion of the same weight, with the tag source and its review defined

**Written 2026-11-11. Nothing in this plan has been run, no data has been pulled, and no file outside `AA/tests/T07/` has been changed.** Revises `PLAN.md` (kept beside it, per `AA/CLAUDE.md`). **Where the two differ, this file wins; everything in `PLAN.md` not mentioned here stands.** The frozen design will be `T07.md` §1-§3 (Step 1).

## What changed from PLAN.md (Manu, 2026-11-09 to 2026-11-11)

1. **Both tag sources are used; there is a seam.** `PLAN.md` decision 3 and the "rank throughout" idea are replaced. The seam is disclosed on the page.
2. **The tag rule is fixed (below).** No six-month average and no semi-annual reconstitution of the ranks: the latest snapshot on or before the date, as Study 3 did.
3. **The membership snapshots are approved for use, not only for validation,** and the reviewer is an independent agent.
4. **Going forward the tags update only from `index_constituents_monthly`.**
5. **A data-review stage (Steps 0A-0F) precedes Step 1.** T07 does not start until it ends.

Unchanged: the fixed 50/50 GOLDBEES and cash sleeve and nothing else; segments on the three approved indices (Large to Nifty 100, Mid to Midcap 100, Small and below to Smallcap 100); the four parents only; the old Study 3 page kept and marked superseded; the nulls, criteria, controls, outcome map and step structure of `PLAN.md`.

## The tag rule (to be frozen in T07.md §3)

Let `cutoff` = the first `snapshot_date` in `index_constituents_monthly` (to be read from the table at the pull; the `mcap_ranks.py` docstring says 2026-04-09).

- **On or after `cutoff`:** the tag of a holding on date d is the index its ISIN is listed in, in the latest snapshot with `snapshot_date <= d`. Nifty 100 gives Large, Midcap 150 gives Mid, Smallcap 250 or Microcap 250 gives Small and below. A stock in none of the four indices uses its rank band (rule below) and is counted separately.
- **Before `cutoff`:** the tag is the band of the stock's rank in the latest `mcap_based_universe` snapshot with `date <= d`: rank 1-100 Large, 101-250 Mid, above 250 Small and below. Rank is over **ordinary shares only** (`instrument_class == 'ordinary'`), by market cap, with no averaging. ISINs follow `symbology_changes`. A stock with no rank reads Small and below, and is counted by name.
- **Tags are rebuilt only at events** (a flip of any of the three signals, a parent rebalance, the first review). Between events a book drifts and a tag never changes by itself.
- **Point-in-time:** no snapshot dated after d is ever used. The rule is checked in code.
- **Open (see below):** what the tag source is for a window date after the last membership snapshot.

## Data-review stage (Steps 0A-0F; nothing here touches an APPROVED row until 0F)

New data items, with IDs continuing from D19: **D20** raw `mcap_based_universe` pull (date, ticker, ISIN, mcap, instrument class); **D21** `index_constituents_monthly` (all snapshots); **D22** `symbology_changes` (ISIN renames); **D23** two **rule-independent panels** plus one shared lookup (changed 2026-11-11, so the data is reusable by any rule, not only the three-index rule): (a) the market-cap panel, one row per ordinary share per snapshot date (ISIN, date, mcap, rank, band; Large rank 1-100, Mid 101-250, Small and below above 250); (b) the membership panel, one row per ISIN per membership snapshot (index_name, band). A versioned, reviewed module `analysis/tag_lookup.py` gives "tag of ISIN x on date d" by the cutoff rule below. Nothing in D23 mentions events, parents, signals or weekly reviews. A test's own per-holding tags (which tag it used at each event) are that test's evidence, checked by its verifier, not an approved dataset.

| Step | Work | Who | Guardrail |
|---|---|---|---|
| 0A | Pull D20-D22 read-only into `Historical Data/extended_<date>/` as **candidates**, with a manifest (retrieved-at, query text, row counts, first and last date, sha256). `--check` mode writes nothing | Puller agent | Off-limits until 0F. Nothing is edited or re-fetched in place. Postgres creds are the read-only ones in `../wm-aiReports/.env` |
| 0B | Derive D23: the two panels from D20 and D21, and `tag_lookup.py` that applies the tag rule above | Puller agent | Script hashes recorded. Output is a separate file from the raw pull. No parent, event or signal enters the panels |
| 0C | **Data review**, using `data/data_review.py` extended with loaders for D20-D23; output in `data/review/<date>/`, verdicts in `review_decisions.json`, findings `F-AA-D16` onward | **Reviewer agent, a different agent from 0A/0B** | Read-only: it cannot edit data, register rows or touch `APPROVED_DATA.md`. It works from a written spec before it reads the puller's script |
| 0D | Independent rebuild of D23 from D20-D22 with the reviewer's own code | Reviewer agent | Must equal the puller's file on every row. Any difference is a FAIL |
| 0E | Register D20-D23 as `PENDING` in `APPROVED_DATA.md` (path, through-date, sha256 prefix from `check_approved_data.py --sha`, note), with a change-log line | Agent | Not usable yet |
| 0F | Manu says "approved". An agent flips the rows to `APPROVED`, extends `check_approved_data.py` to know the new formats, updates the "Latest usable date" table and the "As of" line, and runs `python data/check_approved_data.py` (must exit 0) | Manu, then an agent | Only Manu's message approves |

**Reviewer checks (each PASS or FAIL; overall PASS, PASS WITH NOTES or FAIL):**
1. **Schema and duplicates:** no duplicate (date, ISIN), no blank market caps, only ordinary shares ranked, no snapshot dated after its use.
2. **Exact tag check (hard gate, zero mismatches).** For every holding of the four parents on every date its basket is in effect (a rule-independent population, from D19 and D05, not the event dates of any rule), calling `tag_lookup.py`: before `cutoff`, the band of its rank in the latest `mcap_based_universe` snapshot on or before the date equals the tag; on or after `cutoff`, the index implied by the latest membership snapshot on or before the date equals the tag. Each miss is listed with stock, date, snapshot used, rank or index, and band.
3. **Independent rebuild equals the puller's file** (0D).
4. **Coverage.** The weight-weighted share of holdings, on every date a basket is in effect, that has a tag source, overall and per parent. Unranked names listed by name.
5. **Accuracy of the rank rule against real membership.** On the dates where both sources exist (the membership snapshots), the three-band agreement of the rank tags with the real membership, weight-weighted, with a confusion matrix. This is the figure the page quotes for the pre-`cutoff` tags.
6. **Calendar and stability:** snapshot gaps, rank jumps of more than two bands in a month (listed, not gated), a trace table of about 20 holdings across parents and years (raw market cap or membership, rank, band, signal), and a hand check of about 10 well-known names.
7. **Self-test:** the reviewer's own checks must catch a deliberately corrupted copy of D23.

**Thresholds (fixed by Manu before the reviewer sees any number; proposals in brackets):**
- Hard gates, zero tolerance: checks 1, 2 and 3.
- Coverage (proposal): PASS at 99% overall and 98% per parent; FAIL below 97%, or any single holding above 2% weight with no tag source.
- Accuracy (proposal revised 2026-11-11): earlier work, on the **three-bucket** scheme T07 uses and with no averaging (monthly re-rank), recorded 91.5-92.4% agreement with real membership (all 750 members, five 2026 snapshots; `analysis/evidence/main/METHODS.md` lines 998-1019) and 89.8% against production's own labels on holdings (`classify_validate.py` checks 1-2). The four-bucket figures (74.8-80.7%; 78.7% on holdings) are not T07's scheme. A PASS line of 90% overall sits on the edge of those figures, so **Manu sets the line before the pull.** Whatever it is, the figure is disclosed and the tag-error sensitivity (R5) is run at the measured rate. The reviewer recomputes the figure from approved files; the earlier numbers come from unapproved caches and are not re-used.
- **Decided (Manu, 2026-11-11):** the tag before the cutoff uses the latest `mcap_based_universe` snapshot **on or before the event date**, exactly as stored: no averaging and **no collapsing of the 2026 daily rows to month-end** (so the re-rank cadence is daily in Jan to Apr 2026 and month-end before that; the page says so). "Latest" never means the latest date in the table, only the latest on or before the event date. From the first membership snapshot on, tags come from `index_constituents_monthly`, and going forward only from it. Ties in market cap are broken by `quote_id` (not ISIN: 536 ordinary rows have a null ISIN; `quote_id` is never null). Rows with a null market cap (47) are not ranked; rows with a null ISIN or ticker are ranked and keep their rank position.

## Steps 1-6 (as PLAN.md, with these changes)

- **Step 1.** The pre-registration quotes the rule above, the reviewer's verdict, the D20-D23 sha256s, the cutoff date and the accuracy figure. It counts, before freezing: the weeks where the three signals disagree, the band sizes per book, and the number of holding-weeks on each side of the cutoff. Counts only, no returns.
- **Step 2 (engine).** Reads D23 only, through `approved_data.require()`, and gets every tag by calling the reviewed `tag_lookup.py` at its event dates; it does not recompute ranks. V4 regression adds: its tag for a sample of holdings equals a direct read of the D23 panels.
- **Step 3 (verifier).** Reads the D23 panels with its own lookup (not `tag_lookup.py`), re-applies them to the holdings, weights and signals and re-derives every target weight. It does not read the engine.
- **R5** relabels tags at the **measured accuracy** from reviewer check 5, with the rate and its source stated.
- Everything else in Steps 4-6 stands (scripts, run, write-up, `AA/ARTIFACTS.md` page 3 marked superseded, finding IDs from the counter at closing).

## Open items (nothing proceeds past these)

**Decided by Manu, 2026-11-12 ("I accept all of your recommendations"):**
1. **Pull (Step 0A):** an agent runs it with the read-only credentials. It first runs `--check`, which writes nothing, and shows Manu the summary; the write happens only after Manu has seen that summary. The files are candidates until Manu says "approved".
2. **Accuracy line:** PASS at 90% or more, PASS WITH NOTES at 85-90%, FAIL below 85% (three-band agreement with real membership, weight-weighted). If the result lands in the notes band, Manu decides whether to approve.
3. **Coverage line:** PASS at 99% overall and 98% per parent; PASS WITH NOTES from 97% to 99%; FAIL below 97% or if any single holding above 2% weight has no tag.
4. **Reviewer:** a fresh agent, working from a written spec, that does not read the puller's script until it has built its own version.

**Still open:**
4. **The window against the last membership snapshot.** The window would end 2026-10-30 (D03), but the table may stop earlier (the docstring says 2026-08-01). If so, tags after the last snapshot have no source. **Stop and ask Manu: do not carry the last snapshot forward silently.** The test window may have to end at the last snapshot.
5. The membership table's exact first date (the cutoff) and snapshot count, read at the pull.
6. Which index names count (Nifty 100, Midcap 150, Smallcap 250, Microcap 250) and how a stock in two indices is handled (Study 3's priority was Nifty 100, then Midcap 150, then Smallcap 250, then Microcap 250).
