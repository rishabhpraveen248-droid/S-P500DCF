"""
pipeline.py — Populate Supabase with S&P 500 fundamentals + valuations.
Run LOCALLY (not on Streamlit Cloud):  python pipeline.py
Env vars required: SUPABASE_URL, SUPABASE_KEY (service_role key for writes)
Takes ~20-30 min for 500 tickers (rate-limited on purpose).
"""
import os, time, sys
import numpy as np
import pandas as pd
import yfinance as yf
from supabase import create_client

from engine import dcf, reverse_dcf, verdict, EXCLUDED_SECTORS

SB = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


def get_sp500_tickers():
    import requests
    html = requests.get(
        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        headers={"User-Agent": "Mozilla/5.0 (sp500-dcf student project)"},
        timeout=30).text
    df = pd.read_html(html)[0]
    rows = [(("FI" if r["Symbol"] == "FISV" else r["Symbol"]).replace(".", "-"),
             r["Security"], r["GICS Sector"]) for _, r in df.iterrows()]
    return rows
def fetch_one(ticker):
    tk = yf.Ticker(ticker)
    info = tk.info or {}
    if not info.get("totalRevenue"):
        return None
    g3 = None
    try:
        fin = tk.financials
        if fin is not None and "Total Revenue" in fin.index:
            rev = fin.loc["Total Revenue"].dropna()
            if len(rev) >= 3 and rev.iloc[-1] > 0:
                g3 = (rev.iloc[0] / rev.iloc[-1]) ** (1 / (len(rev) - 1)) - 1
    except Exception:
        pass
    return {
        "price": info.get("currentPrice") or info.get("regularMarketPrice"),
        "market_cap": info.get("marketCap"),
        "revenue": info.get("totalRevenue"),
        "ebitda": info.get("ebitda"),
        "operating_income": (info.get("totalRevenue") or 0) * (info.get("operatingMargins") or 0),
        "net_income": info.get("netIncomeToCommon"),
        "fcf": info.get("freeCashflow"),
        "cash": info.get("totalCash"), "debt": info.get("totalDebt"),
        "shares": info.get("sharesOutstanding"),
        "beta": info.get("beta"),
        "rev_growth_3y": g3,
        "op_margin": info.get("operatingMargins"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
    }


def main():
    tickers = get_sp500_tickers()
    print(f"{len(tickers)} tickers")
    ok = fail = 0
    for i, (t, name, wiki_sector) in enumerate(tickers, 1):
        try:
            f = fetch_one(t)
            if f is None:
                fail += 1
                continue
            sector = f["sector"] or wiki_sector
            f["sector"] = sector
            applicable = sector not in EXCLUDED_SECTORS

            SB.table("companies").upsert({
                "ticker": t, "name": name, "sector": sector,
                "industry": f["industry"], "dcf_applicable": applicable,
            }).execute()
            SB.table("fundamentals").upsert({
                "ticker": t, **{k: (None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v))
                                for k, v in f.items()
                                if k not in ("sector", "industry")}
            }).execute()

            fv = mos = ig = None
            wacc = gt = None
            if applicable:
                _, out = dcf(f)
                if out:
                    fv, mos = out["fair_value"], out["mos"]
                    wacc, gt = out["wacc"], out["g_term"]
                ig = reverse_dcf(f)
            SB.table("valuations").upsert({
                "ticker": t, "fair_value": fv, "margin_of_safety": mos,
                "implied_growth": ig, "wacc": wacc, "terminal_growth": gt,
                "verdict": verdict(mos) if applicable else "N/A",
            }).execute()
            ok  += 1
            if i % 25 == 0:
                print(f"{i}/{len(tickers)} done ({ok} ok, {fail} failed)")
            time.sleep(1.2)          # be polite to Yahoo
        except Exception as e:
            fail += 1
            print(f"[{t}] {e}", file=sys.stderr)
            time.sleep(3)
    print(f"Finished: {ok} ok, {fail} failed")


if __name__ == "__main__":
    main()
