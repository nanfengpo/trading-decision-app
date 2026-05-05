# 架构与设计选择

## 三层职责分离

```
┌─ 前端 (Cloudflare Pages) ────────────────────────────────────────┐
│  HTML/CSS/JS · Supabase JS client · 多窗口 cockpit · SSE 订阅   │
│  ✓ 直接读写自己的 Supabase 数据（受 RLS 保护）                   │
│  ✓ 把用户 API key 注入 /api/analyze 请求                        │
└────────────────────────────┬────────────────────────────────────┘
                             │ /api/analyze (POST + JWT)
                             │ /api/stream/{sid} (SSE)
┌────────────────────────────▼────────────────────────────────────┐
│  后端 (Fly.io)                                                  │
│  ┌─ FastAPI ──────────────────────────────────────────────────┐ │
│  │ - /api/analyze: 创建 session, 验证 JWT                     │ │
│  │ - /api/stream/{sid}: SSE event-source                     │ │
│  │ - /api/dataflows: vendor 状态                             │ │
│  │ - /api/opportunities: 24h 机会 feed                       │ │
│  └────────────┬───────────────────────────────────────────────┘ │
│               │ KeyInjector 注入用户 key                         │
│               ▼                                                  │
│  ┌─ TradingAgentsGraph (LangGraph 多智能体) ──────────────────┐ │
│  │ Market → Social → News → Fundamentals (sequential)        │ │
│  │  → Bull ⇄ Bear ⇄ ResearchManager                          │ │
│  │  → Trader → Risk{Aggr,Cons,Neut} → PortfolioManager       │ │
│  │  ↑                                                         │ │
│  │  premium_bridge.register() 把付费源注入 VENDOR_METHODS    │ │
│  │  StatsCallbackHandler + GranularStatsHandler 跟踪 token   │ │
│  └────────────┬───────────────────────────────────────────────┘ │
│               │ HTTP                                            │
│               ▼                                                  │
│  ┌─ premium dataflows (我们自己的) ──────────────────────────┐ │
│  │ Finnhub Pro · Polygon · Alpha Vantage · AkShare           │ │
│  │ + summarize 层 (raw JSON → ~200 token markdown)           │ │
│  │ + cache 层 (TTL + LRU, 跨用户共享)                        │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
       ┌─────────────── Supabase (DB + Auth) ───────────────┐
       │  profiles · decisions · favorites · opportunities  │
       │  usage_events                                      │
       │  全部启用 RLS = auth.uid() = user_id              │
       └────────────────────────────────────────────────────┘
```

## 关键设计决策

### 1. TradingAgents 不 fork，用 git subtree + 三处 patch

**痛点**：把 TradingAgents 当 lib 用就够了，不需要全面 fork；但又不可避免要打几处补丁（接付费数据、加 Kimi）。

**选择**：`git subtree add` 把上游引入仓库，本地补丁存为 `patches/00*.patch`，用 `apply-patches.sh` 自动重放。

**优势**：
- `git clone` 一次完事（不像 submodule）
- 上游同步用 `git subtree pull`，再 `bash patches/apply-patches.sh` 即可
- 我们的修改全部聚在 4 个文件、3 个 patch，未来上游冲突概率低

详见 [`UPSTREAM.md`](UPSTREAM.md)。

### 2. "改插座，不改电路" — 仅在 4 处稳定扩展点改

| 文件 | 改什么 | 为什么稳定 |
|---|---|---|
| `llm_clients/factory.py` | `_OPENAI_COMPATIBLE` 加 `kimi` | 一个 tuple 字面量，上游迭代极少触碰 |
| `llm_clients/openai_client.py` | `_PROVIDER_CONFIG` 加 Kimi entry | dict 字面量，模式相同 |
| `dataflows/interface.py` | 末尾追加 `premium_bridge.register()` 调用 | 注入式扩展，无侵入 |
| `dataflows/premium_bridge.py` | **新文件**（不修改既有文件） | 全新模块，永不冲突 |

明确 **不改** 的：分析师 prompts (`agents/analysts/`), 研究员/风险 (`agents/researchers/`, `risk_mgmt/`), 编排 (`graph/`)。这些是上游核心 IP 和迭代主战场。

### 3. 数据源加在 VENDOR_METHODS，不在 @tool 函数

TradingAgents 内部已有 `VENDOR_METHODS = {tool_name: {vendor: impl, ...}}` 调度表 + `route_to_vendor()` 兜底链。我们**只往这个表里追加**条目，不动 @tool 函数：

```python
# tradingagents/dataflows/premium_bridge.py 大致逻辑
for vendor_meta in Registry.all():
    if vendor_meta.api_key_env and os.environ.get(vendor_meta.api_key_env):
        for method, (cat, builder) in _METHOD_BINDINGS.items():
            VENDOR_METHODS[method][vendor_meta.name] = builder(src)
```

agent_runner 进一步把 `cfg["data_vendors"]` 设为 `"finnhub_pro,..."`，把付费源放到 fallback 链最前面。

### 4. 翻译层方案 B（拦截 SSE 事件，不改 prompt）

TradingAgents 的内部辩论（Bull/Bear、Risk 三方、Trader、Research Manager）刻意保留英文以保推理质量。我们在后端拦截 `report` / `debate` / `risk_debate` / `final_decision` 事件：

1. 立即 emit 原文（带 `msg_id`）
2. 后台线程池调用便宜+中文强的模型翻译（默认 DeepSeek）
3. 完成后 emit `translation` 补丁事件
4. 前端按 `msg_id` 替换段落

启发式 `is_chinese()` 自动跳过已是中文的内容，避免重复翻译。

