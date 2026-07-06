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
have = {r["ticker"] for r in sb.table("companies").select("ticker").limit(1000).execute().data}

missing = sorted(wiki - have)
print("Missing tickers:", missing if missing else "none — all 503 present")