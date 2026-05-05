"""
AkShare — free Chinese-market data (A-shares, HK, indices, futures, …).

Module env: AKSHARE_ENABLED=1   (no API key needed; this flag just lets
the factory know you want it enabled — keeps the registry consistent
with the other vendors)

This is a skeleton showing the wiring; install with `pip install akshare`
to make it functional. Network access happens at call time.
"""

from __future__ import annotations

import logging
from typing import Optional

from .cache import cached
from .registry import BaseDataSource, Category, VendorMeta, register
from .summarize import summarize_quotes, summarize_fundamentals

logger = logging.getLogger(__name__)


class AkShareCN(BaseDataSource):
    name = "akshare_cn"
    api_key_env = "AKSHARE_ENABLED"

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _ak(self):
        try:
            import akshare as ak  # type: ignore
            return ak
        except ImportError:
            logger.info("akshare not installed — pip install akshare")
            return None

    @cached(ttl=300)
    def fetch_quote_summary(self, ticker: str) -> Optional[str]:
        ak = self._ak()
        if ak is None:
            return None
        try:
            # 600519.SS  → 600519 ;  HK.0700 → 0700.HK
            sym = ticker.split(".")[0]
            df = ak.stock_zh_a_hist(symbol=sym, period="daily", adjust="qfq")
            if df is None or len(df) < 10:
                return None
            closes = df["收盘"].tolist()[-250:]
            return summarize_quotes({"closes": closes}, ticker)
        except Exception as e:
            logger.warning("akshare quote %s failed: %s", ticker, e)
            return None

    @cached(ttl=3600)
    def fetch_fundamentals_summary(self, ticker: str) -> Optional[str]:
        ak = self._ak()
        if ak is None:
            return None
        try:
            sym = ticker.split(".")[0]
            df = ak.stock_individual_info_em(symbol=sym)
            if df is None or df.empty:
                return None
            kv = dict(zip(df["item"], df["value"]))
            metrics = {
                "peTTM": _to_float(kv.get("市盈率(动)")),
                "pbTTM": _to_float(kv.get("市净率")),
            }
            return summarize_fundamentals(metrics, ticker)
        except Exception as e:
            logger.warning("akshare fundamentals %s failed: %s", ticker, e)
            return None


def _to_float(v):
    try: return float(str(v).replace(",", "").replace("%", ""))
    except (TypeError, ValueError): return None


def _factory() -> AkShareCN:
    return AkShareCN()


register(VendorMeta(
    name="akshare_cn",
    display_name="AkShare (A股 / HK / 期货)",
    api_key_env="AKSHARE_ENABLED",
    categories=[Category.MARKET, Category.FUNDAMENTALS],
    factory=_factory,
))
