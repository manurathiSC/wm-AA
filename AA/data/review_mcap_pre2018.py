"""Independent review of the PENDING candidates D20b and D23b (mcap_based_universe
2013-12-31 .. 2017-12-29, its rank panel, and the combined rank panel from 2013-12).

Run from AA/:  python -I data/review_mcap_pre2018.py [--stages 1,2,3,4,5,6,7,8,9]
Writes data/review/2026-11-17_mcap_pre2018/{results.json, trace_table.csv, *.csv}.
Scratch (rebuilt panels, corrupted copies) goes to --scratch (default: $REVIEW_SCRATCH).
Read-only for every data file. Postgres (stage 4) is a read-only session; credentials are
read from wm-aiReports/.env and never printed.

Written by the reviewer before opening data/pull_mcap_pre2018.py or data/build_tag_panels.py.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import random
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

AA = Path(__file__).resolve().parents[1]
HD = AA / "Historical Data"
CAND = HD / "extended_2026-11-17" / "mcap_universe_from_2013-12"
D20B = CAND / "mcap_universe_ordinary_2013-12_2017-12.csv"
D23B_PRE = CAND / "mcap_rank_panel_2013-12_2017-12.csv"
D23B_COMB = CAND / "mcap_rank_panel_from_2013-12.csv"
MANIFEST = CAND / "manifest.json"
D20 = HD / "extended_2026-11-12" / "mcap_universe" / "mcap_universe_ordinary.csv"
D23 = HD / "extended_2026-11-12" / "tags" / "mcap_rank_panel.csv"
D23M = HD / "extended_2026-11-12" / "tags" / "membership_panel.csv"
D22 = HD / "extended_2026-11-12" / "symbology" / "symbology_changes.csv"
D26 = HD / "extended_2026-11-12" / "index_daily_pre2019" / "nse_trading_days.csv"
REG = AA / "data" / "APPROVED_DATA.md"
HOLD = AA / "data" / "holdings_matrix"
PARENTS = ["0003", "0007", "0010", "0029"]
OUT = AA / "data" / "review" / "2026-11-17_mcap_pre2018"
RANK_COLS = ["date", "quote_id", "isin", "ticker", "mcap", "rank", "n_ranked", "band"]

R: dict = {}  # results


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def band_of(rank):
    if rank is None or (isinstance(rank, float) and np.isnan(rank)):
        return "unranked"
    rank = int(rank)
    return "Large" if rank <= 100 else ("Mid" if rank <= 250 else "Small and below")


def read_str(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def log(*a):
    print(*a, flush=True)


# --------------------------------------------------------------------------------------
# My own ranking (written from the rule in CLAUDE.md / APPROVED_DATA.md, not from code)
# --------------------------------------------------------------------------------------
def my_rank(raw: pd.DataFrame) -> pd.DataFrame:
    """raw: string frame with date, quote_id, isin, ticker, mcap. Rank 1 = largest mcap,
    ties by quote_id ascending, null mcap not ranked; band 1-100 Large, 101-250 Mid, >250."""
    d = raw[["date", "quote_id", "isin", "ticker", "mcap"]].copy()
    d = d[d["mcap"] != ""].copy()
    d["mcap_f"] = d["mcap"].astype(float)
    d["qid"] = d["quote_id"].astype(np.int64)
    d = d.sort_values(["date", "mcap_f", "qid"], ascending=[True, False, True], kind="mergesort")
    d["rank"] = d.groupby("date").cumcount() + 1
    d["n_ranked"] = d.groupby("date")["rank"].transform("size")
    d["band"] = np.where(d["rank"] <= 100, "Large", np.where(d["rank"] <= 250, "Mid", "Small and below"))
    return d.reset_index(drop=True)


def compare_rank(mine: pd.DataFrame, theirs_str: pd.DataFrame, label: str) -> dict:
    """Row-for-row and keyed comparison of my rank panel against a candidate file (strings)."""
    t = theirs_str.copy()
    res = {"label": label, "rows_mine": int(len(mine)), "rows_theirs": int(len(t))}
    res["columns_theirs"] = list(t.columns)
    res["columns_ok"] = list(t.columns) == RANK_COLS
    t["qid"] = t["quote_id"].astype(np.int64)
    t["mcap_f"] = pd.to_numeric(t["mcap"], errors="coerce")
    t["rank_i"] = pd.to_numeric(t["rank"], errors="coerce")
    t["n_i"] = pd.to_numeric(t["n_ranked"], errors="coerce")
    key = ["date", "qid"]
    res["dup_keys_theirs"] = int(t.duplicated(key).sum())
    res["dup_keys_mine"] = int(mine.duplicated(key).sum())
    m = mine[["date", "qid", "isin", "ticker", "mcap_f", "rank", "n_ranked", "band"]].merge(
        t[["date", "qid", "isin", "ticker", "mcap_f", "rank_i", "n_i", "band"]],
        on=key, how="outer", suffixes=("_m", "_t"), indicator=True)
    res["only_mine"] = int((m["_merge"] == "left_only").sum())
    res["only_theirs"] = int((m["_merge"] == "right_only").sum())
    b = m[m["_merge"] == "both"]
    diffs = {
        "isin": int((b["isin_m"] != b["isin_t"]).sum()),
        "ticker": int((b["ticker_m"] != b["ticker_t"]).sum()),
        "mcap": int((b["mcap_f_m"] != b["mcap_f_t"]).sum()),
        "rank": int((b["rank"] != b["rank_i"]).sum()),
        "n_ranked": int((b["n_ranked"] != b["n_i"]).sum()),
        "band": int((b["band_m"] != b["band_t"]).sum()),
    }
    res["field_diffs"] = diffs
    res["mcap_max_abs_diff"] = float((b["mcap_f_m"] - b["mcap_f_t"]).abs().max()) if len(b) else None
    # row order: same sequence of (date, quote_id)?
    same_len = len(mine) == len(t)
    res["row_order_identical"] = bool(same_len and np.array_equal(mine["date"].values, t["date"].values)
                                      and np.array_equal(mine["qid"].values, t["qid"].values))
    # band consistent with rank inside their file
    res["their_band_vs_their_rank_bad"] = int((t["band"] != t["rank_i"].map(band_of)).sum())
    res["total_differences"] = (res["only_mine"] + res["only_theirs"] + res["dup_keys_theirs"]
                                + sum(diffs.values()) + (0 if res["columns_ok"] else 1)
                                + (0 if res["row_order_identical"] else 1))
    bad = m[(m["_merge"] != "both") | (m["isin_m"] != m["isin_t"]) | (m["ticker_m"] != m["ticker_t"])
            | (m["mcap_f_m"] != m["mcap_f_t"]) | (m["rank"] != m["rank_i"]) | (m["n_ranked"] != m["n_i"])
            | (m["band_m"] != m["band_t"])]
    return res, bad


# --------------------------------------------------------------------------------------
# Check 1
# --------------------------------------------------------------------------------------
def check1(raw: pd.DataFrame, d20_header: list, mine: pd.DataFrame, cal: pd.Series):
    c = {}
    c["rows"] = int(len(raw))
    c["columns"] = list(raw.columns)
    c["columns_identical_to_D20"] = list(raw.columns) == d20_header
    c["instrument_class_values"] = raw["instrument_class"].value_counts().to_dict()
    c["instrument_type_values"] = raw["instrument_type"].value_counts().to_dict()
    c["nulls_per_column"] = {col: int((raw[col] == "").sum()) for col in raw.columns}
    # where nulls sit
    nm = raw[raw["mcap"] == ""]
    c["null_mcap_rows_by_year"] = nm["date"].str[:4].value_counts().sort_index().to_dict()
    c["null_mcap_quote_ids"] = sorted(nm["quote_id"].unique().tolist())
    c["null_mcap_tickers"] = sorted(nm["ticker"].unique().tolist())
    best = mine.groupby("quote_id")["rank"].min()
    allrk = mine.groupby("quote_id")["rank"].agg(["min", "median", "max", "size"])
    c["null_mcap_stocks_rank_elsewhere"] = {
        q: ({"ticker": nm[nm.quote_id == q].ticker.iloc[0], "null_dates": nm[nm.quote_id == q].date.tolist(),
             "best_rank_other_snapshots": int(allrk.loc[q, "min"]), "median_rank": float(allrk.loc[q, "median"]),
             "n_ranked_snapshots": int(allrk.loc[q, "size"])} if q in allrk.index else
            {"ticker": nm[nm.quote_id == q].ticker.iloc[0], "null_dates": nm[nm.quote_id == q].date.tolist(),
             "best_rank_other_snapshots": None})
        for q in c["null_mcap_quote_ids"]}
    # neighbouring snapshots specifically
    dates = sorted(raw["date"].unique())
    pos = {d: i for i, d in enumerate(dates)}
    rk = mine.set_index(["quote_id", "date"])["rank"]
    neigh = []
    for _, r in nm.iterrows():
        i = pos[r["date"]]
        for j in (i - 1, i + 1):
            if 0 <= j < len(dates) and (r["quote_id"], dates[j]) in rk.index:
                neigh.append(int(rk[(r["quote_id"], dates[j])]))
    c["null_mcap_neighbour_ranks_min"] = min(neigh) if neigh else None
    c["null_mcap_any_top250_on_neighbour"] = bool(neigh and min(neigh) <= 250)
    ni = raw[raw["isin"] == ""]
    c["null_isin_rows"] = int(len(ni))
    c["null_ticker_rows"] = int((raw["ticker"] == "").sum())
    # duplicates
    c["dup_date_quote_id"] = int(raw.duplicated(["date", "quote_id"]).sum())
    nn = raw[raw["isin"] != ""]
    c["dup_date_isin_nonnull"] = int(nn.duplicated(["date", "isin"]).sum())
    c["dup_full_rows"] = int(raw.duplicated().sum())
    c["dup_date_instrument_id"] = int(raw.duplicated(["date", "instrument_id"]).sum())
    c["dup_date_ticker_nonnull"] = int(raw[raw.ticker != ""].duplicated(["date", "ticker"]).sum())
    # values
    mc = pd.to_numeric(raw["mcap"].replace("", np.nan))
    cl = pd.to_numeric(raw["close"].replace("", np.nan))
    sc = pd.to_numeric(raw["mcap_scaled_in_cr"].replace("", np.nan))
    c["mcap_le_0"] = int((mc <= 0).sum())
    c["close_le_0"] = int((cl <= 0).sum())
    c["close_null"] = int(cl.isna().sum())
    rel = ((mc / 1e7) - sc).abs() / sc
    c["mcap_vs_scaled_max_rel_diff"] = float(rel.max())
    c["mcap_vs_scaled_max_abs_diff_cr"] = float(((mc / 1e7) - sc).abs().max())
    c["mcap_vs_scaled_null_mismatch"] = int((mc.isna() != sc.isna()).sum())
    c["mcap_min_cr"] = float(sc.min())
    c["mcap_max_cr"] = float(sc.max())
    # snapshot dates
    c["n_snapshots"] = len(dates)
    months = pd.Series(dates).str[:7]
    c["months_with_more_than_one"] = months[months.duplicated()].tolist()
    exp_months = pd.period_range("2013-12", "2017-12", freq="M").astype(str).tolist()
    c["months_missing"] = sorted(set(exp_months) - set(months))
    c["months_extra"] = sorted(set(months) - set(exp_months))
    calm = cal.groupby(cal.str[:7]).max()
    sess = set(cal)
    rows = []
    for d in dates:
        last = calm.get(d[:7])
        wd = pd.Timestamp(d).day_name()
        rows.append({"date": d, "weekday": wd, "is_session": d in sess, "last_session_of_month": last,
                     "ok": d == last, "n_rows": int((raw.date == d).sum())})
    c["snapshot_calendar"] = rows
    c["snapshots_not_last_session"] = [r for r in rows if not r["ok"]]
    c["snapshots_not_weekday"] = [r for r in rows if r["weekday"] in ("Saturday", "Sunday")]
    # ties at band edges
    t = mine.copy()
    t["tie"] = t.duplicated(["date", "mcap_f"], keep=False)
    ties = t[t["tie"]]
    c["tied_rows"] = int(len(ties))
    c["tied_rows_rank_le_260"] = int((ties["rank"] <= 260).sum())
    edge = []
    for (d, mcv), g in ties.groupby(["date", "mcap_f"]):
        rs = sorted(g["rank"].tolist())
        bands = set(g["band"])
        if len(bands) > 1:
            edge.append({"date": d, "mcap": mcv, "ranks": rs, "bands": sorted(bands)})
    c["ties_straddling_band_edge"] = edge
    c["tied_min_rank"] = int(ties["rank"].min()) if len(ties) else None
    # gap at the edges: ratio of mcap at rank 100 vs 101 and 250 vs 251
    gaps = []
    for d, g in mine.groupby("date"):
        g = g.set_index("rank")["mcap_f"]
        gaps.append({"date": d, "r100": g.get(100), "r101": g.get(101), "r250": g.get(250), "r251": g.get(251)})
    gp = pd.DataFrame(gaps)
    c["min_rel_gap_100_101"] = float(((gp.r100 - gp.r101) / gp.r100).min())
    c["min_rel_gap_250_251"] = float(((gp.r250 - gp.r251) / gp.r250).min())
    R["check1"] = c
    return c


# --------------------------------------------------------------------------------------
# Check 2
# --------------------------------------------------------------------------------------
def check2(raw: pd.DataFrame, d20raw: pd.DataFrame):
    c = {}
    ua = pd.to_datetime(raw["updated_at"])
    dt = pd.to_datetime(raw["date"])
    lag = (ua - dt).dt.days
    c["updated_at_min"] = str(ua.min())
    c["updated_at_max"] = str(ua.max())
    c["updated_at_distinct_days"] = sorted(ua.dt.date.astype(str).unique().tolist())
    c["updated_at_distinct_values"] = int(ua.nunique())
    yr = raw["date"].str[:4]
    tab = []
    for y in sorted(yr.unique()):
        s = yr == y
        tab.append({"year": y, "rows": int(s.sum()), "lag_min": int(lag[s].min()), "lag_median": float(lag[s].median()),
                    "lag_max": int(lag[s].max()), "written_from": str(ua[s].min()), "written_to": str(ua[s].max())})
    c["lag_by_year"] = tab
    # per snapshot: updated_at per date (batch structure)
    per = raw.assign(ua=ua).groupby("date")["ua"].agg(["min", "max", "nunique"])
    c["per_snapshot_updated_at_nunique_max"] = int(per["nunique"].max())
    c["per_snapshot_write_order_monotone"] = bool(per["min"].is_monotonic_increasing)
    c["first_snapshot_written"] = str(per["min"].iloc[0])
    c["last_snapshot_written"] = str(per["max"].iloc[-1])
    # D20's 2018 vintage for comparison
    d20_18 = d20raw[d20raw.date.str[:4] == "2018"]
    ua20 = pd.to_datetime(d20_18["updated_at"])
    c["D20_2018_written_from"] = str(ua20.min())
    c["D20_2018_written_to"] = str(ua20.max())
    # universe size
    sz = raw.groupby("date").size()
    ranked = raw[raw.mcap != ""].groupby("date").size()
    c["universe_size_min"] = {"date": sz.idxmin(), "n": int(sz.min())}
    c["universe_size_max"] = {"date": sz.idxmax(), "n": int(sz.max())}
    c["universe_size_by_date"] = {d: int(v) for d, v in sz.items()}
    mom = sz.pct_change().abs()
    c["universe_size_max_month_change_pct"] = {"date": mom.idxmax(), "pct": float(mom.max() * 100)}
    d20sz = d20raw.groupby("date").size()
    c["D20_first_snapshot_size"] = {"date": d20sz.index[0], "n": int(d20sz.iloc[0])}
    c["join_size_change_pct"] = float((d20sz.iloc[0] / sz.iloc[-1] - 1) * 100)
    c["D20_monthly_2018_size_range"] = [int(d20sz[d20sz.index.str[:4] == "2018"].min()),
                                       int(d20sz[d20sz.index.str[:4] == "2018"].max())]
    # survivorship: delisted (^ in ric)
    dl = raw["ric"].str.contains(r"\^", regex=True)
    c["delisted_ric_share_by_year"] = {y: float(dl[yr == y].mean()) for y in sorted(yr.unique())}
    first = raw[raw.date == raw.date.min()]
    c["first_snapshot_delisted_ric"] = int(first["ric"].str.contains(r"\^", regex=True).sum())
    # quote_ids present on the last pre-2018 snapshot but absent from 2018-01-31, and vice versa
    last = set(raw[raw.date == raw.date.max()].quote_id)
    f18 = set(d20raw[d20raw.date == d20raw.date.min()].quote_id)
    c["join_qids_leaving"] = len(last - f18)
    c["join_qids_entering"] = len(f18 - last)
    # entries / exits per month in D20b (new quote_ids appear, old disappear)
    dates = sorted(raw.date.unique())
    by = {d: set(raw[raw.date == d].quote_id) for d in dates}
    ent = [len(by[b] - by[a]) for a, b in zip(dates, dates[1:])]
    ex = [len(by[a] - by[b]) for a, b in zip(dates, dates[1:])]
    c["monthly_entries_median_max"] = [float(np.median(ent)), int(max(ent))]
    c["monthly_exits_median_max"] = [float(np.median(ex)), int(max(ex))]
    d20m = sorted(d for d in d20raw.date.unique() if d < "2025-12-01")
    by20 = {d: set(d20raw[d20raw.date == d].quote_id) for d in d20m}
    ent20 = [len(by20[b] - by20[a]) for a, b in zip(d20m, d20m[1:])]
    ex20 = [len(by20[a] - by20[b]) for a, b in zip(d20m, d20m[1:])]
    c["D20_monthly_entries_median_max_2018_2025"] = [float(np.median(ent20)), int(max(ent20))]
    c["D20_monthly_exits_median_max_2018_2025"] = [float(np.median(ex20)), int(max(ex20))]
    # ISIN vintage: quote_ids whose ISIN in D20b differs from their latest ISIN in D20
    lastisin = d20raw[d20raw["isin"] != ""].sort_values("date").groupby("quote_id")["isin"].last()
    j = raw[raw["isin"] != ""].merge(lastisin.rename("isin_latest"), left_on="quote_id", right_index=True)
    c["rows_with_isin_differing_from_latest_D20_isin"] = int((j["isin"] != j["isin_latest"]).sum())
    c["quote_ids_with_isin_differing_from_latest"] = int(j[j["isin"] != j["isin_latest"]].quote_id.nunique())
    c["quote_ids_with_more_than_one_isin_within_D20b"] = int(raw[raw["isin"] != ""].groupby("quote_id").isin.nunique().gt(1).sum())
    R["check2"] = c
    return c


# --------------------------------------------------------------------------------------
# Check 3
# --------------------------------------------------------------------------------------
def registry_prefixes() -> dict:
    out = {}
    for line in REG.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(cells) >= 5 and re.fullmatch(r"[0-9a-f]{16}", cells[4] or ""):
            out[cells[2]] = {"status": cells[0], "id": cells[1], "sha16": cells[4], "through": cells[3]}
    return out


def check3(mine: pd.DataFrame, scratch: Path):
    c = {}
    pre = read_str(D23B_PRE)
    res, bad = compare_rank(mine, pre, "D23b pre-2018 vs my rebuild from D20b")
    c["rebuild_vs_pre2018"] = res
    if len(bad):
        bad.to_csv(OUT / "mismatches_check3_rebuild.csv", index=False)
    # write my rebuild in the candidate's format to scratch, compare bytes as a bonus
    my_out = mine[["date", "quote_id", "isin", "ticker", "mcap", "rank", "n_ranked", "band"]].copy()
    my_out["mcap"] = my_out["mcap"].astype(float).map(repr)
    p = scratch / "my_rank_panel_2013-12_2017-12.csv"
    my_out.to_csv(p, index=False, lineterminator="\n")
    c["my_rebuild_sha256"] = sha256(p)
    c["my_rebuild_bytes_equal_candidate"] = c["my_rebuild_sha256"] == sha256(D23B_PRE)
    # combined = pre rows + D23 rows, byte for byte
    bp = D23B_PRE.read_bytes()
    b23 = D23.read_bytes()
    bc = D23B_COMB.read_bytes()
    nl = b23.index(b"\n") + 1
    hdr_pre = bp[: bp.index(b"\n") + 1]
    c["headers_equal"] = hdr_pre == b23[:nl] == bc[: bc.index(b"\n") + 1]
    c["line_ending_crlf_any"] = (b"\r\n" in bp[:5000]) or (b"\r\n" in bc[:5000])
    c["pre_ends_with_newline"] = bp.endswith(b"\n")
    c["combined_len"] = len(bc)
    c["pre_len_plus_d23_body_len"] = len(bp) + len(b23) - nl
    c["combined_equals_pre_plus_d23_body"] = bc == bp + b23[nl:]
    c["sha256_combined_first_part"] = sha_bytes(bc[: len(bp)])
    c["sha256_pre_file"] = sha_bytes(bp)
    c["sha256_combined_second_part"] = sha_bytes(bc[len(bp):])
    c["sha256_d23_body"] = sha_bytes(b23[nl:])
    c["parts_match"] = (c["sha256_combined_first_part"] == c["sha256_pre_file"]
                        and c["sha256_combined_second_part"] == c["sha256_d23_body"])
    # also row-level: combined row count
    c["combined_rows"] = bc.count(b"\n") - 1
    c["pre_rows"] = bp.count(b"\n") - 1
    c["d23_rows"] = b23.count(b"\n") - 1
    # sha vs registry and manifest
    reg = registry_prefixes()
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    shas = {}
    for f, rel in [(D20B, None), (D23B_PRE, None), (D23B_COMB, None), (D20, None), (D23, None)]:
        relp = str(f.relative_to(AA)).replace("\\", "/")
        full = sha256(f)
        e = {"sha256": full, "registry": reg.get(relp), "registry_match": reg.get(relp, {}).get("sha16") == full[:16]}
        mf = man["files"].get(f.name)
        if mf:
            e["manifest_sha256"] = mf["sha256"]
            e["manifest_match"] = mf["sha256"] == full
            e["manifest_rows"] = mf["rows"]
        shas[relp] = e
    shas["manifest_inputs"] = {k: v for k, v in man["inputs"].items()}
    shas["manifest_inputs_match"] = (man["inputs"]["D20 mcap_universe_ordinary.csv"] == sha256(D20)
                                     and man["inputs"]["D23 mcap_rank_panel.csv"] == sha256(D23))
    c["sha256"] = shas
    c["manifest_rows_match"] = (man["files"][D20B.name]["rows"] == R["check1"]["rows"]
                                and man["files"][D23B_PRE.name]["rows"] == c["pre_rows"]
                                and man["files"][D23B_COMB.name]["rows"] == c["combined_rows"])
    c["hard_gate_zero_differences"] = (res["total_differences"] == 0 and c["combined_equals_pre_plus_d23_body"]
                                       and c["parts_match"] and all(v.get("registry_match", True) and v.get("manifest_match", True)
                                                                    for k, v in shas.items() if isinstance(v, dict) and "sha256" in v)
                                       and shas["manifest_inputs_match"])
    R["check3"] = c
    return c


def load_calendar() -> pd.Series:
    return read_str(D26)["date"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stages", default="1,2,3,4,5,6,7,8,9")
    ap.add_argument("--scratch", default=os.environ.get("REVIEW_SCRATCH", ""))
    a = ap.parse_args()
    stages = {int(x) for x in a.stages.split(",")}
    scratch = Path(a.scratch) if a.scratch else None
    if scratch is None:
        sys.exit("--scratch (or REVIEW_SCRATCH) is required: corrupted copies must not go in the repo")
    scratch.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    raw = read_str(D20B)
    d20raw = read_str(D20)
    cal = load_calendar()
    mine = my_rank(raw)
    if 1 in stages:
        log("check 1"); check1(raw, list(d20raw.columns), mine, cal)
    if 2 in stages:
        log("check 2"); check2(raw, d20raw)
    if 3 in stages:
        log("check 3"); check3(mine, scratch)
    STAGES_EXTRA(stages, raw, d20raw, cal, mine, scratch)
    R["runtime_s"] = round(time.time() - t0, 1)
    resp = OUT / "results.json"
    old = json.loads(resp.read_text(encoding="utf-8")) if resp.exists() else {}
    old.update(R)
    resp.write_text(json.dumps(old, indent=1, default=str), encoding="utf-8")
    log("done", R["runtime_s"], "s")


# --------------------------------------------------------------------------------------
# Check 4: provenance (read-only Postgres)
# --------------------------------------------------------------------------------------
ENV = Path(r"c:\Users\manur\Repos\wm-aiReports\.env")


def pg_connect():
    import psycopg2
    env = {}
    for line in ENV.read_text().splitlines():
        line = line.strip()
        if line.startswith("PG_PRICE_") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip("\"'")
    c = psycopg2.connect(host=env["PG_PRICE_HOST"], port=env["PG_PRICE_PORT"], dbname=env["PG_PRICE_DBNAME"],
                         user=env["PG_PRICE_USER"], password=env["PG_PRICE_PASSWORD"], connect_timeout=30)
    c.set_session(readonly=True)
    return c


def _canon_dec(x) -> str:
    from decimal import Decimal
    if x is None or x == "":
        return ""
    d = x if isinstance(x, Decimal) else Decimal(str(x))
    if d.is_nan():
        return "NaN"
    return "{:f}".format(d.normalize()) if d != 0 else "0"


def db_canon(rows, desc) -> pd.DataFrame:
    """Canonical string per value: numerics normalised, timestamps parsed, NULL = ''."""
    import datetime as _dt
    from decimal import Decimal
    cols = [d[0] for d in desc]
    out = {}
    arr = list(zip(*rows)) if rows else [[] for _ in cols]
    for c, vals in zip(cols, arr):
        sample = next((v for v in vals if v is not None), None)
        if isinstance(sample, Decimal) or isinstance(sample, float):
            out[c] = [_canon_dec(v) for v in vals]
        elif isinstance(sample, _dt.datetime):
            out[c] = [("" if v is None else pd.Timestamp(v).isoformat()) for v in vals]
        elif isinstance(sample, _dt.date):
            out[c] = [("" if v is None else v.isoformat()) for v in vals]
        else:
            out[c] = [("" if v is None else str(v)) for v in vals]
    return pd.DataFrame(out, columns=cols)


def csv_canon(df: pd.DataFrame, numeric: list, ts: list) -> pd.DataFrame:
    o = df.copy()
    for c in numeric:
        o[c] = [_canon_dec(v) for v in o[c]]
    for c in ts:
        o[c] = [("" if v == "" else pd.Timestamp(v).isoformat()) for v in o[c]]
    return o


def compare_db(csvdf: pd.DataFrame, dbdf: pd.DataFrame, label: str):
    res = {"label": label, "rows_file": int(len(csvdf)), "rows_db": int(len(dbdf)),
           "columns_file": list(csvdf.columns), "columns_db": list(dbdf.columns),
           "columns_equal_in_order": list(csvdf.columns) == list(dbdf.columns)}
    key = ["date", "quote_id"]
    res["dup_keys_db"] = int(dbdf.duplicated(key).sum())
    m = csvdf.merge(dbdf, on=key, how="outer", suffixes=("_f", "_db"), indicator=True)
    res["only_in_file"] = int((m["_merge"] == "left_only").sum())
    res["only_in_db"] = int((m["_merge"] == "right_only").sum())
    b = m[m["_merge"] == "both"]
    diffs, examples = {}, {}
    for c in [c for c in csvdf.columns if c not in key and c in dbdf.columns]:
        a1, a2 = b[f"{c}_f"], b[f"{c}_db"]
        if c in ("mcap", "mcap_scaled_in_cr", "close"):
            a2 = a2.replace("NaN", "")  # the CSV writes NULL and numeric NaN both as an empty cell
        bad = a1 != a2
        diffs[c] = int(bad.sum())
        if bad.any():
            examples[c] = b.loc[bad, key + [f"{c}_f", f"{c}_db"]].head(5).to_dict("records")
    res["value_diffs_per_column"] = diffs
    res["examples"] = examples
    res["cells_compared"] = int(len(b) * len(diffs))
    res["identical"] = (res["only_in_file"] == 0 and res["only_in_db"] == 0 and sum(diffs.values()) == 0
                        and res["columns_equal_in_order"] and res["dup_keys_db"] == 0)
    return res, m[(m["_merge"] != "both")][key + ["_merge"]]


def check4(raw: pd.DataFrame, d20raw: pd.DataFrame, mine: pd.DataFrame):
    c = {}
    cols = list(raw.columns)
    sel = ", ".join(cols)
    conn = pg_connect()
    cur = conn.cursor()
    cur.execute("SHOW transaction_read_only")
    c["session_read_only"] = cur.fetchone()[0]
    # my own query: explicit columns, BETWEEN, no class filter (filtered here after counting classes)
    cur.execute(f"SELECT {sel} FROM public.mcap_based_universe WHERE date BETWEEN %s AND %s",
                ("2013-12-01", "2017-12-31"))
    rows = cur.fetchall()
    desc = cur.description
    db = db_canon(rows, desc)
    c["db_rows_all_classes_2013-12-01_2017-12-31"] = int(len(db))
    c["db_class_counts"] = db["instrument_class"].value_counts().to_dict()
    dbo = db[db["instrument_class"] == "ordinary"].reset_index(drop=True)
    cur.execute("SELECT count(*) FILTER (WHERE mcap IS NULL), count(*) FILTER (WHERE mcap = 'NaN'::numeric), "
                "count(*) FILTER (WHERE isin IS NULL), count(*) FILTER (WHERE isin = '') "
                "FROM public.mcap_based_universe WHERE date BETWEEN %s AND %s AND instrument_class = 'ordinary'",
                ("2013-12-01", "2017-12-31"))
    a = cur.fetchone()
    c["db_null_mcap_sql_null"], c["db_null_mcap_numeric_nan"], c["db_isin_null"], c["db_isin_empty"] = map(int, a)
    cur.execute("SELECT min(date), max(date), count(*) FROM public.mcap_based_universe")
    mn, mx, n = cur.fetchone()
    c["table_min_date"], c["table_max_date"], c["table_rows_now"] = str(mn), str(mx), int(n)
    cur.execute("SELECT count(*), count(DISTINCT date) FROM public.mcap_based_universe WHERE date < '2013-12-01'")
    c["table_rows_before_2013-12-01"] = list(map(int, cur.fetchone()))
    cur.execute("SELECT count(*) FROM public.mcap_based_universe WHERE date > '2017-12-29' AND date < '2018-01-31'")
    c["table_rows_between_2017-12-29_and_2018-01-31"] = int(cur.fetchone()[0])
    # rows left out by the class filter: would any of them sit in the top 250 of the ordinary universe?
    nonord = db[(db["instrument_class"] != "ordinary") & (db["instrument_class"] != "etf")].copy()
    nonord["mcap_f"] = pd.to_numeric(nonord["mcap"].replace({"": np.nan, "NaN": np.nan}))
    lst = []
    for _, r in nonord.iterrows():
        pool = mine[mine["date"] == r["date"]]["mcap_f"]
        would = int((pool > r["mcap_f"]).sum() + 1) if pd.notna(r["mcap_f"]) else None
        lst.append({"date": r["date"], "ticker": r["ticker"], "name": r["full_name"], "class": r["instrument_class"],
                    "type": r["instrument_type"], "would_rank": would})
    nl = pd.DataFrame(lst)
    c["non_ordinary_non_etf_rows"] = int(len(nl))
    if len(nl):
        g = nl.groupby(["ticker", "name", "class", "type"])["would_rank"].agg(["min", "size"]).reset_index()
        c["non_ordinary_by_stock"] = g.sort_values("min").to_dict("records")
        c["non_ordinary_best_would_rank"] = None if nl["would_rank"].isna().all() else int(nl["would_rank"].min())
    num = ["close", "mcap", "mcap_scaled_in_cr"]
    ts = ["updated_at"]
    f = csv_canon(raw, num, ts)
    r1, miss1 = compare_db(f, dbo, "D20b vs DB 2013-12-01..2017-12-31 ordinary")
    c["D20b_vs_db"] = r1
    # D20 window
    cur.execute(f"SELECT {sel} FROM public.mcap_based_universe WHERE date >= %s AND date <= %s AND instrument_class = 'ordinary'",
                ("2018-01-01", "2026-11-11"))
    rows = cur.fetchall()
    db2 = db_canon(rows, cur.description)
    cur.execute("SELECT count(*), count(DISTINCT date), max(updated_at) FROM public.mcap_based_universe "
                "WHERE date > '2026-11-11' AND instrument_class = 'ordinary'")
    a = cur.fetchone()
    c["db_rows_after_2026-11-11"] = {"rows": int(a[0]), "dates": int(a[1]), "max_updated_at": str(a[2])}
    cur.execute("SELECT max(updated_at) FROM public.mcap_based_universe WHERE date <= '2026-11-11'")
    c["db_max_updated_at_through_2026-11-11"] = str(cur.fetchone()[0])
    conn.close()
    f2 = csv_canon(d20raw, num, ts)
    r2, miss2 = compare_db(f2, db2, "D20 vs DB 2018-01-01..2026-11-11 ordinary")
    c["D20_vs_db"] = r2
    if len(miss1) or not r1["identical"]:
        miss1.to_csv(OUT / "mismatches_check4_D20b.csv", index=False)
    if len(miss2) or not r2["identical"]:
        miss2.to_csv(OUT / "mismatches_check4_D20.csv", index=False)
    c["hard_gate_D20b_equals_db"] = r1["identical"]
    R["check4"] = c
    return c


def STAGES_EXTRA(stages, raw, d20raw, cal, mine, scratch):
    if 4 in stages:
        log("check 4"); check4(raw, d20raw, mine)
    STAGES_5_9(stages, raw, d20raw, cal, mine, scratch)


# --------------------------------------------------------------------------------------
# Population: every holding of the four parents on every NSE session (D26)
# --------------------------------------------------------------------------------------
def population(cal: pd.Series, first="2014-03-03", last="2018-01-31") -> pd.DataFrame:
    sess = pd.DataFrame({"date": cal[(cal >= first) & (cal <= last)].tolist()})
    out = []
    for p in PARENTS:
        m = pd.read_csv(HOLD / f"SCMO_{p}_holding_weight_matrix.csv")
        cols = pd.read_csv(HOLD / f"SCMO_{p}_columns.csv", dtype=str, keep_default_na=False)
        src = pd.read_csv(HOLD / f"SCMO_{p}_holding_weight_sources.csv")
        skipped = set(src.loc[src["csv_skipped_flag"].astype(bool), "rebalance_date"])
        m = m[~m["rebalance_date"].isin(skipped)]
        long = m.melt(id_vars="rebalance_date", var_name="stock", value_name="weight")
        long = long[long["weight"].notna() & (long["weight"] > 0)]
        long = long.merge(cols[["stock", "ISIN", "name"]], on="stock", how="left")
        assert long["ISIN"].notna().all() and (long["ISIN"] != "").all(), f"{p}: stock without ISIN"
        bd = sorted(m["rebalance_date"].unique())
        s = sess.copy()
        idx = np.searchsorted(np.array(bd), s["date"].values, side="right") - 1
        s = s[idx >= 0].copy()
        s["basket"] = [bd[i] for i in idx[idx >= 0]]
        j = s.merge(long.rename(columns={"rebalance_date": "basket"}), on="basket")
        j["parent"] = "SCMO_" + p
        out.append(j)
    pop = pd.concat(out, ignore_index=True).rename(columns={"ISIN": "isin"})
    return pop[["parent", "date", "basket", "stock", "isin", "name", "weight"]]


# --------------------------------------------------------------------------------------
# My own tag lookup (rank part of the rule; used for dates before the 2026-04-09 cutoff)
# --------------------------------------------------------------------------------------
class MyTags:
    def __init__(self, panel: pd.DataFrame, sym: pd.DataFrame):
        """panel columns: date (str), quote_id (int), isin (str, '' = none), rank (int), band."""
        self.dates = sorted(panel["date"].unique())
        self.by_isin: dict = defaultdict(lambda: defaultdict(list))
        self.by_q: dict = defaultdict(dict)
        for d, q, i, r, b in zip(panel["date"], panel["quote_id"], panel["isin"], panel["rank"], panel["band"]):
            q = int(q); r = int(r)
            self.by_q[d][q] = (r, b, i)
            if i:
                self.by_isin[d][i].append((r, q, b))
        qi: dict = defaultdict(set)
        for col in ("isin", "new_isin"):
            for i, q in zip(sym[col], sym["quote_id"]):
                if i and q != "":
                    qi[i].add(int(float(q)))
        for i, q in zip(panel["isin"], panel["quote_id"]):
            if i:
                qi[i].add(int(q))
        iq: dict = defaultdict(set)
        for i, qs in qi.items():
            for q in qs:
                iq[q].add(i)
        self.qi, self.iq = qi, iq
        self.ambiguous = 0

    def tag(self, isin: str, asof: str) -> dict:
        if not isin:
            return {"band": "Small and below", "source": "unranked", "snapshot": None, "detail": None, "via": None}
        k = self._idx(asof)
        if k < 0:
            return {"band": "Small and below", "source": "unranked", "snapshot": None, "detail": None, "via": None}
        s = self.dates[k]
        hits = self.by_isin[s].get(isin)
        if hits:
            if len(hits) > 1:
                self.ambiguous += 1
            r, q, b = min(hits)
            return {"band": b, "source": "rank", "snapshot": s, "detail": r, "via": "isin"}
        qs = set(self.qi.get(isin, ()))
        aliases = set()
        for q in qs:
            aliases |= self.iq.get(q, set())
        cands = set(q for q in qs if q in self.by_q[s])
        for a in aliases - {isin}:
            for r, q, b in self.by_isin[s].get(a, []):
                cands.add(q)
        if not cands:
            return {"band": "Small and below", "source": "unranked", "snapshot": s, "detail": None, "via": None}
        if len(cands) > 1:
            self.ambiguous += 1
        r, b, _ = min(self.by_q[s][q] for q in cands)
        return {"band": b, "source": "rank", "snapshot": s, "detail": r, "via": "symbology"}

    def _idx(self, asof: str) -> int:
        import bisect
        return bisect.bisect_right(self.dates, asof) - 1


def load_their_lookup(rank_csv: Path):
    sys.path.insert(0, str(AA / "analysis"))
    from tag_lookup import TagLookup
    return TagLookup.from_files(rank_csv, D23M, D22)


def build_my_panel(mine: pd.DataFrame) -> pd.DataFrame:
    """My rebuild of 2013-12..2017-12 (from raw D20b) + the approved D23 rank panel."""
    d23 = read_str(D23)
    a = mine[["date", "quote_id", "isin", "rank", "band"]].copy()
    b = d23[["date", "quote_id", "isin", "rank", "band"]].copy()
    b["rank"] = b["rank"].astype(int)
    return pd.concat([a, b], ignore_index=True)


def norm_tag(t: dict) -> tuple:
    return (t["band"], t["source"], t["snapshot"], None if t["detail"] is None else int(t["detail"]), t["via"])


def run_tag_compare(pairs: list, mytags: MyTags, theirs) -> tuple[int, list]:
    bad = []
    for isin, d in pairs:
        a = norm_tag(mytags.tag(isin, d))
        b = norm_tag(theirs.tag(isin, d))
        if a != b:
            bad.append({"isin": isin, "date": d, "mine": a, "theirs": b})
    return len(pairs), bad


def sample_pairs(raw: pd.DataFrame, pop: pd.DataFrame, cal: pd.Series, sym: pd.DataFrame, seed=20261117) -> dict:
    rng = random.Random(seed)
    pop_isins = set(pop["isin"])
    isins_b = sorted(set(raw["isin"]) - {""})
    other = sorted(set(isins_b) - pop_isins)
    sym_isins = sorted((set(sym["isin"]) | set(sym["new_isin"])) - {""} - set(isins_b))
    snaps = sorted(raw["date"].unique())
    cals = list(cal)
    edge_dates = set()
    for s in snaps + ["2018-01-31"]:
        ts = pd.Timestamp(s)
        edge_dates.add(s)
        edge_dates.add(str((ts - pd.Timedelta(days=1)).date()))
        i = cals.index(s) if s in cals else None
        prev = [c for c in cals if c < s]
        if prev:
            edge_dates.add(prev[-1])
        nxt = [c for c in cals if c > s]
        if nxt:
            edge_dates.add(nxt[0])
    edge_dates |= {"2013-11-30", "2013-12-01", "2013-12-30", "2014-01-01", "2014-01-02", "2015-02-27", "2015-03-01",
                   "2015-03-02", "2016-10-29", "2016-10-31", "2017-12-31", "2018-01-01", "2018-01-30", "2018-02-01",
                   "2018-02-27", "2019-06-28", "2021-10-29", "2025-12-30", "2026-04-08"}
    edge_dates = sorted(edge_dates)
    out = {}
    # (a) random other ISINs x edge dates
    a = [(rng.choice(other), rng.choice(edge_dates)) for _ in range(40000)]
    # (b) random D20b ISINs x random calendar sessions 2013-12-02 .. 2018-02-28
    span = [c for c in cals if "2013-12-02" <= c <= "2018-02-28"]
    b = [(rng.choice(isins_b), rng.choice(span)) for _ in range(30000)]
    # (c) ISINs only in symbology (renamed / not in D20b) x edge dates
    c = [(rng.choice(sym_isins), rng.choice(edge_dates)) for _ in range(5000)]
    # (d) every ISIN of D20b whose quote_id carries another ISIN somewhere (renames), on every snapshot and the day before
    q_isins = defaultdict(set)
    for i, q in zip(raw["isin"], raw["quote_id"]):
        q_isins[q].add(i)
    d20 = read_str(D23)
    for i, q in zip(d20["isin"], d20["quote_id"]):
        if q in q_isins and i:
            q_isins[q].add(i)
    renamed = sorted({i for q, s in q_isins.items() if len(s) > 1 for i in s})
    d = [(i, dt) for i in renamed for dt in snaps[::4] + ["2017-12-28", "2017-12-29", "2018-01-30", "2018-01-31"]]
    # (e) unknown / empty ISINs
    e = [("INE000X00000", "2015-06-30"), ("", "2015-06-30"), ("XYZ", "2017-12-29")]
    out = {"random_other_isin_x_edge_dates": a, "random_D20b_isin_x_sessions": b, "symbology_only_isins_x_edge_dates": c,
           "renamed_isins_x_snapshots": d, "unknown_isins": e}
    return out, edge_dates, renamed


def check5(raw, cal, mine, mytags, theirs, pop, sym):
    c = {}
    pairs_pop = sorted(set(zip(pop["isin"], pop["date"])))
    t0 = time.time()
    n, bad = run_tag_compare(pairs_pop, mytags, theirs)
    c["population"] = {"holding_days": int(len(pop)), "distinct_isin_date": n, "mismatches": len(bad),
                       "distinct_isins": int(pop["isin"].nunique()), "sessions": int(pop["date"].nunique()),
                       "first": pop["date"].min(), "last": pop["date"].max(),
                       "per_parent_holding_days": pop.groupby("parent").size().to_dict(), "seconds": round(time.time() - t0, 1)}
    allbad = [dict(b, set="population") for b in bad]
    samples, edge_dates, renamed = sample_pairs(raw, pop, cal, sym)
    c["edge_dates_used"] = len(edge_dates)
    c["renamed_isins"] = len(renamed)
    tot = n
    totbad = len(bad)
    for name, pr in samples.items():
        n2, b2 = run_tag_compare(pr, mytags, theirs)
        c[name] = {"lookups": n2, "mismatches": len(b2)}
        tot += n2; totbad += len(b2)
        allbad += [dict(b, set=name) for b in b2]
    c["total_lookups"] = tot
    c["total_mismatches"] = totbad
    c["my_ambiguous_cases"] = mytags.ambiguous
    # source mix in the population (theirs)
    src = defaultdict(int); via = defaultdict(int)
    for isin, d in pairs_pop:
        t = theirs.tag(isin, d)
        src[t["source"]] += 1; via[str(t["via"])] += 1
    c["population_sources_distinct_pairs"] = dict(src)
    c["population_via_distinct_pairs"] = dict(via)
    if allbad:
        pd.DataFrame(allbad).to_csv(OUT / "mismatches_check5_tags.csv", index=False)
    c["hard_gate_zero_mismatches"] = totbad == 0
    R["check5"] = c
    return c


# --------------------------------------------------------------------------------------
# Check 6: coverage
# --------------------------------------------------------------------------------------
def check6(pop, theirs, raw, sym):
    c = {}
    p = pop[pop["date"] <= "2017-12-31"].copy()
    tags = {k: theirs.tag(*k) for k in set(zip(p["isin"], p["date"]))}
    p["source"] = [tags[(i, d)]["source"] for i, d in zip(p["isin"], p["date"])]
    p["band"] = [tags[(i, d)]["band"] for i, d in zip(p["isin"], p["date"])]
    p["snapshot"] = [tags[(i, d)]["snapshot"] for i, d in zip(p["isin"], p["date"])]
    p["ranked"] = p["source"] != "unranked"
    c["window"] = [p["date"].min(), p["date"].max()]
    c["holding_days"] = int(len(p))
    c["overall_weighted_pct"] = float(100 * (p["weight"] * p["ranked"]).sum() / p["weight"].sum())
    c["overall_count_pct"] = float(100 * p["ranked"].mean())
    per = {}
    for par, g in p.groupby("parent"):
        per[par] = {"holding_days": int(len(g)), "weighted_pct": float(100 * (g["weight"] * g["ranked"]).sum() / g["weight"].sum()),
                    "count_pct": float(100 * g["ranked"].mean())}
    c["per_parent"] = per
    c["thresholds"] = "PASS if overall >= 99% and every parent >= 98% (weight-weighted); a single unranked holding above 2% weight is listed"
    c["pass"] = c["overall_weighted_pct"] >= 99 and all(v["weighted_pct"] >= 98 for v in per.values())
    un = p[~p["ranked"]]
    rows = []
    rawq = raw.groupby("isin")["date"].agg(["min", "max", "size"])
    nullm = raw[raw["mcap"] == ""]
    for (par, isin, stock, name), g in un.groupby(["parent", "isin", "stock", "name"]):
        snaps = sorted(set(g["snapshot"].dropna()))
        if isin in rawq.index:
            first, lastd, n = rawq.loc[isin]
            on = [s for s in snaps if ((raw["isin"] == isin) & (raw["date"] == s)).any()]
            nm = [s for s in snaps if ((nullm["isin"] == isin) & (nullm["date"] == s)).any()]
            why = (f"in D20b {first}..{lastd} ({n} snapshots); "
                   + (f"null mcap on {nm}" if nm else f"absent from snapshot(s) {snaps}"))
        else:
            ss = sym[(sym["isin"] == isin) | (sym["new_isin"] == isin)]
            why = "ISIN not in D20b" + (f"; symbology: class {sorted(set(ss['instrument_class']))}, quote_id {sorted(set(ss['quote_id']))}, "
                                         f"ric {sorted(set(ss['ric']))}" if len(ss) else "; not in symbology either")
        rows.append({"parent": par, "isin": isin, "stock": stock, "name": name, "holding_days": int(len(g)),
                     "first": g["date"].min(), "last": g["date"].max(), "max_weight": float(g["weight"].max()),
                     "weight_share_pct_of_parent": float(100 * g["weight"].sum() / p[p.parent == par]["weight"].sum()),
                     "snapshots": ",".join(snaps), "why": why})
    c["unranked"] = rows
    c["unranked_above_2pct_weight"] = [r for r in rows if r["max_weight"] > 0.02]
    if rows:
        pd.DataFrame(rows).to_csv(OUT / "check6_unranked_holdings.csv", index=False)
    R["check6"] = c
    return c, p


# --------------------------------------------------------------------------------------
# Check 7: plausibility flags
# --------------------------------------------------------------------------------------
LARGE_2014 = ["RELIANCE", "TCS", "HDFCBANK", "ITC", "INFY", "ONGC", "ICICIBANK", "HDFC", "SBIN", "COALINDIA", "HINDUNILVR",
              "LT", "SUNPHARMA", "WIPRO", "BHARTIARTL", "NTPC", "TATAMOTORS", "HCLTECH", "AXISBANK", "KOTAKBANK", "MARUTI",
              "NMDC", "BAJAJ-AUTO", "M&M", "TECHM", "ULTRACEMCO", "ASIANPAINT", "IOC", "POWERGRID", "BPCL", "GAIL", "CIPLA",
              "DRREDDY", "LUPIN", "HEROMOTOCO", "NESTLEIND", "TATASTEEL", "HINDZINC", "BAJFINANCE", "TITAN"]


def monthly_d23():
    """D23 rank panel, one snapshot per month (the last) for 2018-01 .. 2025-12."""
    d = read_str(D23)
    d = d[d["date"] <= "2025-12-31"]
    last = d.groupby(d["date"].str[:7])["date"].max()
    d = d[d["date"].isin(set(last))].copy()
    d["rank"] = d["rank"].astype(int)
    d["mcap_f"] = d["mcap"].astype(float)
    return d


def turnover(panel: pd.DataFrame, n: int) -> pd.Series:
    dates = sorted(panel["date"].unique())
    top = {d: set(panel[(panel["date"] == d) & (panel["rank"] <= n)]["quote_id"]) for d in dates}
    return pd.Series({b: len(top[b] - top[a]) for a, b in zip(dates, dates[1:])})


def spikes(panel: pd.DataFrame) -> pd.DataFrame:
    """Band at t differs from t-1, and t+1 equals t-1 (needs the stock ranked on all three consecutive snapshots)."""
    dates = sorted(panel["date"].unique())
    pos = {d: i for i, d in enumerate(dates)}
    p = panel[["date", "quote_id", "isin", "ticker", "rank", "band"]].copy()
    p["k"] = p["date"].map(pos)
    a = p.merge(p.assign(k=p["k"] + 1), on=["quote_id", "k"], suffixes=("", "_prev"))
    a = a.merge(p.assign(k=p["k"] - 1)[["quote_id", "k", "rank", "band", "date"]], on=["quote_id", "k"], suffixes=("", "_next"))
    s = a[(a["band"] != a["band_prev"]) & (a["band_next"] == a["band_prev"])]
    return s[["date", "quote_id", "isin", "ticker", "rank_prev", "rank", "rank_next", "band_prev", "band", "band_next"]]


def share_blips(rawlike: pd.DataFrame, ranks: pd.DataFrame, thr=0.30) -> pd.DataFrame:
    """Implied shares = mcap/close; blip = jump > thr against both neighbours, in opposite directions, and back within 10%."""
    d = rawlike[rawlike["mcap"] != ""][["date", "quote_id", "ticker", "mcap", "close"]].copy()
    d["sh"] = d["mcap"].astype(float) / d["close"].astype(float)
    dates = sorted(d["date"].unique())
    pos = {x: i for i, x in enumerate(dates)}
    d["k"] = d["date"].map(pos)
    d = d.merge(ranks[["date", "quote_id", "rank", "band"]], on=["date", "quote_id"], how="left")
    a = d.merge(d.assign(k=d["k"] + 1)[["quote_id", "k", "sh", "rank", "band"]], on=["quote_id", "k"], suffixes=("", "_prev"))
    a = a.merge(d.assign(k=d["k"] - 1)[["quote_id", "k", "sh", "rank", "band", "date"]], on=["quote_id", "k"], suffixes=("", "_next"))
    r1 = np.log(a["sh"] / a["sh_prev"]); r2 = np.log(a["sh_next"] / a["sh"]); r0 = np.log(a["sh_next"] / a["sh_prev"])
    lt = np.log(1 + thr)
    m = (r1.abs() > lt) & (r2.abs() > lt) & (np.sign(r1) != np.sign(r2)) & (r0.abs() < np.log(1.10))
    out = a[m].copy()
    out["shares_ratio_vs_prev"] = np.exp(r1[m]); out["shares_ratio_next_vs"] = np.exp(r2[m])
    out["crosses_band"] = (out["band"] != out["band_prev"]) & (out["band_prev"] == out["band_next"])
    return out[["date", "quote_id", "ticker", "rank_prev", "rank", "rank_next", "band_prev", "band", "band_next",
                "shares_ratio_vs_prev", "shares_ratio_next_vs", "crosses_band"]]


def check7(raw, d20raw, mine, pop, theirs, mytags):
    c = {}
    pre = mine.copy()
    pre["rank"] = pre["rank"].astype(int)
    post = monthly_d23()
    # (a) implied shares blips
    b_pre = share_blips(raw, pre)
    d20m = d20raw[d20raw["date"].isin(set(post["date"]))]
    b_post = share_blips(d20m, post)
    top = lambda b: b[(b[["rank_prev", "rank", "rank_next"]].min(axis=1) <= 300)]
    obs_pre = int((pre["rank"] <= 300).sum()); obs_post = int((post["rank"] <= 300).sum())
    c["blips_thr"] = "implied shares (mcap/close) move > 30% against both neighbouring snapshots, in opposite directions, and the neighbours agree within 10%"
    c["blips_pre_all"] = int(len(b_pre)); c["blips_post_all_2018_2025"] = int(len(b_post))
    c["blips_pre_top300"] = top(b_pre).to_dict("records")
    c["blips_post_top300_count"] = int(len(top(b_post)))
    c["blips_rate_top300_per_10k_obs"] = {"2014_2017": round(1e4 * len(top(b_pre)) / obs_pre, 2),
                                          "2018_2025": round(1e4 * len(top(b_post)) / obs_post, 2)}
    c["blips_pre_crossing_band"] = b_pre[b_pre["crosses_band"]].to_dict("records")
    # held stocks affected by a blip snapshot
    held_q = set()
    pre_isin_q = dict(zip(pre["isin"], pre["quote_id"]))
    for i in set(pop["isin"]):
        if i in pre_isin_q:
            held_q.add(pre_isin_q[i])
    c["blips_pre_on_held_stocks"] = b_pre[b_pre["quote_id"].isin(held_q)].to_dict("records")
    # one-way large share jumps in the top 300 (not reverted): splits/bonus/mergers or errors
    d = raw[raw["mcap"] != ""][["date", "quote_id", "ticker", "mcap", "close"]].copy()
    d["sh"] = d["mcap"].astype(float) / d["close"].astype(float)
    d = d.sort_values(["quote_id", "date"])
    d["sh_prev"] = d.groupby("quote_id")["sh"].shift()
    d["mc_prev"] = d.groupby("quote_id")["mcap"].shift().astype(float)
    d = d.merge(pre[["date", "quote_id", "rank"]], on=["date", "quote_id"], how="left")
    j = d[(np.abs(np.log(d["sh"] / d["sh_prev"])) > np.log(1.3)) & (d["rank"] <= 300)]
    c["share_jumps_gt30pct_top300_pre"] = int(len(j))
    c["share_jumps_gt30pct_top300_pre_list"] = j.assign(ratio=j["sh"] / j["sh_prev"], mcap_ratio=j["mcap"].astype(float) / j["mc_prev"])[
        ["date", "quote_id", "ticker", "rank", "ratio", "mcap_ratio"]].to_dict("records")
    # (b) band-edge spikes
    sp_pre = spikes(pre); sp_post = spikes(post)
    c["spikes_pre_count"] = int(len(sp_pre)); c["spikes_post_count_2018_2025"] = int(len(sp_post))
    c["spikes_rate_per_snapshot"] = {"2014_2017": round(len(sp_pre) / (pre["date"].nunique() - 2), 2),
                                     "2018_2025": round(len(sp_post) / (post["date"].nunique() - 2), 2)}
    big = sp_pre[(sp_pre["rank"] - sp_pre["rank_prev"]).abs() > 100]
    c["spikes_pre_moves_over_100_ranks"] = big.to_dict("records")
    sp_held = sp_pre[sp_pre["quote_id"].isin(held_q)]
    c["spikes_pre_on_held_stocks"] = int(len(sp_held))
    sp_pre.to_csv(OUT / "check7_band_spikes_2014_2017.csv", index=False)
    # holes: absent on a snapshot, present on both neighbours
    dates = sorted(raw["date"].unique())
    byq = {dd: set(pre[pre["date"] == dd]["quote_id"]) for dd in dates}
    rk = pre.set_index(["date", "quote_id"])["rank"]
    holes = []
    for a_, b_, c_ in zip(dates, dates[1:], dates[2:]):
        for q in (byq[a_] & byq[c_]) - byq[b_]:
            holes.append({"date": b_, "quote_id": q, "rank_prev": int(rk[(a_, q)]), "rank_next": int(rk[(c_, q)]),
                          "null_mcap_row": bool(((raw["date"] == b_) & (raw["quote_id"] == q)).any())})
    hl = pd.DataFrame(holes)
    c["holes_count"] = int(len(hl))
    c["holes_by_date"] = hl.groupby("date").size().to_dict() if len(hl) else {}
    c["holes_top250_neighbours"] = hl[(hl[["rank_prev", "rank_next"]].min(axis=1) <= 250)].to_dict("records") if len(hl) else []
    c["holes_on_held_stocks"] = hl[hl["quote_id"].isin(held_q)].to_dict("records") if len(hl) else []
    # 2017-02-28 -> 2017-03-31 drop: who left and did they come back?
    left = byq["2017-02-28"] - byq["2017-03-31"]
    back = left & set().union(*[byq[x] for x in dates if x > "2017-03-31"])
    lr = pre[(pre["date"] == "2017-02-28") & pre["quote_id"].isin(left)]
    c["drop_2017_03"] = {"left": len(left), "came_back_later": len(back), "best_rank_on_2017_02_28": int(lr["rank"].min()),
                         "median_rank_on_2017_02_28": float(lr["rank"].median()),
                         "delisted_ric_share": float(raw[(raw["date"] == "2017-02-28") & raw["quote_id"].isin(left)]["ric"].str.contains(r"\^").mean())}
    # (c) turnover
    t_pre100, t_pre250 = turnover(pre, 100), turnover(pre, 250)
    t_post100, t_post250 = turnover(post, 100), turnover(post, 250)
    c["turnover_top100"] = {"2014_2017_median": float(t_pre100.median()), "2014_2017_mean": float(t_pre100.mean()), "2014_2017_max": [t_pre100.idxmax(), int(t_pre100.max())],
                            "2018_2025_median": float(t_post100.median()), "2018_2025_mean": float(t_post100.mean()), "2018_2025_max": [t_post100.idxmax(), int(t_post100.max())]}
    c["turnover_top250"] = {"2014_2017_median": float(t_pre250.median()), "2014_2017_mean": float(t_pre250.mean()), "2014_2017_max": [t_pre250.idxmax(), int(t_pre250.max())],
                            "2018_2025_median": float(t_post250.median()), "2018_2025_mean": float(t_post250.mean()), "2018_2025_max": [t_post250.idxmax(), int(t_post250.max())]}
    c["turnover_monthly_pre"] = {k: [int(t_pre100[k]), int(t_pre250[k])] for k in t_pre100.index}
    # (d) join
    j0 = pre[pre["date"] == "2017-12-29"].set_index("quote_id")
    j1 = post[post["date"] == "2018-01-31"].set_index("quote_id")
    com = j0.index.intersection(j1.index)
    top0 = j0[j0["rank"] <= 500].index.intersection(com)
    rho = pd.Series(j0.loc[top0, "rank"]).corr(pd.Series(j1.loc[top0, "rank"]), method="spearman")
    rho_ref = []
    for dd in [("2016-12-30", "2017-01-31"), ("2017-11-30", "2017-12-29")]:
        x0 = pre[pre["date"] == dd[0]].set_index("quote_id"); x1 = pre[pre["date"] == dd[1]].set_index("quote_id")
        tt = x0[x0["rank"] <= 500].index.intersection(x1.index)
        rho_ref.append({"pair": dd, "spearman_top500": float(x0.loc[tt, "rank"].corr(x1.loc[tt, "rank"], method="spearman"))})
    x0 = post[post["date"] == "2018-01-31"].set_index("quote_id"); x1 = post[post["date"] == "2018-02-28"].set_index("quote_id")
    tt = x0[x0["rank"] <= 500].index.intersection(x1.index)
    rho_ref.append({"pair": ("2018-01-31", "2018-02-28"), "spearman_top500": float(x0.loc[tt, "rank"].corr(x1.loc[tt, "rank"], method="spearman"))})
    # implied-share ratio across the join (vintage break would shift it)
    r0 = raw[raw["date"] == "2017-12-29"].set_index("quote_id"); r1 = d20raw[d20raw["date"] == "2018-01-31"].set_index("quote_id")
    cq = r0.index.intersection(r1.index)
    cq = [q for q in cq if r0.loc[q, "mcap"] != "" and r1.loc[q, "mcap"] != ""]
    shr = (r1.loc[cq, "mcap"].astype(float) / r1.loc[cq, "close"].astype(float)) / (r0.loc[cq, "mcap"].astype(float) / r0.loc[cq, "close"].astype(float))
    ref = []
    for a_, b_ in zip(dates[-4:], dates[-3:]):
        s0 = raw[raw["date"] == a_].set_index("quote_id"); s1 = raw[raw["date"] == b_].set_index("quote_id")
        q2 = [q for q in s0.index.intersection(s1.index) if s0.loc[q, "mcap"] != "" and s1.loc[q, "mcap"] != ""]
        rr = (s1.loc[q2, "mcap"].astype(float) / s1.loc[q2, "close"].astype(float)) / (s0.loc[q2, "mcap"].astype(float) / s0.loc[q2, "close"].astype(float))
        ref.append({"pair": [a_, b_], "share_unchanged_pct": float(100 * (np.abs(rr - 1) < 1e-3).mean()), "moved_gt10pct": int((np.abs(rr - 1) > 0.1).sum())})
    c["join"] = {"top100_changed": int(len(set(j1[j1["rank"] <= 100].index) - set(j0[j0["rank"] <= 100].index))),
                 "top250_changed": int(len(set(j1[j1["rank"] <= 250].index) - set(j0[j0["rank"] <= 250].index))),
                 "spearman_top500": float(rho), "spearman_reference": rho_ref,
                 "n_ranked": [int(j0["n_ranked"].iloc[0]), int(j1["n_ranked"].iloc[0])],
                 "total_mcap_lakh_cr": [float(j0["mcap_f"].sum() / 1e12), float(j1["mcap_f"].sum() / 1e12)],
                 "implied_shares_unchanged_pct": float(100 * (np.abs(shr - 1) < 1e-3).mean()),
                 "implied_shares_moved_gt10pct": int((np.abs(shr - 1) > 0.1).sum()),
                 "implied_shares_reference_prev_months": ref,
                 "rank100_mcap_cr": [float(j0[j0["rank"] == 100]["mcap_f"].iloc[0] / 1e7), float(j1[j1["rank"] == 100]["mcap_f"].iloc[0] / 1e7)],
                 "rank250_mcap_cr": [float(j0[j0["rank"] == 250]["mcap_f"].iloc[0] / 1e7), float(j1[j1["rank"] == 250]["mcap_f"].iloc[0] / 1e7)]}
    # edge mcaps over time
    edges = []
    for dd, g in pd.concat([pre, post]).groupby("date"):
        g = g.set_index("rank")["mcap_f"]
        edges.append({"date": dd, "rank100_cr": round(g.get(100) / 1e7), "rank250_cr": round(g.get(250) / 1e7), "n": int(len(g))})
    c["edge_mcap_by_snapshot"] = edges
    # (e) well-known 2014 large caps
    lc = {}
    for tk in LARGE_2014:
        g = pre[pre["ticker"] == tk]
        if len(g) == 0:
            lc[tk] = {"present": False}
            continue
        out100 = g[g["rank"] > 100]
        lc[tk] = {"present": True, "snapshots": int(len(g)), "rank_min": int(g["rank"].min()), "rank_max": int(g["rank"].max()),
                  "outside_top100": out100[["date", "rank"]].values.tolist()[:12], "n_outside": int(len(out100)),
                  "isins": sorted(set(g["isin"]))}
    c["large_caps_2014"] = lc
    c["top100_names"] = {dd: pre[(pre["date"] == dd) & (pre["rank"] <= 100)]["ticker"].tolist() for dd in ("2014-03-31", "2017-12-29")}
    c["ranks_101_120_on_2014-03-31"] = pre[(pre["date"] == "2014-03-31") & (pre["rank"].between(95, 110))][["rank", "ticker", "mcap_f"]].assign(mcap_cr=lambda x: (x.mcap_f / 1e7).round()).drop(columns="mcap_f").values.tolist()
    # (f) parents' band split, rank rule, at rank-snapshot month-ends: 2014-03..2017-12 vs 2019-01..2026-03
    rows = []
    allpan = pd.concat([pre[["date", "quote_id", "isin", "rank", "band"]], post[["date", "quote_id", "isin", "rank", "band"]]])
    for par in PARENTS:
        m = pd.read_csv(HOLD / f"SCMO_{par}_holding_weight_matrix.csv")
        cols = pd.read_csv(HOLD / f"SCMO_{par}_columns.csv", dtype=str, keep_default_na=False)
        src = pd.read_csv(HOLD / f"SCMO_{par}_holding_weight_sources.csv")
        skipped = set(src.loc[src["csv_skipped_flag"].astype(bool), "rebalance_date"])
        m = m[~m["rebalance_date"].isin(skipped)]
        long = m.melt(id_vars="rebalance_date", var_name="stock", value_name="weight")
        long = long[long["weight"].notna() & (long["weight"] > 0)].merge(cols[["stock", "ISIN"]], on="stock")
        bd = np.array(sorted(m["rebalance_date"].unique()))
        snaps = sorted(set(allpan["date"]))
        for s in snaps:
            if not (("2014-03-03" <= s <= "2017-12-31") or ("2019-01-01" <= s <= "2026-03-31")):
                continue
            i = np.searchsorted(bd, s, side="right") - 1
            if i < 0:
                continue
            h = long[long["rebalance_date"] == bd[i]]
            for isin, w in zip(h["ISIN"], h["weight"]):
                t = mytags.tag(isin, s)
                rows.append({"parent": "SCMO_" + par, "date": s, "period": "2014-2017" if s < "2018" else "2019-2026-03",
                             "band": t["band"] if t["source"] != "unranked" else "unranked", "weight": w})
    sp = pd.DataFrame(rows)
    tab = sp.groupby(["parent", "period", "band"])["weight"].sum() / sp.groupby(["parent", "period"])["weight"].sum() * 100
    c["parent_band_split_pct"] = {f"{a}|{b}|{d}": round(float(v), 1) for (a, b, d), v in tab.items()}
    R["check7"] = c
    return c


# --------------------------------------------------------------------------------------
# Check 8: trace table
# --------------------------------------------------------------------------------------
def check8(pop6, raw, theirs, seed=8):
    rng = np.random.default_rng(seed)
    p = pop6.copy()
    p["year"] = p["date"].str[:4]
    picks = []
    for y in ["2014", "2015", "2016", "2017"]:
        for par in PARENTS:
            g = p[(p["year"] == y) & (p["parent"] == "SCMO_" + par)]
            picks.append(g.iloc[int(rng.integers(len(g)))])
    # add four near band edges (rank 90-110 or 240-260)
    near = p[p["source"] == "rank"].copy()
    near["rank"] = [theirs.tag(i, d)["detail"] for i, d in zip(near["isin"], near["date"])]
    for lo, hi in ((90, 110), (240, 260)):
        g = near[near["rank"].between(lo, hi)]
        for k in rng.choice(len(g), size=min(2, len(g)), replace=False):
            picks.append(g.iloc[int(k)])
    rows = []
    for r in picks:
        t = theirs.tag(r["isin"], r["date"])
        snap = t["snapshot"]
        rr = raw[(raw["date"] == snap) & (raw["isin"] == r["isin"])]
        day = raw[(raw["date"] == snap) & (raw["mcap"] != "")]
        mc = day["mcap"].astype(float)
        if len(rr) == 1 and rr["mcap"].iloc[0] != "":
            m = float(rr["mcap"].iloc[0])
            hand_rank = int((mc > m).sum()) + 1
            ties = int((mc == m).sum()) - 1
        else:
            m, hand_rank, ties = None, None, None
        srt = np.sort(mc.values)[::-1]
        hand_band = band_of(hand_rank) if hand_rank else "unranked"
        rows.append({"parent": r["parent"], "date": r["date"], "isin": r["isin"], "stock": r["stock"], "name": r["name"],
                     "weight": round(float(r["weight"]), 4), "snapshot_used": snap,
                     "raw_ticker": rr["ticker"].iloc[0] if len(rr) else None, "raw_close": rr["close"].iloc[0] if len(rr) else None,
                     "raw_mcap": rr["mcap"].iloc[0] if len(rr) else None, "mcap_cr": round(m / 1e7, 1) if m else None,
                     "n_ranked_by_hand": int(len(mc)), "rank_by_hand": hand_rank, "tied_mcaps": ties,
                     "mcap_rank100_cr": round(srt[99] / 1e7, 1), "mcap_rank101_cr": round(srt[100] / 1e7, 1),
                     "mcap_rank250_cr": round(srt[249] / 1e7, 1), "mcap_rank251_cr": round(srt[250] / 1e7, 1),
                     "band_by_hand": hand_band, "lookup_rank": t["detail"], "lookup_band": t["band"], "lookup_source": t["source"],
                     "lookup_via": t["via"], "agree": (hand_band == t["band"] and hand_rank == t["detail"])})
    tt = pd.DataFrame(rows).sort_values(["date", "parent"])
    tt.to_csv(OUT / "trace_table.csv", index=False)
    R["check8"] = {"rows": int(len(tt)), "all_agree": bool(tt["agree"].all()), "sources": tt["lookup_source"].value_counts().to_dict(),
                   "bands": tt["lookup_band"].value_counts().to_dict(), "years": tt["date"].str[:4].value_counts().sort_index().to_dict()}
    return tt


# --------------------------------------------------------------------------------------
# Check 9: self-test with corrupted copies
# --------------------------------------------------------------------------------------
def check3_on(mine, pre_path: Path, comb_path: Path) -> dict:
    pre = read_str(pre_path)
    r1, _ = compare_rank(mine, pre, "pre")
    comb = read_str(comb_path)
    r2, _ = compare_rank(mine, comb[comb["date"] < "2018-01-01"].reset_index(drop=True), "combined pre-2018 part")
    b23 = D23.read_bytes(); nl = b23.index(b"\n") + 1
    concat_ok = comb_path.read_bytes() == pre_path.read_bytes() + b23[nl:]
    reg = registry_prefixes()
    sha_ok = (sha256(pre_path)[:16] == reg[str(D23B_PRE.relative_to(AA)).replace("\\", "/")]["sha16"]
              and sha256(comb_path)[:16] == reg[str(D23B_COMB.relative_to(AA)).replace("\\", "/")]["sha16"])
    return {"pre_differences": r1["total_differences"], "pre_detail": {k: r1[k] for k in ("only_mine", "only_theirs", "dup_keys_theirs", "field_diffs", "row_order_identical")},
            "combined_part_differences": r2["total_differences"], "concat_ok": concat_ok, "sha_ok": sha_ok,
            "flagged": bool(r1["total_differences"] or r2["total_differences"] or not concat_ok or not sha_ok)}


def check9(mine, mytags, pop, scratch):
    out = {}
    pre_bytes = D23B_PRE.read_bytes()
    b23 = D23.read_bytes(); nl = b23.index(b"\n") + 1
    lines = pre_bytes.decode("utf-8").split("\n")
    hdr, body = lines[0], [x for x in lines[1:] if x]
    pairs = sorted(set(zip(pop["isin"], pop["date"])))
    # rows the population actually uses: (snapshot, isin)
    used = set()
    snaps = sorted(set(mine["date"]))
    import bisect
    for i, d in pairs:
        k = bisect.bisect_right(snaps, d) - 1
        if k >= 0:
            used.add((snaps[k], i))
    idx_used = [n for n, ln in enumerate(body) if (ln.split(",")[0], ln.split(",")[2]) in used]
    rng = random.Random(99)
    def fields(n): return body[n].split(",")
    # pick rows
    drop_n = rng.choice(idx_used)
    # swap two ranks: two used rows on one snapshot, different bands
    f0 = fields(drop_n)
    cands = [n for n in idx_used if fields(n)[0] == "2016-06-30"]
    a_n = next(n for n in cands if fields(n)[7] == "Mid")
    b_n = next(n for n in cands if fields(n)[7] == "Small and below")
    mc_n = rng.choice(idx_used)
    dup_n = rng.choice(idx_used)
    def swap(b):
        b = list(b); fa, fb = b[a_n].split(","), b[b_n].split(",")
        fa[5], fb[5] = fb[5], fa[5]; fa[7], fb[7] = fb[7], fa[7]
        b[a_n], b[b_n] = ",".join(fa), ",".join(fb); return b
    def chg_mcap(b):
        b = list(b); f = b[mc_n].split(","); f[4] = repr(float(f[4]) * 1.5); b[mc_n] = ",".join(f); return b
    corruptions = {
        "drop_a_row": (lambda b: b[:drop_n] + b[drop_n + 1:], f"{fields(drop_n)[0]} {fields(drop_n)[3]} rank {fields(drop_n)[5]}"),
        "swap_two_ranks_and_bands": (swap, f"{fields(a_n)[0]} {fields(a_n)[3]} rank {fields(a_n)[5]} <-> {fields(b_n)[3]} rank {fields(b_n)[5]}"),
        "change_one_mcap_x1.5_rank_kept": (chg_mcap, f"{fields(mc_n)[0]} {fields(mc_n)[3]} rank {fields(mc_n)[5]}"),
        "duplicate_a_row": (lambda b: b[:dup_n + 1] + [b[dup_n]] + b[dup_n + 1:], f"{fields(dup_n)[0]} {fields(dup_n)[3]} rank {fields(dup_n)[5]}"),
    }
    for name, (fn, what) in corruptions.items():
        nb = fn(body)
        pre_b = ("\n".join([hdr] + nb) + "\n").encode("utf-8")
        pp = scratch / f"corrupt_{name}_pre.csv"; cp = scratch / f"corrupt_{name}_combined.csv"
        pp.write_bytes(pre_b); cp.write_bytes(pre_b + b23[nl:])
        c3 = check3_on(mine, pp, cp)
        theirs = load_their_lookup(cp)
        n, bad = run_tag_compare(pairs, mytags, theirs)
        out[name] = {"what": what, "check3": c3, "check5_population_mismatches": len(bad), "check5_lookups": n,
                     "check5_examples": bad[:3]}
        log("  ", name, "check3 flagged:", c3["flagged"], "check5 mismatches:", len(bad))
    # control: the real files pass both
    c3 = check3_on(mine, D23B_PRE, D23B_COMB)
    out["control_real_files"] = {"check3": c3}
    R["check9"] = out
    return out


# --------------------------------------------------------------------------------------
# Extra for checks 6/7: identity cross-check and sensitivity of held bands to gaps / bad rows
# --------------------------------------------------------------------------------------
def identity_check(pop6, raw):
    """Basket sid (Eikon RIC root) against the RIC root of the D20b row the ISIN matched."""
    sid = {}
    for p in PARENTS:
        cols = pd.read_csv(HOLD / f"SCMO_{p}_columns.csv", dtype=str, keep_default_na=False)
        for s, i, sd in zip(cols["stock"], cols["ISIN"], cols["sid"]):
            sid[(f"SCMO_{p}", s)] = sd
    r = raw[["date", "isin", "ric", "ticker", "full_name"]].copy()
    r["ric_root"] = r["ric"].str.split(".").str[0]
    m = pop6[pop6["source"] == "rank"].merge(r, left_on=["snapshot", "isin"], right_on=["date", "isin"], suffixes=("", "_r"))
    m["sid"] = [sid[(a, b)] for a, b in zip(m["parent"], m["stock"])]
    bad = m[m["sid"] != m["ric_root"]]
    g = bad.groupby(["parent", "stock", "isin", "sid", "ric", "ticker", "full_name"]).size().reset_index(name="holding_days")
    return {"matched_holding_days": int(len(m)), "sid_ne_ric_root_holding_days": int(len(bad)),
            "pairs": g.to_dict("records")}


def gaps(raw, pre, max_rank=260):
    dates = sorted(raw["date"].unique())
    pos = {d: i for i, d in enumerate(dates)}
    pres = raw.groupby("quote_id")["date"].apply(lambda s: sorted(pos[x] for x in s))
    rk = pre.set_index(["date", "quote_id"])["rank"]
    mc = pre.set_index(["date", "quote_id"])["mcap_f"]
    out = []
    for q, ks in pres.items():
        for a, b in zip(ks, ks[1:]):
            if b - a > 1:
                da, db = dates[a], dates[b]
                ra, rb = rk.get((da, q)), rk.get((db, q))
                if ra is None or rb is None:
                    continue
                if min(ra, rb) <= max_rank:
                    out.append({"quote_id": q, "ticker": raw[raw.quote_id == q]["ticker"].iloc[0], "missing": dates[a + 1:b],
                                "rank_before": int(ra), "rank_after": int(rb), "mcap_before": float(mc[(da, q)]),
                                "mcap_after": float(mc[(db, q)]), "k_before": a, "k_after": b})
    return out, dates


def rerank_snapshot(g: pd.DataFrame) -> pd.DataFrame:
    g = g.copy()
    g["qid"] = g["quote_id"].astype(np.int64)
    g = g.sort_values(["mcap_f", "qid"], ascending=[False, True], kind="mergesort")
    g["rank"] = np.arange(1, len(g) + 1)
    g["band"] = [band_of(x) for x in g["rank"]]
    return g


def band_effect(pre, pop6, snap, modify) -> dict:
    g = pre[pre["date"] == snap][["quote_id", "isin", "ticker", "mcap_f", "rank", "band"]].copy()
    new = rerank_snapshot(modify(g))
    nb = dict(zip(new["isin"], new["band"]))
    held = pop6[(pop6["snapshot"] == snap) & (pop6["source"] == "rank")]
    ch = held[[nb.get(i) != b for i, b in zip(held["isin"], held["band"])]]
    return {"snapshot": snap, "holding_days_using_snapshot": int(len(held)), "holding_days_band_changed": int(len(ch)),
            "changed": ch.groupby(["parent", "stock", "band"]).size().reset_index(name="days").assign(
                new_band=lambda x: [nb.get(i) for i in ch.groupby(["parent", "stock", "band"])["isin"].first()]).to_dict("records")}


def sensitivity(raw, mine, pop6):
    pre = mine.copy()
    gl, dates = gaps(raw, pre)
    res = {"gaps_top260": [], "blips": []}
    for gp in gl:
        n = gp["k_after"] - gp["k_before"]
        for j, snap in enumerate(gp["missing"], start=1):
            m_est = gp["mcap_before"] * (gp["mcap_after"] / gp["mcap_before"]) ** (j / n)
            row = pd.DataFrame([{"quote_id": gp["quote_id"], "isin": "__gap__", "ticker": gp["ticker"], "mcap_f": m_est}])
            eff = band_effect(pre, pop6, snap, lambda g, row=row: pd.concat([g, row], ignore_index=True))
            pool = pre[pre["date"] == snap]["mcap_f"]
            eff.update({"ticker": gp["ticker"], "rank_before": gp["rank_before"], "rank_after": gp["rank_after"],
                        "gap_length": len(gp["missing"]), "estimated_rank": int((pool > m_est).sum() + 1)})
            res["gaps_top260"].append(eff)
    # DHANUKA-type blips: replace mcap by close x mean neighbour implied shares
    b = share_blips(raw, pre)
    for _, r in b.iterrows():
        if min(r["rank_prev"], r["rank"], r["rank_next"]) > 300:
            continue
        x = raw[(raw.quote_id == r["quote_id"])].set_index("date")
        ds = sorted(x.index); i = ds.index(r["date"])
        sh = np.mean([float(x.loc[ds[i - 1], "mcap"]) / float(x.loc[ds[i - 1], "close"]),
                      float(x.loc[ds[i + 1], "mcap"]) / float(x.loc[ds[i + 1], "close"])])
        fixed = float(x.loc[r["date"], "close"]) * sh
        q = r["quote_id"]
        def mod(g, q=q, fixed=fixed):
            g = g.copy(); g.loc[g["quote_id"] == q, "mcap_f"] = fixed; return g
        eff = band_effect(pre, pop6, r["date"], mod)
        pool = pre[(pre["date"] == r["date"]) & (pre["quote_id"] != q)]["mcap_f"]
        eff.update({"ticker": r["ticker"], "rank_as_stored": int(r["rank"]), "rank_repaired": int((pool > fixed).sum() + 1)})
        # the stock's own band on that snapshot for its holders
        hd = pop6[(pop6["snapshot"] == r["date"]) & (pop6["isin"].isin(raw[raw.quote_id == q]["isin"]))]
        eff["own_holding_days"] = hd.groupby("parent").size().to_dict()
        res["blips"].append(eff)
    return res


def STAGES_5_9(stages, raw, d20raw, cal, mine, scratch):
    if not ({5, 6, 7, 8, 9} & stages):
        return
    sym = read_str(D22)
    pop = population(cal)
    log("population", len(pop))
    my_panel = build_my_panel(mine)
    mytags = MyTags(my_panel, sym)
    log("loading TagLookup on the combined candidate")
    theirs = load_their_lookup(D23B_COMB)
    if 5 in stages:
        log("check 5"); check5(raw, cal, mine, mytags, theirs, pop, sym)
    pop6 = None
    if {6, 8} & stages:
        log("check 6"); _, pop6 = check6(pop, theirs, raw, sym)
    if 6 in stages:
        R["check6"]["identity_sid_vs_ric"] = identity_check(pop6, raw)
    if 7 in stages:
        log("check 7"); check7(raw, d20raw, mine, pop, theirs, mytags)
        R["check7"]["sensitivity"] = sensitivity(raw, mine, pop6)
    if 8 in stages:
        log("check 8"); check8(pop6, raw, theirs)
    if 9 in stages:
        log("check 9"); check9(mine, mytags, pop, scratch)


if __name__ == "__main__":
    main()
