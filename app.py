"""
S&P 500 DCF Screener — Streamlit frontend for the Supabase valuation pipeline.

Reads three tables (companies, fundamentals, valuations) populated by pipeline.py.
Uses the PUBLISHABLE (anon) key — read-only, safe to deploy publicly.

Local run:
    pip install -r requirements.txt
    streamlit run app.py

Secrets (create .streamlit/secrets.toml locally, or set in Streamlit Cloud):
    SUPABASE_URL = "https://YOURPROJECT.supabase.co"
    SUPABASE_ANON_KEY = "your-publishable-anon-key"
"""

import numpy as np
import pandas as pd
import streamlit as st
from supabase import create_client
from engine import dcf, build_assumptions, EXCLUDED_SECTORS, FORECAST_YEARS

# ---------------------------------------------------------------- page config
st.set_page_config(
    page_title="Valuation Atlas — S&P 500 DCF Screener",
    page_icon="📊",
    layout="wide",
)

# ------------------------------------------------------------------- styling
st.markdown(
    """
    <style>
    @import url("https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Schibsted+Grotesk:wght@400;500;600;700&family=Spline+Sans+Mono:wght@400;500;600&display=swap");

    :root {
        --va-bg: #120f0d;
        --va-text: #f2ead9;
        --va-muted: #948d84;
        --va-accent: #d9a962;
        --va-border: rgba(245, 239, 224, 0.12);
    }

    .stApp { background-color: var(--va-bg); font-family: "Schibsted Grotesk", sans-serif; }
    h1, h2, h3 { font-family: "Instrument Serif", serif !important; color: var(--va-text) !important; font-weight: 400; }
    .metric-label { color: var(--va-muted); font-size: 0.8rem; letter-spacing: .06em; text-transform: uppercase; }
    .metric-value { color: var(--va-text); font-size: 1.6rem; font-weight: 600; font-family: "Spline Sans Mono", monospace; }
    .verdict-under { color: #4ade80; font-weight: 700; }
    .verdict-over { color: #f87171; font-weight: 700; }
    .verdict-fair { color: var(--va-accent); font-weight: 700; }
    div[data-testid="stSidebar"] { display: none; }

    [data-testid="stMetricValue"] { font-family: "Spline Sans Mono", monospace; color: var(--va-text); }
    [data-testid="stMetricLabel"] { color: var(--va-muted); text-transform: uppercase; letter-spacing: .06em; font-size: 0.75rem; }

    .va-wordmark-row { display: flex; align-items: baseline; gap: 0.6rem; margin-bottom: 2.2rem; }
    .va-wordmark { font-family: "Instrument Serif", serif; font-size: 1.4rem; color: var(--va-text); }
    .va-wordmark-sub { font-family: "Spline Sans Mono", monospace; font-size: 0.75rem; letter-spacing: .08em; color: var(--va-muted); text-transform: uppercase; }
    .va-eyebrow { font-family: "Spline Sans Mono", monospace; font-size: 0.8rem; letter-spacing: .12em; color: var(--va-accent); text-transform: uppercase; margin-bottom: 1rem; }
    .va-headline { font-family: "Instrument Serif", serif; font-size: 2.6rem; line-height: 1.25; color: var(--va-text); font-weight: 400; margin-bottom: 1.4rem; }
    .va-headline .va-accent { font-style: italic; color: var(--va-accent); }
    .va-subtext { font-family: "Schibsted Grotesk", sans-serif; font-size: 1rem; line-height: 1.6; color: var(--va-muted); max-width: 46rem; margin-bottom: 1.8rem; }
    .va-footer { font-family: "Schibsted Grotesk", sans-serif; font-size: 0.8rem; line-height: 1.6; color: var(--va-muted); }

    .stTextInput input { background-color: transparent; border: none; border-bottom: 1px solid var(--va-border); border-radius: 0; color: var(--va-text); font-size: 1.05rem; }
    .stTextInput input:focus { border-bottom: 1px solid var(--va-accent); box-shadow: none; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ------------------------------------------------------------------ supabase
@st.cache_resource
def get_client():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"])

@st.cache_data(ttl=3600)
def load_data() -> pd.DataFrame:
    sb = get_client()

    def fetch_all(table):
        rows, start, page = [], 0, 1000
        while True:
            batch = sb.table(table).select("*").range(start, start + page - 1).execute().data
            rows.extend(batch)
            if len(batch) < page:
                return pd.DataFrame(rows)
            start += page

    companies = fetch_all("companies")
    fundamentals = fetch_all("fundamentals")
    valuations = fetch_all("valuations")

    df = (
        companies.merge(fundamentals, on="ticker", how="left")
        .merge(valuations, on="ticker", how="left")
    )
    return df

try:
    df = load_data()
except Exception as e:
    st.error(
        "Could not load data from Supabase. Check that SUPABASE_URL and "
        f"SUPABASE_ANON_KEY are set in secrets.\n\nDetails: {e}"
    )
    st.stop()

n_modeled = int(df["fair_value"].notna().sum())

# ------------------------------------------------------------------- hero
st.markdown(
    f"""
    <div class="va-wordmark-row">
        <span class="va-wordmark">Valuation Atlas</span>
        <span class="va-wordmark-sub">S&P 500 · DCF</span>
    </div>
    <div class="va-eyebrow">DCF Model — S&P 500</div>
    <div class="va-headline">{n_modeled} S&P 500 companies, each run through an
        <span class="va-accent">independent two-stage DCF.</span></div>
    <div class="va-subtext">Three-year explicit forecast, Gordon-growth terminal value, WACC
        computed per company from live beta and capital structure. Search a ticker to see the
        assumptions behind its fair value, then adjust them yourself and watch it recompute.</div>
    """,
    unsafe_allow_html=True,
)

# ------------------------------------------------------------------ filters
search = st.text_input(
    "Search",
    "",
    placeholder="Search a company or ticker, try NVDA or Coca-Cola",
    label_visibility="collapsed",
    key="search_box",
)

f1, f2 = st.columns([2, 1], gap="large")

with f1:
    sectors = sorted(df["sector"].dropna().unique().tolist())
    sel_sectors = st.pills("Sector", sectors, selection_mode="multi", key="sel_sectors")

    verdicts = [v for v in df["verdict"].dropna().unique().tolist() if v != "N/A"]
    sel_verdicts = st.pills("Verdict", sorted(verdicts), selection_mode="multi", key="sel_verdicts")

with f2:
    mos_min, mos_max = st.slider(
        "Margin of safety range (%)",
        min_value=-100, max_value=500, value=(-100, 500), step=5,
        help="Fair value vs. price. Positive means the model thinks it is cheap.",
        key="mos_range",
    )

# ------------------------------------------------------------------ apply filters
view = df.copy()
view = view[view["fair_value"].notna()]

if sel_sectors:
    view = view[view["sector"].isin(sel_sectors)]
if sel_verdicts:
    view = view[view["verdict"].isin(sel_verdicts)]

view["mos_pct"] = view["margin_of_safety"] * 100
view = view[(view["mos_pct"] >= mos_min) & (view["mos_pct"] <= mos_max)]

if search:
    s = search.strip().lower()
    view = view[
        view["ticker"].str.lower().str.contains(s, na=False)
        | view["name"].str.lower().str.contains(s, na=False)
    ]

cap_col, reset_col = st.columns([5, 1])
with cap_col:
    st.caption(f"{len(view):,} companies, sorted by margin of safety")
with reset_col:
    if st.button("Reset filters", use_container_width=True):
        for k in ("sel_sectors", "sel_verdicts", "mos_range", "search_box"):
            st.session_state.pop(k, None)
        st.rerun()

# ------------------------------------------------------------------- table
table = view[[
    "ticker", "name", "sector", "price", "fair_value",
    "mos_pct", "implied_growth", "wacc", "verdict",
]].copy()
table["implied_growth"] = table["implied_growth"] * 100
table["wacc"] = table["wacc"] * 100
table = table.sort_values("mos_pct", ascending=False)

row_h, header_h, pad = 35, 38, 3
table_height = min(header_h + row_h * max(len(table), 1) + pad, 560)

st.dataframe(
    table,
    use_container_width=True,
    hide_index=True,
    height=table_height,
    column_config={
        "ticker": st.column_config.TextColumn("Ticker", width="small"),
        "name": st.column_config.TextColumn("Company"),
        "sector": st.column_config.TextColumn("Sector"),
        "price": st.column_config.NumberColumn("Price", format="$%.2f"),
        "fair_value": st.column_config.NumberColumn("Fair value", format="$%.2f"),
        "mos_pct": st.column_config.NumberColumn("Margin of safety", format="%.1f%%"),
        "implied_growth": st.column_config.NumberColumn(
            "Implied growth", format="%.1f%%",
            help="Reverse DCF: the FCF growth rate the current price implies.",
        ),
        "wacc": st.column_config.NumberColumn("WACC", format="%.2f%%"),
        "verdict": st.column_config.TextColumn("Verdict", width="small"),
    },
)

st.divider()

# ------------------------------------------------------- single-company DCF
st.header("Company deep-dive")

tickers = view["ticker"].sort_values().tolist() or df["ticker"].sort_values().tolist()
pick = st.selectbox("Pick a company", tickers, index=0 if tickers else None)

if pick:
    row = df[df["ticker"] == pick].iloc[0]

    left, right = st.columns([1, 2], gap="large")

    with left:
        name = row["name"]
        sector_disp = row.get("sector", "")
        industry_disp = row.get("industry", "") or ""
        price = row["price"]
        market_cap = row.get("market_cap")
        revenue = row.get("revenue")
        fcf = row.get("fcf")
        cash = row.get("cash") or 0
        debt = row.get("debt") or 0
        net_cash = cash - debt
        rev_growth_3y = row.get("rev_growth_3y")
        beta = row.get("beta")
        verdict_val = row.get("verdict")
        fair_value = row["fair_value"]

        def fmt_b(x):
            return f"${x/1e9:,.1f}B" if pd.notna(x) else "—"

        st.subheader(f"{name} ({pick})")
        st.caption(f"{sector_disp} · {industry_disp}")

        st.write(f"**Price:** ${price:,.2f}" if pd.notna(price) else "**Price:** —")
        st.write(f"**Market cap:** {fmt_b(market_cap)}")
        st.write(f"**Revenue (TTM):** {fmt_b(revenue)}")
        st.write(f"**Free cash flow:** {fmt_b(fcf)}")
        st.write(f"**Net cash (cash minus debt):** {fmt_b(net_cash)}")
        if pd.notna(rev_growth_3y):
            st.write(f"**3-yr revenue CAGR:** {rev_growth_3y*100:,.1f}%")
        if pd.notna(beta):
            st.write(f"**Beta:** {beta:.2f}")

        if verdict_val and verdict_val != "N/A":
            cls_map = {"UNDERVALUED": "verdict-under", "OVERVALUED": "verdict-over"}
            cls = cls_map.get(verdict_val, "verdict-fair")
            verdict_html = f"Pipeline verdict: <span class=\"{cls}\">{verdict_val}</span> (fair value ${fair_value:,.2f})"
            st.markdown(verdict_html, unsafe_allow_html=True)

    with right:
        st.subheader("Interactive DCF, set your own assumptions")

        sector_val = row.get("sector")
        revenue_val = row.get("revenue")
        shares_val = row.get("shares")

        if sector_val in EXCLUDED_SECTORS:
            st.info(
                "This sector is excluded from the DCF engine (financials, real "
                "estate, and utilities do not fit a cash-flow DCF), so there is "
                "nothing to model here."
            )
        elif not (pd.notna(revenue_val) and revenue_val and shares_val):
            st.info(
                "This company is missing revenue or share data, so a DCF "
                "is not meaningful here."
            )
        else:
            base_a = build_assumptions(row)

            a1, a2, a3, a4 = st.columns(4)
            g0 = a1.slider("Year-1 revenue growth (%)", -20.0, 50.0,
                            float(base_a["g0"] * 100), 0.5) / 100
            m_ss = a2.slider("Steady-state EBIT margin (%)", 0.0, 60.0,
                              float(base_a["m_ss"] * 100), 0.5) / 100
            wacc = a3.slider("Discount rate / WACC (%)", 5.0, 15.0,
                              float(base_a["wacc"] * 100), 0.25) / 100
            g_term = a4.slider("Terminal growth (%)", 0.0, 4.0,
                                float(base_a["g_term"] * 100), 0.1) / 100

            if wacc <= g_term:
                st.warning("WACC must be greater than terminal growth for the math to converge.")
            else:
                custom_a = dict(base_a)
                custom_a["g0"] = g0
                custom_a["m_ss"] = m_ss

                forecast, out = dcf(row, a=custom_a, wacc_override=wacc, terminal_override=g_term)

                if out is None:
                    st.info(
                        "This engine cannot produce a fair value with these "
                        "assumptions (for example, negative steady-state free cash flow)."
                    )
                else:
                    price2 = row.get("price")
                    fv_share = out["fair_value"]
                    mos = out["mos"]

                    m1, m2, m3 = st.columns(3)
                    m1.metric("Fair value / share", f"${fv_share:,.2f}")
                    m2.metric("Current price", f"${price2:,.2f}" if pd.notna(price2) else "—")
                    m3.metric(
                        "Margin of safety",
                        f"{mos*100:,.1f}%" if pd.notna(mos) else "—",
                        delta=None,
                    )

                    proj = forecast[["Revenue", "EBIT", "FCF"]] / 1e9
                    st.bar_chart(proj, height=260)

                    ev_b = out["ev"] / 1e9
                    st.caption(
                        f"{FORECAST_YEARS}-year revenue-driven DCF (same engine as the "
                        "pipeline verdict on the left), enterprise value "
                        f"${ev_b:,.1f}B, discounted at {wacc*100:,.2f}% WACC "
                        f"with {g_term*100:,.1f}% terminal growth."
                    )

st.divider()
st.markdown(
    """
    <div class="va-footer">
    Fair value = PV of projected free cash flow plus net cash, divided by shares outstanding.<br>
    Margin of safety = (fair value minus price) divided by price. Sample data, not investment advice.
    </div>
    """,
    unsafe_allow_html=True,
)
