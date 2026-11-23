"""Market-cap band of each stock in a parent's basket: index membership vs single-day market-cap rank.

    python -I analysis/basket_band_check.py            # writes analysis/evidence/basket_band_check_<mcap date>/
    python -I analysis/basket_band_check.py --check    # prints only, writes nothing

Ad-hoc lookup asked for by Manu on 2026-11-13; not a test and not an input to any test.
Two views of the same basket (the 2026-09-11 baskets of SCMO_0010 and SCMO_0029, weights typed from Manu's screenshots):
    index band  the latest public.index_constituents_monthly snapshot on or before the basket date
                (Nifty 100 = Large, Midcap 150 = Mid, Smallcap 250 = Small, Microcap 250 = Micro)
    rank band   rank by mcap_scaled_in_cr among all instrument_class = 'ordinary' rows of public.mcap_based_universe
                on MCAP_DATE (1 = largest; one row per ISIN; no free-float or liquidity filter);
                1-100 Large, 101-250 Mid, 251-500 Small, 501+ Micro
Reads Postgres live (read-only session, creds PG_PRICE_* in wm-aiReports/.env). These rows are NOT approved data
(data/APPROVED_DATA.md); the membership rows on 2026-09-01 equal the approved D21 copy for these stocks.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import psycopg2

AA = Path(__file__).resolve().parents[1]
ENV = AA.parents[1] / "wm-aiReports" / ".env"
MCAP_DATE = "2026-11-12"
BASKET_DATE = "2026-09-11"

# scid -> {NSE symbol: weight}; symbol is the key into index_constituents_monthly
BASKETS = {
    "SCMO_0010": {
        "EMMVEE": .0667, "GLAND": .0667, "IPCALAB": .0666, "GRANULES": .0667, "WELCORP": .0667,
        "SAIL": .0667, "SOUTHBANK": .0667, "KARURVYSYA": .0667, "PNBHOUSING": .0666, "MOTHERSON": .0666,
        "MANAPPURAM": .0666, "LALPATHLAB": .0666, "CEMPRO": .0667, "ENGINERSIN": .0667, "ABCAPITAL": .0667,
    },
    "SCMO_0029": {
        "SAILIFE": .0714, "ACUTAAS": .0714, "INOXINDIA": .0714, "SYRMA": .0715, "DATAPATTNS": .0714,
        "ABSLAMC": .0714, "NAM-INDIA": .0714, "SKYGOLD": .0714, "TVSMOTOR": .0715, "PGIL": .0714,
        "MOTHERSON": .0715, "LAURUSLABS": .0714, "GRANULES": .0714, "KARURVYSYA": .0715,
    },
}
IDX = {"NIFTY 100": "Large", "NIFTY MIDCAP 150": "Mid", "NIFTY SMALLCAP 250": "Small", "NIFTY MICROCAP 250": "Micro"}
ORDER = ["Large", "Mid", "Small", "Micro", "NOT IN ANY"]

Q_SNAP = ("SELECT MAX(snapshot_date)::text AS d FROM public.index_constituents_monthly WHERE snapshot_date <= %(d)s")
Q_MEMB = ("SELECT index_name, symbol, isin, company_name FROM public.index_constituents_monthly "
          "WHERE snapshot_date = %(d)s")
Q_MCAP = ("SELECT ticker, full_name, isin, close::float AS close, mcap_scaled_in_cr::float AS mcap_cr "
          "FROM public.mcap_based_universe WHERE date = %(d)s AND instrument_class = 'ordinary'")


def connect():
    env = {}
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            env[k] = v.strip("\"'")
    c = psycopg2.connect(host=env["PG_PRICE_HOST"], port=env["PG_PRICE_PORT"], dbname=env["PG_PRICE_DBNAME"],
                         user=env["PG_PRICE_USER"], password=env["PG_PRICE_PASSWORD"], connect_timeout=20)
    c.set_session(readonly=True)
    return c


def rank_band(k: int) -> str:
    return "Large" if k <= 100 else "Mid" if k <= 250 else "Small" if k <= 500 else "Micro"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="print only, write nothing")
    a = ap.parse_args()

    with connect() as c:
        snap = pd.read_sql(Q_SNAP, c, params={"d": BASKET_DATE})["d"][0]
        memb = pd.read_sql(Q_MEMB, c, params={"d": snap})
        u = pd.read_sql(Q_MCAP, c, params={"d": MCAP_DATE})
    if u.empty:
        raise SystemExit(f"no mcap_based_universe rows on {MCAP_DATE}")
    r = (u.dropna(subset=["mcap_cr"]).sort_values("mcap_cr", ascending=False)
           .drop_duplicates("isin").reset_index(drop=True))
    r["rank"] = r.index + 1
    cut = {k: round(float(r["mcap_cr"].iloc[k - 1])) for k in (100, 250, 500)}
    print(f"membership snapshot {snap} (in force on {BASKET_DATE}); mcap {MCAP_DATE}: {len(r)} ordinary ISINs ranked; "
          f"cut-offs (Rs cr) #100 {cut[100]:,}, #250 {cut[250]:,}, #500 {cut[500]:,}")

    out_dir = AA / "analysis" / "evidence" / f"basket_band_check_{MCAP_DATE}"
    stocks_all, summ_all = [], []
    for scid, basket in BASKETS.items():
        rows = []
        for sym, w in basket.items():
            m = memb[memb["symbol"] == sym]
            idx_band = IDX[m["index_name"].iloc[0]] if len(m) else "NOT IN ANY"
            isin = m["isin"].iloc[0] if len(m) else None
            x = r[r["isin"] == isin] if isin else r[r["ticker"] == sym]
            if x.empty:
                raise SystemExit(f"{scid} {sym}: not found in mcap_based_universe on {MCAP_DATE}")
            x = x.iloc[0]
            rows.append({"scid": scid, "symbol": sym, "weight": w, "isin": x["isin"], "company": x["full_name"],
                         "index_name": m["index_name"].iloc[0] if len(m) else None, "index_band": idx_band,
                         "close": x["close"], "mcap_cr": round(float(x["mcap_cr"])), "rank": int(x["rank"]),
                         "rank_band": rank_band(int(x["rank"]))})
        s = pd.DataFrame(rows).sort_values("rank").reset_index(drop=True)
        wsum = s["weight"].sum()
        for view in ("index_band", "rank_band"):
            g = s.groupby(view).agg(n=("symbol", "size"), weight=("weight", "sum"))
            for band, row in g.iterrows():
                summ_all.append({"scid": scid, "view": view, "band": band, "n": int(row.n),
                                 "weight_pct": round(100 * row.weight / wsum, 2), "count_pct": round(100 * row.n / len(s), 1)})
        stocks_all.append(s)
        pd.set_option("display.width", 250)
        print(f"\n== {scid} (weights sum {wsum:.4f}) ==")
        print(s[["symbol", "weight", "index_band", "mcap_cr", "rank", "rank_band"]].to_string(index=False))

    stocks = pd.concat(stocks_all, ignore_index=True)
    summ = pd.DataFrame(summ_all)
    summ["o"] = summ["band"].map(ORDER.index)
    summ = summ.sort_values(["scid", "view", "o"]).drop(columns="o").reset_index(drop=True)
    print("\n" + summ.to_string(index=False))

    if a.check:
        print("\n--check: nothing written")
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    stocks.to_csv(out_dir / "stocks.csv", index=False)
    summ.to_csv(out_dir / "summary.csv", index=False)
    (out_dir / "manifest.json").write_text(json.dumps({
        "retrieved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "script": "analysis/basket_band_check.py", "basket_date": BASKET_DATE, "membership_snapshot": snap,
        "mcap_date": MCAP_DATE, "ordinary_isins_ranked": len(r), "cutoffs_cr": cut,
        "queries": {"snapshot": Q_SNAP, "membership": Q_MEMB, "mcap": Q_MCAP},
        "baskets": BASKETS}, indent=2))
    print(f"\nwrote {out_dir}")


if __name__ == "__main__":
    main()
