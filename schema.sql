-- Run this once in Supabase: SQL Editor > New query > paste > Run
create table if not exists companies (
  ticker text primary key,
  name text, sector text, industry text,
  dcf_applicable boolean default true,   -- false for financials/REITs
  updated_at timestamptz default now()
);

create table if not exists fundamentals (
  ticker text primary key references companies(ticker),
  price float, market_cap float, revenue float, ebitda float,
  operating_income float, net_income float, fcf float,
  cash float, debt float, shares float, beta float,
  rev_growth_3y float, op_margin float,
  fetched_at timestamptz default now()
);

create table if not exists valuations (
  ticker text primary key references companies(ticker),
  fair_value float, margin_of_safety float,
  implied_growth float,           -- reverse DCF result
  wacc float, terminal_growth float,
  verdict text,                   -- UNDERVALUED / NEUTRAL / OVERVALUED / N/A
  computed_at timestamptz default now()
);

-- Public read access for the Streamlit app (anon key)
alter table companies enable row level security;
alter table fundamentals enable row level security;
alter table valuations enable row level security;
create policy "public read" on companies for select using (true);
create policy "public read" on fundamentals for select using (true);
create policy "public read" on valuations for select using (true);