### 5. 多租户 KeyInjector — process-wide 锁 + 短 critical section

**问题**：TradingAgents 在 LLM 客户端构造时读 `os.environ`。`os.environ` 全进程共享。多用户并发会冲突。

**方案**（v8）：

```python
with key_injector.inject(req.api_keys):    # acquires lock + sets env
    graph = TradingAgentsGraph(config=cfg)  # captures keys in client objects
    # 立即出 with 块
# graph.stream() 跑余下流程，不再访问 env，可与其他用户并发
```

锁仅持有几百毫秒（构造期），之后多用户在 stream 阶段完全并发。

### 6. 用量追踪两层：聚合（StatsCallbackHandler）+ 颗粒度（GranularStatsHandler）

| 层 | 实现 | 落地 |
|---|---|---|
| 聚合 | `cli/stats_handler.py` (TradingAgents 自带) | 单条 `usage` SSE 事件 → `decisions.run_state.usage` JSONB |
| 颗粒度 | `usage_logger.GranularStatsHandler` (我们写的) | 每次 LLM/工具调用一条 `usage_event` SSE → 前端批量插入 `usage_events` 表 |

颗粒度数据支持 Profile 页"近 90 天 token 折线"等分析查询。

### 7. 缓存层（dataflows/cache.py）

进程内 OrderedDict + TTL，每个 vendor `fetch_*` 装饰：

```python
@cached(ttl=600)  # news 10 分钟
def fetch_news_summary(self, ticker, lookback_days=7):
    ...
```

按类别选 TTL：news 10m / quotes 5m / fundamentals 1h / insider 30m。`None` 不缓存（避免 transient 失败被锁死）。

跨用户共享同 ticker 查询时缓存命中率特别高 — 同一时段 100 个用户分析 NVDA，只打 vendor 一次。

### 8. SSE 而非 WebSocket

为什么：
- TradingAgents 流式输出**单向**（后端→前端）
- HTTP/1.1 keep-alive 在 Cloudflare + Fly 组合上比 WebSocket 友好
- 前端 `EventSource` 自动重连 + 自动 last-event-id
- Cloudflare Pages 的 `_redirects` 直接代理 SSE 没问题

代价：每 15s 心跳 `: ping` 防代理超时（在 `server.py` 的 stream 端实现）。

### 9. 前端选择不打包构建

直接的 HTML + 三个 `<script>` 标签。原因：
- 应用复杂度还在"几千行 vanilla JS"档位
- 不依赖 React/Vue 把启动时间从 100ms 推到 1s
- Cloudflare Pages 一份 `bash build.sh` 就完事
- 看代码可以直接读 `static/app.js`，不用 sourcemap

未来如果要 Vue/React，可以无痛切换 — 现有 cockpit DOM 全用 class-based 选择器，便于 React 化。

### 10. Cloudflare Pages 不能跑 TradingAgents

CF Pages 是**纯静态托管**，CF Workers 是 JS/Python (Pyodide) runtime，**都不能跑 LangGraph + langchain**。所以：
- 前端：CF Pages（全球 CDN）
- 后端：必须跑在能容纳 Python + langchain + numpy 的 host（Fly.io / Render / Railway / 自建 VPS）
- DB + Auth：Supabase（JS-from-browser 直连，不经过我们后端）

这种分裂部署看起来麻烦，但实际上：
- CF Pages 完全免费
- Fly.io 单 1GB VM ~$2/月
- Supabase Free 套餐够用很久（500MB DB / 50k MAU）
- **总成本 < $5/月**

## 流量路径全图

一次 LIVE 决策的完整数据流：

```
用户在浏览器点 "启动新决策"
  ↓
前端 fetch /api/analyze (POST, JWT, api_keys+user_id+ticker+...)
  ↓
CF Pages _redirects 代理到 Fly.io
  ↓
Fly: server.py
  - 验证 JWT (SUPABASE_JWT_SECRET)
  - 创建 session, 返回 sid
  ↓
前端 new EventSource(/api/stream/{sid})
  ↓
Fly: agent_runner.run() → _run_live()
  - 进入 KeyInjector(api_keys) 锁
  - 构造 TradingAgentsGraph + StatsCallbackHandler + GranularStatsHandler
  - 退出锁
  - graph.stream():
      - Market analyst → /tool: get_news → premium_bridge → finnhub_pro → cache?
      - 每条 LLM 输出 → SSE: usage_event {kind:llm_call, tokens}
      - 工具调用 → SSE: usage_event {kind:tool_call}
      - 报告生成 → SSE: report
      - 翻译层后台 → SSE: translation
      - ... 12 个 agent 全程 ...
      - 最终 → SSE: final_decision + usage + complete
  ↓
前端实时渲染
  ↓
complete 事件后:
  - History.save() → Supabase decisions 表
  - _flushUsageEvents() → Supabase usage_events 表（每条调用一行）
  ↓
用户切到"个人中心"看用量
  ↓
前端 SELECT * FROM usage_summary WHERE user_id = auth.uid()
  ↓
渲染近 90 天 token / call 统计
```

## 设计未决项

- **B.1 并行分析师** — 需要 `AgentState.messages` 的命名空间化或子图隔离（详见 [`FUTURE-WORK.md`](FUTURE-WORK.md)）
- **FMP / Nasdaq Data Link / JQData / RQData** — 个人中心 UI 已有 key 输入框，但没写 vendor 模块
- **prompt 紧凑化** — 估计省 10-15% input token，需要逐 analyst 检查
- **opportunity scanner 扩到云端** — 当前在 backend 进程内运行；移到独立 worker 可以横向扩展
