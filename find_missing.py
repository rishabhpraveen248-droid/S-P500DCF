import os
from io import StringIO
import pandas as pd
import requests
from supabase import create_client

html = requests.get(
    "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    headers={"User-Agent": "Mozilla/5.0"},
).text
wiki = set(pd.read_html(StringIO(html))[0]["Symbol"])

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

def fetch_all_tickers(page_size=1000):
    """Paginate through the companies table instead of relying on a single
    hardcoded limit, so this keeps working if the table grows past one page."""
    tickers, start = set(), 0
    while True:
        batch = (
            sb.table("companies")
            .select("ticker")
            .range(start, start + page_size - 1)
            .execute()
            .data
        )
        tickers.update(r["ticker"] for r in batch)
        if len(batch) < page_size:
            break
        start += page_size
    return tickers

have = fetch_all_tickers()

missing = sorted(wiki - have)
print("Missing tickers:", missing if missing else "none — all 503 present")
