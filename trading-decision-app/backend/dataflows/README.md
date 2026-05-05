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

## Wiring into TradingAgents (v6+ — already done)

Since v6 the wiring is done **automatically** via the patch series in
`patches/0002-premium-dataflows-bridge.patch`:

1. `tradingagents/dataflows/premium_bridge.py` — small shim that imports
   our `dataflows` package (when on PYTHONPATH) and registers each
   configured vendor into TradingAgents' `VENDOR_METHODS`.
2. `tradingagents/dataflows/interface.py` — calls
   `premium_bridge.register(VENDOR_METHODS)` at module load time.

Result: when the host application sets e.g. `FINNHUB_API_KEY` in env,
`finnhub_pro` becomes a first-class vendor that the analysts'
`route_to_vendor("get_news", …)` will pick up.

`agent_runner._run_live` further sets `cfg["data_vendors"]` to put the
premium vendor first in TradingAgents' fallback chain whenever its key
is configured — so users don't even have to know about the
`data_vendors` config.

### Verify it's wired correctly

```python
from tradingagents.dataflows.interface import VENDOR_METHODS
print(list(VENDOR_METHODS["get_news"].keys()))
# → ['alpha_vantage', 'yfinance', 'finnhub_pro']   ← finnhub_pro added by bridge
```

## Token-saving tip

The whole point of this layer is that agents see **summaries**, not raw
JSON. A single Finnhub `/company-news` response can be 30 KB; the
markdown summary is ~600 bytes. Across one analysis (4 analysts × 1-3
calls each) that's ~100K tokens saved on average for **GPT-4-class
models**. Quality goes up too because attention isn't diluted by JSON
boilerplate.
