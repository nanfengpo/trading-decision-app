# 智能交易决策系统 · TradingAgents × 78 Strategies

把 [TradingAgents](../TradingAgents) 的多智能体投研流程和已有的 78 条交易策略库融合到一个网页工作台：

- 输入股票代码 / 日期 / LLM / 研究深度 → 启动一次完整的多智能体分析
- **实时**显示 12 个智能体的运行进度、新闻分析、辩论过程
- 输出 5 档评级（Buy / Overweight / Hold / Underweight / Sell）+ 来自 78 条库的可执行策略匹配（按匹配度排序）

```
┌────────── 浏览器 (SSE) ──────────┐        ┌──────── FastAPI 后端 ───────┐
│  AI 决策 Tab                      │  POST  │  /api/analyze → session id  │
│   ├─ 表单 (ticker/date/llm…)     │ ─────► │                              │
│   ├─ 实时进度看板 (12 agents)     │ event  │  /api/stream/{sid} (SSE)    │
│   ├─ 工具调用 / 日志流            │ stream │   └─ AgentRunner 逐节点 emit│
│   ├─ 4 份分析师报告               │ ◄───── │      ├ TradingAgentsGraph   │
│   ├─ 投资辩论 / 风险三方辩论      │        │      │   (LIVE 模式)        │
│   └─ 最终决策 + Top-5 策略匹配    │        │      └ 脚本演示 (DEMO 模式)│
└──────────────────────────────────┘        └──────────────────────────────┘
                                                       │
                                                       ▼
                                            策略匹配器 (Top-K + 原因)
```

## 快速开始

```bash
# 1) 安装依赖
cd trading-decision-app
pip install -r requirements.txt

# 2) （可选）安装 TradingAgents 依赖以启用 LIVE 模式
cd ../TradingAgents
pip install -r requirements.txt

# 3) 配置 .env（推荐方式）
cd ../trading-decision-app
cp .env.example .env
# 编辑 .env：填上至少一个 API Key（OPENAI/ANTHROPIC/GOOGLE/DEEPSEEK）
#   也可设置 DEFAULT_LLM_PROVIDER / DEFAULT_DEEP_LLM 等默认值

# 4) 启动
python backend/server.py
# 默认监听 http://localhost:8000
```

打开浏览器访问 `http://localhost:8000`。

> 即使没有任何 API Key，系统会自动切换到 **DEMO 模式**，emit 一组脚本化的事件，供 UI 演示和开发调试使用。

## .env 配置

`server.py` 启动时会按如下顺序自动加载 `.env`：

1. 项目根目录：`trading-strategy-system/.env`
2. 应用目录：`trading-strategy-system/trading-decision-app/.env`
3. 当前工作目录：`./.env`

### API Key 变量

| 变量 | 用途 |
|---|---|
| `OPENAI_API_KEY` | OpenAI |
| `ANTHROPIC_API_KEY` | Anthropic Claude |
| `GOOGLE_API_KEY` | Google Gemini |
| `DEEPSEEK_API_KEY` | DeepSeek |
| `DASHSCOPE_API_KEY` | Qwen 通义千问 |
| `MOONSHOT_API_KEY` | Kimi (Moonshot) |
| `ZHIPU_API_KEY` | 智谱 GLM |
| `TRANSLATION_PROVIDER` | 翻译层强制使用某一家（默认按 deepseek→qwen→glm→kimi→openai 顺序自动选） |
| `TRANSLATION_MODEL` | 翻译层强制模型 ID |

页面右上角 `LLM 提供商` 旁边会显示 ✓/✗ 徽标，提示当前提供商的 KEY 是否就绪。

### 表单默认值变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `DEFAULT_LLM_PROVIDER` | 自动 | `openai` / `anthropic` / `google` / `deepseek` |
| `DEFAULT_DEEP_LLM` | 提供商首选 | 任意模型 ID，不在下拉列表中会自动落到"自定义" |
| `DEFAULT_QUICK_LLM` | 提供商首选 | 同上 |
| `DEFAULT_RESEARCH_DEPTH` | 1 | 1–5 |
| `DEFAULT_OUTPUT_LANGUAGE` | Chinese | `Chinese` / `English` |
| `DEFAULT_TICKER` | NVDA | 默认股票代码 |
| `DEFAULT_INSTRUMENT` | stock | 默认品种偏好 |
| `DEFAULT_RISK_TOLERANCE` | 3 | 1–5 |

## 运行模式

| 模式 | 触发条件 | 行为 |
|---|---|---|
| `auto` (默认) | TradingAgents 可导入 + 提供商 Key 在环境变量中 | 选 LIVE，否则 DEMO |
| `live` | 强制 | 调用真实 LLM，产生真实 token 消耗 |
| `demo` | 强制 | 不调用任何 LLM，emit 脚本事件，约 30 秒走完全流程 |

可在表单"运行模式"下拉框中切换。

## 表单字段

| 字段 | 说明 |
|---|---|
| 股票代码 | 任何 yfinance 可识别的代码：`NVDA`, `SPY`, `BTC-USD`, `AAPL` 等 |
| 分析日期 | 通常用今天或最近交易日 |
| LLM 提供商 | OpenAI / Anthropic / Google / DeepSeek（自动从 .env 检测可用 key） |
| 深思模型 | 下拉框，按提供商列出最新模型（GPT-5.4 / Claude Opus 4.6 / Gemini 3.1 Pro / DeepSeek V4 Pro …） |
| 轻思模型 | 下拉框，每个提供商单独的快速模型列表 |
| 自定义模型 | 在两个下拉框最后选 "自定义模型 ID …"，输入任意模型名（适配新发布或私有部署） |
| 研究深度 | 投资辩论与风险讨论各跑 N 轮，N=1 最快、N=5 最详 |
| 输出语言 | 中文 / English |
| 品种偏好 | 用于策略匹配（股票/ETF/加密/黄金/商品/外汇/债券） |
| 风险偏好 | 1-5 档；高于偏好的策略自动降权 |
| 分析师勾选 | 4 类分析师可单独开关 |

