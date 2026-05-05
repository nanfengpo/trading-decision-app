# 开发指南

针对**本地调试 / 二次开发 / 加新功能**的人。生产部署看 [`DEPLOYMENT.md`](DEPLOYMENT.md)。

## 快速启动（5 分钟）

```bash
# 1. 克隆 + Python 依赖
git clone <your-repo-url>
cd trading-strategy-system
pip install -r trading-decision-app/requirements.txt
pip install -r TradingAgents/requirements.txt    # LIVE 模式才需要

# 2. 最少配置 — 复制 .env.example 填一个 LLM key
cp trading-decision-app/.env.example trading-decision-app/.env
$EDITOR trading-decision-app/.env
# 至少填: DEEPSEEK_API_KEY=sk-...   或者任何其他 *_API_KEY

# 3. 启动
./scripts/dev.sh
# → http://localhost:8000
```

不填任何 LLM key → 自动走 **DEMO 模式**（脚本化事件，~30s 走完整链路，0 token 消耗）。

## 仓库结构（开发者视角）

```
trading-strategy-system/
├── TradingAgents/              git subtree, 上游
│   └── tradingagents/
│       ├── agents/             ⚠ 不要手改（上游会冲突）
│       ├── dataflows/
│       │   ├── interface.py    ⚠ 已被我们 0002 patch 改过
│       │   ├── premium_bridge.py  ⬅ 我们的 patch 0002+0003 创建
│       │   └── ...
│       ├── llm_clients/        ⚠ 已被我们 0001 patch 改过
│       └── graph/
├── trading-decision-app/
│   ├── backend/                ✏ 你大部分时间编辑这里
│   │   ├── server.py           FastAPI 路由 + SSE
│   │   ├── agent_runner.py     TradingAgentsGraph wrapper
│   │   ├── key_injector.py     多租户 key 注入
│   │   ├── usage_logger.py     token 颗粒度追踪
│   │   ├── translator.py       英→中翻译
│   │   ├── strategy_matcher.py 决策→78 策略匹配
│   │   ├── model_catalog.py    下拉框模型清单
│   │   ├── dataflows/          付费数据源
│   │   └── opportunities/      24h 机会
│   ├── static/                 ✏ 前端三件套
│   ├── supabase/migrations/    SQL 模式（4 个文件）
│   └── .env.example            完整环境变量清单
├── patches/                    ✏ TradingAgents 本地补丁
│   └── apply-patches.sh
├── scripts/                    ✏ 自动化
└── docs/                       ✏ 你正在看这个
```

## 开发循环

### 改前端（HTML / CSS / JS）

后端 FastAPI 直接 serve 静态文件，**保存即生效**，浏览器刷新就好。

```bash
./scripts/dev.sh
# 改 static/app.js → 浏览器 Cmd+R
```

### 改后端 Python

```bash
# 默认 dev 模式开了 --reload，改完保存自动重启
./scripts/dev.sh

# 调试一个特定模块
cd trading-decision-app/backend
python -c "import server; ..."
```

### 改 TradingAgents 源码

只在四个明确的"插座"位置改（[ARCHITECTURE.md](ARCHITECTURE.md) 有详细说明），改完后**生成 patch 文件**：

```bash
# 1. 编辑 TradingAgents/tradingagents/<file>.py
# 2. 验证可以跑通
./scripts/dev.sh

# 3. 把当前改动捕获为新 patch
git diff TradingAgents/tradingagents/path/to/file.py \
  > patches/0004-my-new-feature.patch

# 4. 提交
git add patches/ TradingAgents/
git commit -m "feat: ..."
```

### 拉 TradingAgents 上游新版本

```bash
./scripts/upgrade-tradingagents.sh
# 自动 git subtree pull → apply patches --check → 报告冲突
```

详见 [`UPSTREAM.md`](UPSTREAM.md)。

### 改 Supabase 模式

