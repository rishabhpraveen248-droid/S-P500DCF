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

# ---------------------------------------------------------------- page config
st.set_page_config(
    page_title="S&P 500 DCF Screener",
    page_icon="📊",
    layout="wide",
)

# ------------------------------------------------------------------- styling
st.markdown(
    """
    <style>
      .stApp { background-color: #0d1526; }
      h1, h2, h3 { color: #f5efe0 !important; font-weight: 600; }
      .metric-label { color: #8fa3c4; font-size: 0.8rem; letter-spacing: .06em;
                      text-transform: uppercase; }
      .metric-value { color: #f5efe0; font-size: 1.6rem; font-weight: 600; }
      .verdict-under { color: #4ade80; font-weight: 700; }
      .verdict-over  { color: #f87171; font-weight: 700; }
      .verdict-fair  { color: #facc15; font-weight: 700; }
      div[data-testid="stSidebar"] { background-color: #101b33; }
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

    df = companies.merge(fundamentals, on="ticker", how="left") \
                  .merge(valuations, on="ticker", how="left")
    return df


try:
    df = load_data()
except Exception as e:
    st.error(
        "Could not load data from Supabase. Check that SUPABASE_URL and "
        f"SUPABASE_ANON_KEY are set in secrets.\n\nDetails: {e}"
    )
    st.stop()

# ------------------------------------------------------------------- header
st.title("S&P 500 DCF Screener")
st.caption(
    "Automated discounted-cash-flow valuations for every company in the index. "
    "Data refreshed by a local pipeline (yfinance → DCF engine → Supabase). "
    "Educational project — not investment advice."
)

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("Filters")

    sectors = sorted(df["sector"].dropna().unique().tolist())
    sel_sectors = st.multiselect("Sector", sectors, default=[])

    verdicts = [v for v in df["verdict"].dropna().unique().tolist() if v != "N/A"]
    sel_verdicts = st.multiselect("Verdict", sorted(verdicts), default=[])

    mos_min, mos_max = st.slider(
        "Margin of safety range (%)",
        min_value=-100, max_value=500, value=(-100, 500), step=5,
        help="Fair value vs. price. Positive = model thinks it's cheap.",
    )

    search = st.text_input("Search ticker or name", "")

    st.divider()
    st.caption(
        f"{df['fair_value'].notna().sum()} of {len(df)} companies have a DCF "
        "(financials, real estate, and utilities are excluded — DCF doesn't "
        "suit their capital structure)."
    )

# ------------------------------------------------------------------ filters
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

# ------------------------------------------------------------- summary row
c1, c2, c3, c4 = st.columns(4)
c1.metric("Companies shown", f"{len(view):,}")
c2.metric("Undervalued", f"{(view['verdict'] == 'UNDERVALUED').sum():,}")
c3.metric("Overvalued", f"{(view['verdict'] == 'OVERVALUED').sum():,}")
med = view["mos_pct"].median()
c4.metric("Median margin of safety", f"{med:,.1f}%" if pd.notna(med) else "—")

# ------------------------------------------------------------------- table
table = view[[
    "ticker", "name", "sector", "price", "fair_value",
    "mos_pct", "implied_growth", "wacc", "verdict",
]].copy()
table["implied_growth"] = table["implied_growth"] * 100
table["wacc"] = table["wacc"] * 100
table = table.sort_values("mos_pct", ascending=False)

st.dataframe(
    table,
    use_container_width=True,
    hide_index=True,
    height=480,
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
        st.subheader(f"{row['name']} ({pick})")
        st.caption(f"{row.get('sector', '')} · {row.get('industry', '') or ''}")

        def fmt_b(x):
            return f"${x/1e9:,.1f}B" if pd.notna(x) else "—"

        st.write(f"**Price:** ${row['price']:,.2f}" if pd.notna(row["price"]) else "**Price:** —")
        st.write(f"**Market cap:** {fmt_b(row.get('market_cap'))}")
        st.write(f"**Revenue (TTM):** {fmt_b(row.get('revenue'))}")
        st.write(f"**Free cash flow:** {fmt_b(row.get('fcf'))}")
        st.write(f"**Net cash (cash − debt):** {fmt_b((row.get('cash') or 0) - (row.get('debt') or 0))}")
        if pd.notna(row.get("rev_growth_3y")):
            st.write(f"**3-yr revenue CAGR:** {row['rev_growth_3y']*100:,.1f}%")
        if pd.notna(row.get("beta")):
            st.write(f"**Beta:** {row['beta']:.2f}")

        v = row.get("verdict")
        if v and v != "N/A":
            cls = {"UNDERVALUED": "verdict-under", "OVERVALUED": "verdict-over"}.get(v, "verdict-fair")
            st.markdown(
                f"Pipeline verdict: <span class='{cls}'>{v}</span> "
                f"(fair value ${row['fair_value']:,.2f})",
                unsafe_allow_html=True,
            )

    with right:
        st.subheader("Interactive DCF — set your own assumptions")

        fcf0 = row.get("fcf")
        shares = row.get("shares")
        cash = row.get("cash") or 0
        debt = row.get("debt") or 0
        price = row.get("price")

        if not (pd.notna(fcf0) and fcf0 and fcf0 > 0 and pd.notna(shares) and shares):
            st.info(
                "This company doesn't have positive trailing free cash flow (or is "
                "missing share data), so a simple FCF-based DCF isn't meaningful here."
            )
        else:
            a, b, c = st.columns(3)
            g5 = a.slider("FCF growth, yrs 1–5 (%)", -10.0, 40.0, 8.0, 0.5) / 100
            g_term = b.slider("Terminal growth (%)", 0.0, 4.0, 2.5, 0.1) / 100
            wacc = c.slider("Discount rate / WACC (%)", 5.0, 15.0,
                            float(row["wacc"] * 100) if pd.notna(row.get("wacc")) else 9.0,
                            0.25) / 100

            if wacc <= g_term:
                st.warning("WACC must be greater than terminal growth for the math to converge.")
            else:
                years = np.arange(1, 6)
                fcfs = fcf0 * (1 + g5) ** years
                pv_fcfs = fcfs / (1 + wacc) ** years
                tv = fcfs[-1] * (1 + g_term) / (wacc - g_term)
                pv_tv = tv / (1 + wacc) ** 5
                ev = pv_fcfs.sum() + pv_tv
                equity = ev + cash - debt
                fv_share = equity / shares
                mos = (fv_share / price - 1) if pd.notna(price) and price else np.nan

                m1, m2, m3 = st.columns(3)
                m1.metric("Fair value / share", f"${fv_share:,.2f}")
                m2.metric("Current price", f"${price:,.2f}" if pd.notna(price) else "—")
                m3.metric(
                    "Margin of safety",
                    f"{mos*100:,.1f}%" if pd.notna(mos) else "—",
                    delta=None,
                )

                proj = pd.DataFrame({
                    "Year": [f"Y{y}" for y in years],
                    "Projected FCF ($B)": fcfs / 1e9,
                    "PV of FCF ($B)": pv_fcfs / 1e9,
                })
                st.bar_chart(proj.set_index("Year"), height=260)

                st.caption(
                    f"PV of 5-yr FCFs ${pv_fcfs.sum()/1e9:,.1f}B + PV of terminal value "
                    f"${pv_tv/1e9:,.1f}B ({pv_tv/ev*100:,.0f}% of EV) = enterprise value "
                    f"${ev/1e9:,.1f}B → + net cash = equity ${equity/1e9:,.1f}B "
                    f"÷ {shares/1e6:,.0f}M shares."
                )

st.divider()
st.caption(
    "Built by Risba · data via yfinance · valuations are a student modeling "
    "project, not investment advice."
)