## 实时输出（左侧导航 · 单面板视图）

启动后下方 cockpit 出现一个**左侧侧边栏**，每个章节都可点击切换，徽章显示数量/状态：

| 侧边栏项 | 内容 |
|---|---|
| 📊 智能体进度 | 12 个 agent 按团队分组实时刷新（等待/进行中/完成） |
| 📡 事件流 | 工具调用 + Agent 输出 + 系统日志 |
| 📈 市场技术 / 💬 情绪 / 📰 新闻 / 💼 基本面 | 4 份分析师独立报告 |
| 🐂🐻 投资辩论 | 牛/熊研究员逐回合对话 |
| 📋 研究计划 / 🧾 交易提案 | 研究经理裁决 + 交易员方案 |
| ⚖️ 风险辩论 | 激进/中立/保守三方 |
| 🎯 最终决策 + 策略 | 评级 + 解析信号 + 78 条库 Top-5 匹配 |

## 翻译层（方案 B）

TradingAgents 把内部辩论（Bull/Bear、风险三方、Trader、Research Manager）保留为英文以保证推理质量。本系统在后端加了一层翻译：

1. 事件按原文（英文）**立即** emit，前端先显示原文 + 标签 "🔄 中文翻译生成中…"
2. 后端在线程池里调用一个便宜+中文强的模型翻译（**默认 DeepSeek**，可改 Qwen/GLM/Kimi/OpenAI）
3. 翻译完成 emit `translation` 事件，前端按 `msg_id` 把对应段落替换成中文

设置 `TRANSLATION_PROVIDER` / `TRANSLATION_MODEL` 可强制指定。已是中文的内容（分析师报告、最终决策）用启发式自动跳过。

页面右上角 `翻译 · deepseek/deepseek-chat` 徽章实时显示翻译层状态。

## 报告下载

cockpit 右上角两个按钮（运行完成后启用）：

- **⬇ 下载报告 (Markdown)** — 一份完整的 `.md`，含最终决策、策略库匹配、4 份分析师报告、所有辩论（自动选用中文翻译）
- **⬇ JSON** — 全部原始事件流 + 状态快照，便于审计或二次处理

文件名形如 `decision_NVDA_2024-05-10.md`。

## API 端点

| 路径 | 方法 | 说明 |
|---|---|---|
| `/` | GET | 主页 |
| `/api/analyze` | POST | 注册会话，返回 `{session_id}` |
| `/api/stream/{sid}` | GET | SSE 事件流 |
| `/api/strategies-meta` | GET | 类别中文名映射 |
| `/health` | GET | 健康检查 |

### 事件类型（SSE `data` 字段）

| `type` | 何时 emit | 关键字段 |
|---|---|---|
| `ready` | 客户端订阅成功 | `session_id` |
| `init` | 启动后第一条 | `agents`, `selected_analysts`, `config` |
| `mode` | 决定模式后 | `mode: "live" / "demo"` |
| `agent_status` | 任意 agent 状态变化 | `agent_id`, `status` |
| `tool_call` | LLM 调用工具 | `name`, `args` |
| `log` | 任意系统/agent 输出 | `kind`, `content`, `ts` |
| `report` | 分析师 / 经理 / 交易员的结构化报告 | `section`, `title`, `content` |
| `debate` | 牛/熊研究员发言 | `side`, `content` |
| `risk_debate` | 风险三方发言 | `side`, `content` |
| `final_decision` | 投资组合经理裁决 | `decision`, `matched_strategies` |
| `complete` | 所有节点完成 | — |
| `error` | 任意失败 | `message` |

## 项目结构

```
trading-decision-app/
├── backend/
│   ├── server.py             # FastAPI 入口 + SSE
│   ├── agent_runner.py       # 包装 TradingAgentsGraph（含 demo 回退）
│   └── strategy_matcher.py   # 决策 → 策略库匹配
├── static/
│   ├── index.html            # 主页面（4 个 Tab）
│   ├── app.js                # 前端逻辑（tabs / 库 / SSE cockpit）
│   ├── styles.css            # 样式
│   └── strategies.js         # 78 条策略数据（与原 trading-strategy-system.html 共享数据）
├── requirements.txt
└── README.md
```

## 与原 trading-strategy-system.html 的关系

- **保留**：78 条策略库、7 大类别、复杂度/风险评级、筛选与卡片渲染
- **替换**：原"AI 智能问答"被改造为"AI 智能决策"——不再是单次 LLM 推荐，而是完整的多智能体投研流程 + 自动策略库匹配
- **新增**：实时事件流、12 个智能体进度看板、辩论可视化、5 档评级输出

## 调试小贴士

- 第一次跑建议用 `mode = demo` + `research_depth = 1`，30 秒看完整链路。
- LIVE 模式下首次启动可能较慢（拉取 yfinance 数据 + 模型预热）。
- 如果策略匹配为空，多半是 `final_decision.raw` 中没出现可识别的关键词；可在 `strategy_matcher.py::_parse_decision` 中扩展。
- 如需把策略库换成你自己的，编辑 `static/strategies.js` 中的 `STRATEGIES` 即可，前端和后端匹配器都会感知。

## 许可与免责

教育目的。本系统不构成投资建议，不保证盈利，不对任何实盘损失负责。任何实盘操作前请独立判断或咨询持牌专业人士。
