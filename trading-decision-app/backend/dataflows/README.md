# dataflows — premium data-source layer

Why this exists: TradingAgents ships with yfinance + free Finnhub by default.
That's fine for a demo but slow, capped, and missing options/macro/Chinese-market
coverage. This package lets users plug in paid data without forking
TradingAgents.

## Architecture

```
agents (TradingAgents)
   │
   │  call dataflows.get_source("news") .fetch_news_summary("NVDA")
   ▼
┌─ factory.get_source ─────────────────────────────────┐
│  picks first configured vendor in this category      │
└──────────────┬───────────────────────────────────────┘
               ▼
       ┌─ vendor module ──────────┐
       │  finnhub_pro.py          │
       │  polygon_io.py           │  ← raw HTTP
       │  alpha_vantage.py        │
       │  akshare_cn.py           │
       └──────────────┬───────────┘
                      ▼
              ┌─ summarize.py ──────────┐
              │  summarize_news()        │
              │  summarize_quotes()      │  ← cuts JSON to ~200 tokens
              │  summarize_fundamentals()│
              └──────────────┬───────────┘
                             ▼
                  agent gets a tiny markdown blob
                  (≈10× cheaper, ≈less noise)
```

## Adding a new vendor — the 4 steps

1. Create `backend/dataflows/yourvendor.py`:

```python
from .registry import BaseDataSource, Category, VendorMeta, register
from .summarize import summarize_news

class MyVendor(BaseDataSource):
    name = "myvendor"
    api_key_env = "MYVENDOR_API_KEY"

    def fetch_news_summary(self, ticker, lookback_days=7):
        if not self.is_configured:
            return None
        items = self._call_api(...)
        return summarize_news(items, top_k=5, ticker=ticker)

register(VendorMeta(
    name="myvendor",
    display_name="My Vendor",
    api_key_env="MYVENDOR_API_KEY",
    categories=[Category.NEWS],
    factory=lambda: MyVendor(),
))
```

2. Add an import line in `dataflows/__init__.py` so it self-registers:

```python
from . import yourvendor   # noqa: F401
```

3. Set `MYVENDOR_API_KEY` in your `.env` (or per-user via the Profile page).

4. Optional pin: set `DATAFLOW_NEWS=myvendor` to force this vendor for news
   over any other registered news provider.

## Vendor status (this repo)

| Vendor | Module | Categories | Status |
|---|---|---|---|
| Finnhub Pro | `finnhub_pro.py` | news, fundamentals, social, market | ✅ full |
| Polygon.io | `polygon_io.py` | market, news | ✅ market+news, options TODO |
| Alpha Vantage | `alpha_vantage.py` | market, fundamentals | ✅ |
| AkShare (CN) | `akshare_cn.py` | market, fundamentals | ✅ skeleton |
| FMP Premium | — | fundamentals | TODO |
| Nasdaq Data Link | — | macro | TODO |
| JQData / RQData | — | CN market+fundamentals | TODO |

## Wiring into TradingAgents

The cleanest place is `agents/utils/agent_utils.py` where the analyst tools
are defined. Replace each tool's body to first try
`dataflows.get_source(category).fetch_*()` and fall back to the existing
yfinance call when the source returns None:

```python
# tradingagents/agents/utils/agent_utils.py
from dataflows import get_source

@tool
def get_news(query, start_date, end_date):
    src = get_source("news")
    if src:
        out = src.fetch_news_summary(query, lookback_days=7)
        if out: return out
    return _yfinance_news_fallback(query, start_date, end_date)
```

That's the **minimum diff** strategy: pre-pend the premium path; keep the
free path as the fallback.

## Token-saving tip

The whole point of this layer is that agents see **summaries**, not raw
JSON. A single Finnhub `/company-news` response can be 30 KB; the
markdown summary is ~600 bytes. Across one analysis (4 analysts × 1-3
calls each) that's ~100K tokens saved on average for **GPT-4-class
models**. Quality goes up too because attention isn't diluted by JSON
boilerplate.
