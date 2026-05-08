# 自选 page redesign — master-detail layout + history matching

**Date:** 2026-05-08
**Status:** Approved, in implementation

## Goal

Turn the 自选 tab from a flat table into a master-detail page where the
sidebar lists watchlist assets and the main panel shows the latest historical
decision for the selected asset. Surface live-quote numbers in Chinese-text
units (万亿 / 亿 / 万) instead of the K/M/B fixed-unit columns.

## Three user-visible changes

1. **History → watchlist matching is automatic.** Every ticker that has a
   decision in the user's history is also in their 自选. New decisions add
   their ticker to 自选 on save (if missing). Existing un-matched tickers
   are backfilled once on next page load.
2. **Master-detail layout.** Asset list moves to a left sidebar; main panel
   shows the latest decision for the selected asset (with a chip strip to
   pick an older one). Empty assets show a quote card + "▶ 启动新决策" CTA.
3. **Chinese-text numbers.** 成交额 and 市值 render as `293 亿美元`,
   `3.62 万亿美元`, `2090 亿港币`, `780 亿人民币` — no fixed-unit columns.

## Layout

```
⭐ 自选            [+ 添加] [📥 导入] [↻ 刷新]    14:35
─────────────────────────────────────────────────────
[全部 17] [美股 9] [港股 3] [加密 4] [龙头股 5]
─────────────────────────────────────────────────────
┌─────────────┐ ┌────────────────────────────────────┐
│ NVDA        │ │ Quote card (price · OHLC · 成交额 · │
│ NVIDIA      │ │            市值 · P/E)              │
│ $148 +2.3%  │ ├────────────────────────────────────┤
├─────────────┤ │ Chip strip: [05-08·Buy] [04-22·Hold]│
│ AAPL        │ ├────────────────────────────────────┤
│ Apple Inc   │ │ Decision body (params/usage/final/  │
│ $234 -0.5%  │ │   matched-strategies)               │
└─────────────┘ └────────────────────────────────────┘
```

- Sidebar ~280px, scrolls independently.
- Main panel scrolls independently.
- Group chips stay above both panes; filter the sidebar only.
- Mobile (<700px) stacks: sidebar on top, main below.

## Sidebar row

```
NVDA
NVIDIA Corp
$148.32   +2.34% ↑
```

- Selected: 3px accent left border + soft background.
- Sort: assets with decisions first (newest decision date wins),
  then assets without decisions, alphabetical within each block.
- Action buttons (▶ 决策 / 🗑 移除) appear on hover or when selected.
- Group filter narrows the list; if the selected ticker drops out,
  auto-select the first remaining row.

## Main panel — three sections

**Quote card (always when ticker selected)**

- Top row: ticker bold, display name dimmed, market badge right-aligned.
- Price + % change (large), OHLC right-aligned mono.
- Bottom row: 成交额, 市值, P/E using Chinese-text formatter.

**Decision chip strip (when ≥1 decision)**

- One chip per decision: `trade_date · rating`.
- Color by rating: Buy/Overweight green, Hold amber, Sell/Underweight red,
  others neutral.
- Latest selected by default; clicking another chip swaps the body.
- Hidden when zero decisions.

**Decision body**

- Rendered by new shared `renderDecisionSections(entry) → html` helper,
  extracted from `HistoryPage.openDrawer()`.
- Sections: 运行参数, 用量, 最终决策, 匹配策略 (same as today's drawer).
- "🪟 在新窗口打开" link in the section header → existing
  `WindowManager.openHistorical(entry)` flow.

**Empty state (no decisions)**

```
还没跑过 NVDA 的决策

[▶ 启动新决策]
```

— quote card stays at top; chip strip + body replaced with this block.

## Auto-matching mechanism

**On decision save** (`History.save()` / `_saveHistoryNonBlocking()`):
after the decision is persisted, call `Watchlist.ensureTicker(ticker)`
which inserts the ticker if not already in `Watchlist.cache`.

**One-time backfill** on `Watchlist.refresh()`: loosen the existing
`autoImported` flag so it runs once even when the watchlist is non-empty.
The flag still guards against repeated runs. Subsequent refreshes are
no-ops because the `History.save()` path keeps things in sync going forward.

## Number formatter

```js
formatLargeCN(value, market)
  → `${num} ${unit} ${currency}`  // e.g. "3.62 万亿美元"
```

- Units: ≥1e12 → 万亿, ≥1e8 → 亿, ≥1e4 → 万, else raw.
- Significant figures: 2-3 (use `toPrecision(3)` then trim).
- Currency by market: us/crypto/commodity/forex/other → 美元,
  hk → 港币, cn → 人民币.
- Returns `"—"` for null/NaN.

## Backend fix

`backend/quotes.py` — Finnhub returns `marketCapitalization` in **millions
USD**. CoinGecko + yfinance return raw USD. Multiply Finnhub's value by
`1e6` so all sources return raw market cap. Frontend now applies one
formatter for all sources without source-sniffing.

## State

- `Watchlist.selectedTicker` — persisted in `localStorage["tda:wl:selected"]`.
- `Watchlist.selectedDecisionId` — in-memory only; resets to "latest" on
  ticker change.
- Default selection: last persisted ticker if it's still in the list,
  otherwise the first row of the unfiltered list.

## Files touched

- `trading-decision-app/static/index.html` — rewrite the `#watchlist`
  section markup.
- `trading-decision-app/static/styles.css` — replace `.watchlist-list*`
  table styles with `.watchlist-pane` (sidebar) + `.watchlist-detail`
  (main) styles; drop `.wl-c-*` column classes.
- `trading-decision-app/static/app.js` —
  - rewrite `Watchlist.render()` for master-detail layout;
  - add `Watchlist.ensureTicker()` and call from `History.save()`;
  - extract `renderDecisionSections(entry)` from `HistoryPage.openDrawer()`,
    reuse in both sites;
  - add `formatLargeCN(value, market)` helper.
- `trading-decision-app/backend/quotes.py` — multiply Finnhub `market_cap`
  by 1e6.

## Out of scope

- Per-row sparklines / mini-charts in the sidebar.
- Drag-to-reorder watchlist entries.
- Filtering decisions in the chip strip (just shows newest 10).
- Changing the 历史 tab itself — drawer behavior unchanged.