```bash
# 1. 写新迁移
$EDITOR trading-decision-app/supabase/migrations/0005_my_change.sql

# 2. 在 Supabase Dashboard SQL Editor 粘贴 + Run
# (开发期没有自动 migrate；生产可以用 supabase CLI)

# 3. 提交
git add trading-decision-app/supabase/migrations/0005_my_change.sql
git commit -m "feat(db): ..."
```

## 调试技巧

### 看 SSE 事件流（最直观）

```bash
# 启动一个 demo 决策并打印所有事件
SID=$(curl -s -X POST http://localhost:8000/api/analyze \
  -H 'Content-Type: application/json' \
  -d '{"ticker":"NVDA","trade_date":"2024-05-10","mode":"demo"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['session_id'])")

curl -sN "http://localhost:8000/api/stream/$SID"
```

事件类型：`init / mode / agent_status / tool_call / log / report / debate / risk_debate / final_decision / translation / usage_event / usage / complete / error`.

### 验证付费数据源是否生效

```bash
# 设 key
export FINNHUB_API_KEY=sk-...

# 跑 dev 模式，看分析师工具调用日志中的 vendor 名
./scripts/dev.sh

# 在浏览器跑一次 NVDA 决策；终端会打印
#   route_to_vendor → finnhub_pro for get_news (...)
```

### 验证缓存命中率

```bash
curl http://localhost:8000/api/dataflows/cache-stats
# {"hits": N, "misses": M, "evictions": ..., "size": ..., "skipped_none": ...}
```

### 验证 KeyInjector 没漏掉用户 key

```bash
# 1. 把 backend .env 中的 OPENAI_API_KEY 删掉
# 2. 启动 dev 服务器，登录某用户，在 Profile 里给他配置 OPENAI_API_KEY
# 3. 跑一次 LIVE 决策 — 应该用上他的个人 key
# 4. 再跑一个 demo 决策；查 backend 日志中没有暴露明文 key
```

### 验证 Supabase RLS 真隔离

```bash
# 注册两个用户 A 和 B
# 各自跑一次决策
# 用 A 的 token 调用 /rest/v1/decisions
curl "$SUPABASE_URL/rest/v1/decisions" \
  -H "apikey: $SUPABASE_ANON_KEY" \
  -H "Authorization: Bearer <A's JWT>"
# 只应该返回 A 的决策；B 的决策一行都不出现
```

## 常见问题

### `langchain_core.messages` import 失败

`pip install -r TradingAgents/requirements.txt`，只需 LIVE 模式。

### CORS 错误

Backend `.env` 加 `CORS_ORIGINS=http://localhost:5173,https://yourpages.dev`（多个用逗号）。

### Supabase JWT 验证失败

后端 `.env` 里 `SUPABASE_JWT_SECRET` 必须和你 Supabase 项目 `Settings → API → JWT Secret` 一字不差。注意它和 anon key 不同。

### 翻译层不工作

检查 `/api/runtime-config.js` 里有没有 `SUPABASE_URL`；查 backend 日志看 `translator: using provider=...` 这行。需要至少一个翻译源 key（推荐 `DEEPSEEK_API_KEY`，最便宜+中文好）。

### 加新功能想跑测试

```bash
# 后端目前没有 unit test 套件；最快的烟雾测试是：
cd trading-decision-app/backend
python -c "
import server
from fastapi.testclient import TestClient
c = TestClient(server.app)
# ... your assertions
"
```

`patches/apply-patches.sh --check` 是最好的"补丁是否应用得上"快速测试。

## 提交前检查清单

- [ ] `./scripts/dev.sh` 启得起来，浏览器能打开
- [ ] 跑过一次 demo 决策（无 key 也能跑）
- [ ] 改了 TradingAgents 的话：`bash patches/apply-patches.sh --reverse && bash patches/apply-patches.sh` 能干净往返
- [ ] 改了 schema 的话：迁移 SQL 是 idempotent（可以多次 Run）
- [ ] 没有 hard-coded API key、Supabase secret、用户邮箱
- [ ] `.env` 不在 git diff 里（被 .gitignore 兜住了，但 double-check）
