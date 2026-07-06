"""
engine.py — Generalized DCF / reverse-DCF valuation engine for any company.
Sector-aware assumptions; excludes sectors where DCF is inappropriate.
"""
import numpy as np
import pandas as pd

FORECAST_YEARS = 10
TERMINAL_GROWTH = 0.025
RISK_FREE = 0.042
ERP = 0.048

# Sectors where FCF-based DCF is structurally invalid
EXCLUDED_SECTORS = {"Financial Services", "Financials", "Real Estate"}

# Sector defaults: (steady-state EBIT margin cap, steady CapEx %, D&A %)
SECTOR_PARAMS = {
    "Technology":             (0.30, 0.06, 0.05),
    "Communication Services": (0.25, 0.10, 0.09),
    "Healthcare":             (0.22, 0.05, 0.05),
    "Consumer Cyclical":      (0.12, 0.05, 0.04),
    "Consumer Defensive":     (0.12, 0.04, 0.04),
    "Industrials":            (0.14, 0.05, 0.04),
    "Energy":                 (0.15, 0.10, 0.09),
    "Utilities":              (0.20, 0.15, 0.10),
    "Basic Materials":        (0.15, 0.08, 0.06),
    "_default":               (0.15, 0.06, 0.05),
}


def get_wacc(beta):
    beta = min(max(beta if beta and not np.isnan(beta) else 1.0, 0.6), 2.0)
    return max(RISK_FREE + beta * ERP, 0.065)


def build_assumptions(f):
    """Derive company-specific assumptions from fundamentals dict f."""
    p = SECTOR_PARAMS.get(f.get("sector"), SECTOR_PARAMS["_default"])
    margin_cap, capex_ss, da_pct = p

    # Start from actual margin; fade toward min(cap, actual+improvement)
    m0 = f["operating_income"] / f["revenue"] if f["revenue"] else 0.10
    m0 = min(max(m0, -0.20), 0.60)
    m_ss = min(max(m0 * 1.2, 0.02), margin_cap, 0.60)

    # Growth: start near trailing 3y growth (clamped), fade to terminal
    g0 = f.get("rev_growth_3y")
    g0 = min(max(g0 if g0 is not None and not np.isnan(g0) else 0.05, -0.05), 0.35)

    return {
        "g0": g0, "m0": max(m0, 0.0) if m0 > 0 else m0, "m_ss": m_ss,
        "capex_ss": capex_ss, "da_pct": da_pct,
        "wacc": get_wacc(f.get("beta")),
        "tax": 0.21, "nwc_pct": 0.02, "g_term": TERMINAL_GROWTH,
    }


def fade(v0, v1, n):
    return list(np.linspace(v0, v1, n))


def dcf(f, a=None, growth_override=None, wacc_override=None,
        terminal_override=None, years=FORECAST_YEARS):
    """Returns (forecast_df, summary_dict) or (None, None) if not applicable."""
    if f.get("sector") in EXCLUDED_SECTORS:
        return None, None
    if not f.get("revenue") or f["revenue"] <= 0 or not f.get("shares"):
        return None, None

    a = a or build_assumptions(f)
    wacc = wacc_override if wacc_override is not None else a["wacc"]
    g_term = terminal_override if terminal_override is not None else a["g_term"]
    if g_term >= wacc:
        g_term = wacc - 0.02

    growth = ([growth_override] * years if growth_override is not None
              else fade(a["g0"], g_term, years))
    margins = fade(a["m0"], a["m_ss"], years)
    capex = fade(max(a["capex_ss"] * 1.5, a["da_pct"]), a["capex_ss"], years)

    rows, rev_prev = [], f["revenue"]
    for yr in range(1, years + 1):
        i = yr - 1
        rev = rev_prev * (1 + growth[i])
        ebit = rev * margins[i]
        nopat = ebit - max(ebit, 0) * a["tax"]
        fcf = (nopat + rev * a["da_pct"] - rev * capex[i]
               - (rev - rev_prev) * a["nwc_pct"])
        rows.append({"Year": yr, "Revenue": rev, "EBIT": ebit,
                     "FCF": fcf, "PV": fcf / (1 + wacc) ** yr})
        rev_prev = rev

    df = pd.DataFrame(rows).set_index("Year")
    fcf_n = df.loc[years, "FCF"]
    if fcf_n <= 0:  # terminal value undefined on negative steady FCF
        return df, None
    tv = fcf_n * (1 + g_term) / (wacc - g_term)
    ev = df["PV"].sum() + tv / (1 + wacc) ** years
    equity = ev + (f.get("cash") or 0) - (f.get("debt") or 0)
    fv = equity / f["shares"]

    price = f.get("price") or np.nan
    mos = (fv - price) / price if price else np.nan
    return df, {"fair_value": fv, "mos": mos, "wacc": wacc,
                "g_term": g_term, "ev": ev, "assumptions": a}


def reverse_dcf(f, a=None, years=FORECAST_YEARS):
    """Solve constant revenue growth s.t. fair value == market price."""
    price = f.get("price")
    if not price or f.get("sector") in EXCLUDED_SECTORS:
        return None
    a = a or build_assumptions(f)

    def fv_at(g):
        _, out = dcf(f, a=a, growth_override=g, years=years)
        return out["fair_value"] - price if out else -1e12

    lo, hi = -0.50, 3.0
    if fv_at(lo) > 0 or fv_at(hi) < 0:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if fv_at(mid) > 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def verdict(mos):
    if mos is None or np.isnan(mos):
        return "N/A"
    if mos > 0.20:
        return "UNDERVALUED"
    if mos < -0.20:
        return "OVERVALUED"
    return "NEUTRAL"
