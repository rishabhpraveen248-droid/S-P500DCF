# S-P500DCF

Automated discounted-cash-flow (DCF) and reverse-DCF valuation screener for the S&P 500. Educational project, not investment advice.

## How it fits together

- `schema.sql` - run once in the Supabase SQL editor to create the `companies`, `fundamentals`, and `valuations` tables, with public read-only row-level-security policies.
- `engine.py` - sector-aware DCF and reverse-DCF valuation engine shared by the pipeline and the app.
- `pipeline.py` - run locally (not on Streamlit Cloud) to pull fundamentals from yfinance for every S&P 500 ticker and write fundamentals/valuations into Supabase. Requires `SUPABASE_URL` and `SUPABASE_KEY` (service-role key) as environment variables.
- `find_missing.py` - compares the current S&P 500 ticker list against what is stored in Supabase, useful after a pipeline run to spot gaps.
- `app.py` - the public Streamlit dashboard. Reads data with the read-only anon/publishable key, configured via `.streamlit/secrets.toml` (`SUPABASE_URL`, `SUPABASE_ANON_KEY`).

## Setup

1. Create a Supabase project and run `schema.sql` in the SQL editor.
2. Install dependencies for the pipeline scripts: `pip install -r "requirements (2).txt"`.
3. Set `SUPABASE_URL` and `SUPABASE_KEY` (service-role key) as environment variables, then run `python pipeline.py` to populate the database (roughly 20-30 minutes for all S&P 500 tickers).
4. Install dependencies for the app: `pip install -r requirements.txt`.
5. Add `SUPABASE_URL` and `SUPABASE_ANON_KEY` to `.streamlit/secrets.toml` (or Streamlit Cloud secrets), then run `streamlit run app.py`.

## Notes

- `app (1).py` is an earlier draft of the dashboard and is not deployed; `app.py` is the current version. It is kept only for reference and can be deleted once no longer needed.
- DCF valuations are not computed for Financials, Real Estate, and similar sectors excluded in `engine.py`, since a cash-flow-based DCF is not structurally meaningful for them.
