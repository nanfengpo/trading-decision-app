# 智策 · TradingForge

> 多智能体投研工作台 · 12 agents → 78 strategies → 实时可视化

把 [TradingAgents](https://github.com/TauricResearch/TradingAgents) 的多智能体辩论流程、78 条交易策略库、24h 机会扫描、付费数据源接入和翻译层全部装进一个可部署的 Web 应用。支持多用户 / 个人 API Key / 用量追踪 / 暗色模式。

```
┌─ GitHub (源代码) ──────────────────────────────────────┐
│ git push → CF Pages 自动构建 + GH Actions 部署 Fly.io   │
└──────┬─────────────────────────────────┬──────────────┘
       │                                 │
       ▼                                 ▼
┌─ Cloudflare Pages ─┐           ┌─ Fly.io ─────────────┐
│ static frontend    │ /api/*  ► │ FastAPI + SSE         │
│ 全球 CDN           │           │ TradingAgents (多智能体)│
└────────┬───────────┘           └──────────┬──────────┘
         │ JWT + Postgres                    │ 验证 JWT
         ▼                                   ▼
       ┌─────────────── Supabase ──────────────────┐
       │  Auth + RLS:                              │
       │  profiles · decisions · favorites ·       │
       │  opportunities · usage_events             │
       └───────────────────────────────────────────┘
```

## 仓库布局

```
trading-strategy-system/
├── README.md                  ← 你正在看这个
├── docs/                      ← 详细文档
│   ├── DEPLOYMENT.md          完整部署指南（Supabase + Fly + CF）
│   ├── DEVELOPMENT.md         本地开发 + 调试
│   ├── ARCHITECTURE.md        架构与设计选择
│   ├── UPSTREAM.md            TradingAgents subtree 同步
│   └── FUTURE-WORK.md         已识别但未做的优化
├── scripts/                   ← 自动化脚本
│   ├── setup.sh               首次安装
│   ├── upgrade-tradingagents.sh  上游同步 + 重放 patches
│   ├── dev.sh                 本地启动后端
│   └── check-config.sh        诊断 .env / Supabase / 数据源
├── patches/                   ← TradingAgents 本地补丁系列
│   ├── 0001-add-kimi-provider.patch
│   ├── 0002-premium-dataflows-bridge.patch
│   ├── 0003-premium-bridge-expand-detail.patch
│   └── apply-patches.sh
├── trading-decision-app/      ← 我们的应用
│   ├── backend/               FastAPI + 多智能体 wrapper
│   │   ├── server.py
│   │   ├── agent_runner.py
│   │   ├── key_injector.py    ⬅ v8: 多租户 key 注入
│   │   ├── usage_logger.py    ⬅ v8: 颗粒度 token 追踪
│   │   ├── translator.py
│   │   ├── strategy_matcher.py
│   │   ├── model_catalog.py
│   │   ├── dataflows/         付费数据源 + 缓存
│   │   └── opportunities/     24h 机会扫描器
│   ├── static/                前端 (HTML / CSS / JS)
│   ├── supabase/migrations/   DB schema (4 个迁移)
│   ├── cloudflare/build.sh    CF Pages 构建脚本
│   ├── Dockerfile             后端容器
│   ├── fly.toml               Fly.io 部署配置
│   └── .env.example           完整环境变量清单
├── TradingAgents/             ← git subtree, 来自 TauricResearch/TradingAgents
└── .github/workflows/         CI（push to main → fly deploy）
```

## 30 分钟快速上线

跟着 [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) 一步步走：

| 步骤 | 时间 | 做什么 |
|---|---|---|
| 1 | 5 min | `git push` 到你的 GitHub repo |
| 2 | 5 min | Supabase 新建项目 + 跑 SQL 迁移 |
| 3 | 10 min | `fly launch` + `fly secrets set` + `fly deploy` |
| 4 | 5 min | Cloudflare Pages 接 GitHub + 设环境变量 |
| 5 | 5 min | 注册 → 跑一次 → 验证多设备同步 |

或者一键脚本：

```bash
./scripts/setup.sh           # 交互式配置（首次）
./scripts/dev.sh             # 本地启动
./scripts/upgrade-tradingagents.sh  # 拉上游
```

## 单机本地试用（最快路径）

```bash
git clone <your-repo-url>
cd trading-strategy-system

# Python 依赖
pip install -r trading-decision-app/requirements.txt
pip install -r TradingAgents/requirements.txt   # 仅 LIVE 模式需要

# 配 .env（最少配一个 LLM key）
cp trading-decision-app/.env.example trading-decision-app/.env
$EDITOR trading-decision-app/.env

# 启动
./scripts/dev.sh

# → http://localhost:8000
```

不配置任何 key 时自动走 DEMO 模式（脚本化事件，~30 秒走完整链路）。

## 核心功能一览

| 模块 | 文件 |
|---|---|
| 🧠 **多智能体辩论** | TradingAgents 12 个 agent 串行 / 并行执行（B.1 进行中）|
| 📚 **78 条策略库** | `trading-decision-app/static/strategies.js` |
| 📡 **实时可视化** | SSE + cockpit 侧边栏 + 多窗口并行 |
| 💰 **付费数据源** | Finnhub Pro / Polygon / Alpha Vantage / AkShare（[dataflows/README](trading-decision-app/backend/dataflows/README.md)） |
| ⚡ **24h 机会扫描** | BTC 插针 / IV 突变 / 社媒话题暴涨（`opportunities/`） |
| 🌍 **翻译层** | 内部辩论英文 → 中文（DeepSeek/Qwen/GLM/Kimi/OpenAI 任选） |
| 🔐 **多租户** | 每用户自带 LLM Key（`key_injector` + Supabase RLS） |
| 📊 **Token 用量追踪** | 每次 LLM/工具调用都落 `usage_events` 表 |
| ⭐ **收藏 / 评分 / 置顶** | 历史决策 + 策略 + 机会三维度收藏 |
| 🌗 **暗色模式** | localStorage 持久化 + `prefers-color-scheme` 自动 |
| 🌐 **7 家 LLM** | OpenAI / Anthropic / Google / DeepSeek / Qwen / Kimi / GLM |

## 常见任务

| 想做的事 | 看哪个文档 |
|---|---|
| 把项目部署到生产 | [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) |
| 本地开发 / 调试 | [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) |
| 拉 TradingAgents 上游新功能 | [`docs/UPSTREAM.md`](docs/UPSTREAM.md) |
| 加新的付费数据源 | [`trading-decision-app/backend/dataflows/README.md`](trading-decision-app/backend/dataflows/README.md) |
| 理解架构与设计选择 | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| 看后续优化路线图 | [`docs/FUTURE-WORK.md`](docs/FUTURE-WORK.md) |

## 许可与免责

教育目的。本系统不构成投资建议，不保证盈利，不对实盘损失负责。任何实盘前请独立判断或咨询持牌专业人士。
