# DEPRECATED: earlier draft of the dashboard, not used. See app.py.
"""
app.py — S&P 500 Reverse-DCF Screener (Streamlit + Supabase)
Secrets required in Streamlit Cloud (Settings > Secrets):
  SUPABASE_URL = "https://xxxx.supabase.co"
  SUPABASE_KEY = "anon public key"
"""
import numpy as np
import pandas as pd
import streamlit as st
from supabase import create_client

from engine import dcf, reverse_dcf, build_assumptions, EXCLUDED_SECTORS

st.set_page_config(page_title="S&P 500 Reverse-DCF Screener",
                   page_icon="📉", layout="wide")
st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&display=swap');
html, body, [class*="css"] { font-family:'Space Grotesk',sans-serif; }
</style>""", unsafe_allow_html=True)


@st.cache_resource
def sb():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])


@st.cache_data(ttl=3600, show_spinner="Loading S&P 500 data…")
def load_all():
    c = pd.DataFrame(sb().table("companies").select("*").execute().data)
    f = pd.DataFrame(sb().table("fundamentals").select("*").execute().data)
    v = pd.DataFrame(sb().table("valuations").select("*").execute().data)
    df = c.merge(f, on="ticker").merge(v, on="ticker")
    return df


df = load_all()
page = st.sidebar.radio("View", ["📉 Screener", "🔍 Company deep dive"])

# ============================================================== SCREENER
if page == "📉 Screener":
    st.title("S&P 500 Reverse-DCF Screener")
    st.caption("What growth is the market pricing into every company? "
               "Automated 10-yr DCF + reverse DCF, sector-aware assumptions. "
               "Financials & REITs excluded (DCF not meaningful). "
               "Educational, not investment advice.")

    c1, c2, c3 = st.columns(3)
    sectors = sorted(df["sector"].dropna().unique())
    pick = c1.multiselect("Sector", sectors)
    verd = c2.multiselect("Verdict", ["UNDERVALUED", "NEUTRAL", "OVERVALUED"])
    search = c3.text_input("Search ticker/name")

    view = df[df["dcf_applicable"] == True].copy()
    if pick:
        view = view[view["sector"].isin(pick)]
    if verd:
        view = view[view["verdict"].isin(verd)]
    if search:
        s = search.lower()
        view = view[view["ticker"].str.lower().str.contains(s) |
                    view["name"].str.lower().str.contains(s)]

    n = len(view)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Companies", n)
    m2.metric("Median implied growth",
              f"{view['implied_growth'].median():.1%}" if n else "—")
    m3.metric("Undervalued", int((view["verdict"] == "UNDERVALUED").sum()))
    m4.metric("Overvalued", int((view["verdict"] == "OVERVALUED").sum()))

    show = view[["ticker", "name", "sector", "price", "fair_value",
                 "margin_of_safety", "implied_growth", "verdict"]].copy()
    show = show.sort_values("implied_growth", ascending=False)
    st.dataframe(
        show, use_container_width=True, height=560, hide_index=True,
        column_config={
            "price": st.column_config.NumberColumn("Price", format="$%.2f"),
            "fair_value": st.column_config.NumberColumn("DCF fair value", format="$%.2f"),
            "margin_of_safety": st.column_config.NumberColumn("Margin of safety", format="%.1%%"),
            "implied_growth": st.column_config.NumberColumn(
                "Market-implied growth /yr", format="%.1%%",
                help="Constant 10-yr revenue growth needed to justify today's price"),
        })
    st.caption(f"Data refreshed: {pd.to_datetime(df['fetched_at']).max():%b %d, %Y}. "
               "Companies where steady-state FCF is negative show no fair value.")

# ============================================================== DEEP DIVE
else:
    st.title("Company deep dive")
    tickers = df.sort_values("ticker")["ticker"].tolist()
    t = st.selectbox("Company", tickers,
                     format_func=lambda x: f"{x} — {df.set_index('ticker').loc[x,'name']}")
    row = df.set_index("ticker").loc[t].to_dict()

    if row["sector"] in EXCLUDED_SECTORS or not row["dcf_applicable"]:
        st.warning(f"**{row['name']}** is in **{row['sector']}** — cash-flow "
                   "DCF isn't meaningful for banks, insurers, or REITs "
                   "(their 'FCF' reflects balance-sheet flows, not operations). "
                   "Dividend-discount or excess-return models apply instead.")
        st.stop()

    a = build_assumptions(row)
    st.sidebar.subheader("Assumptions")
    wacc = st.sidebar.slider("WACC (%)", 6.0, 15.0, float(round(a["wacc"]*100, 1)), 0.25) / 100
    gt = st.sidebar.slider("Terminal growth (%)", 1.0, 4.0, float(a["g_term"]*100), 0.25) / 100
    g0 = st.sidebar.slider("Year-1 revenue growth (%)", -10.0, 60.0,
                           float(round(a["g0"]*100, 1)), 0.5) / 100
    m_ss = st.sidebar.slider("Steady-state EBIT margin (%)", 2.0, 60.0,
                             float(round(a["m_ss"]*100, 1)), 0.5) / 100
    a.update({"g0": g0, "m_ss": m_ss})

    fdf, out = dcf(row, a=a, wacc_override=wacc, terminal_override=gt)
    price = row["price"]

    if out is None:
        st.error("Steady-state FCF is negative under these assumptions — "
                 "no defensible fair value. Raise margin or lower CapEx-heavy growth.")
    else:
        fv, mos = out["fair_value"], out["mos"]
        c1, c2, c3 = st.columns(3)
        c1.metric("Price", f"${price:,.2f}")
        c2.metric("DCF fair value", f"${fv:,.2f}", f"{mos:+.1%}")
        ig = reverse_dcf(row, a=a)
        c3.metric("Market-implied growth",
                  f"{ig:.1%}/yr" if ig is not None else "—")
        st.bar_chart((fdf / 1e9)[["FCF", "PV"]])
        with st.expander("Forecast table ($B)"):
            st.dataframe((fdf / 1e9).round(2), use_container_width=True)

    st.caption(f"Sector: {row['sector']} · Revenue ${row['revenue']/1e9:,.1f}B · "
               f"Beta {row['beta']:.2f}" if row.get("beta") else "")
