# 部署指南 · GitHub × Supabase × Fly.io × Cloudflare Pages

把这个项目从本地搬到公网。约 30 分钟。

```
┌─ GitHub (源代码) ─────────────────────────────────────┐
│ push → 触发 Cloudflare Pages 自动构建                  │
│       → 触发 GitHub Actions 部署后端到 Fly.io          │
└──────┬─────────────────────────────────┬───────────────┘
       │                                 │
       ▼                                 ▼
┌─ Cloudflare Pages ─┐           ┌─ Fly.io ────────────┐
│  static frontend   │ /api/* ►  │  FastAPI + SSE       │
│  (HTML/CSS/JS)     │           │  TradingAgents       │
│  全球 CDN          │           │  Docker 容器         │
└────────┬───────────┘           └──────────┬──────────┘
         │                                  │
         │ JWT + 直接查 Postgres            │ 验证 JWT
         ▼                                  ▼
       ┌──────────── Supabase ────────────────┐
       │  Auth (邮箱/密码/魔法链接)          │
       │  Postgres + RLS (每用户独立历史)    │
       └──────────────────────────────────────┘
```

---

## 0. 准备

需要四个账号（都有免费额度）：

- [GitHub](https://github.com) — 源代码托管
- [Supabase](https://supabase.com) — 数据库 + 认证
- [Fly.io](https://fly.io) — 后端长连接服务
- [Cloudflare](https://dash.cloudflare.com) — 静态前端 + CDN

至少一个 LLM 提供商的 API Key（OpenAI / Anthropic / Google / DeepSeek / Qwen / Kimi / GLM 任意一家）。

---

## 1. 把项目推到 GitHub

```bash
cd trading-strategy-system
git init
git add .
git commit -m "Initial trading-decision-app v3"
gh repo create trading-decision-app --public --source=. --push
# 或在网页 New Repo → 拷贝 git remote add 命令
```

⚠️ **不要提交** `.env` —— 已在 `.gitignore` 里。

---

## 2. 创建 Supabase 项目（5 分钟）

1. 在 <https://supabase.com> 点 **New Project** → 起个名字、设密码、选离自己最近的区域
2. 项目就绪后，左栏 **SQL Editor** → 新建 query → 把 [`supabase/schema.sql`](supabase/schema.sql) 整段粘贴进去 → **Run**
3. 左栏 **Authentication → Providers** → 启用 **Email**（默认开启），按需关掉"邮箱确认"以方便测试
4. 左栏 **Settings → API** 抓三个值，记下来：
   - **Project URL** （形如 `https://xxxxx.supabase.co`）
   - **anon public key** —— 浏览器用，可以公开
   - **JWT Secret** —— 后端验证用，**绝对不能公开**

---

## 3. 部署后端到 Fly.io（10 分钟）

### 3.1 安装 flyctl + 登录

```bash
# macOS
brew install flyctl
# 或 curl -L https://fly.io/install.sh | sh

fly auth signup        # 没账号
fly auth login         # 已有账号
```

### 3.2 创建 app + 设置 secrets + 首次部署 — 一键脚本

**推荐路径**：用仓库自带的 [`scripts/deploy-fly.sh`](../scripts/deploy-fly.sh) 一条龙搞定 — 它会自动：① 验证 flyctl 登录态和 region 合法性，② `fly launch` 创建 app（如果还没建过），③ 把所有非空 secret 一次性 set，④ `fly deploy` 推镜像，⑤ curl `/health` 验证。

```bash
cd <repo-root>          # 一定要在仓库根目录跑

# 1) 把 keys 当成环境变量临时导出（不会进 git）
export DEEPSEEK_API_KEY="sk-..."
export OPENAI_API_KEY="sk-..."                # 至少配一个 LLM key 即可
export SUPABASE_URL="https://xxxxx.supabase.co"
export SUPABASE_ANON_KEY="eyJhbGc..."
export SUPABASE_JWT_SECRET="<step 2.4 的 JWT Secret>"
# 可选: FINNHUB_API_KEY, POLYGON_API_KEY, ALPHA_VANTAGE_API_KEY, FMP_API_KEY,
#       ANTHROPIC_API_KEY, GOOGLE_API_KEY, DASHSCOPE_API_KEY, MOONSHOT_API_KEY,
#       ZHIPU_API_KEY

# 2) 跑脚本
./scripts/deploy-fly.sh
```

App 名默认是 `trading-forge`，region 默认是 `sjc`（美西，离 OpenAI/Anthropic 服务器最近）。要改：

```bash
FLY_APP_NAME=my-name FLY_REGION=hkg ./scripts/deploy-fly.sh
```

之后日常重新部署（不再设 secret）：

```bash
./scripts/deploy-fly.sh --redeploy
```

成功标志：终端最后输出 `✓ Backend deployed to https://trading-forge.fly.dev`，访问 `https://trading-forge.fly.dev/health` 返回 `{"status":"ok"}`。

### 3.2-bis 手动等价命令（不想用脚本时）

```bash
# 创建 app（不立刻部署）
fly launch --no-deploy --copy-config \
  --config trading-decision-app/fly.toml \
  --dockerfile trading-decision-app/Dockerfile \
  --name trading-forge \
  --region sjc

# 配置 secrets
fly secrets set -a trading-forge \
  OPENAI_API_KEY="sk-..." \
  DEEPSEEK_API_KEY="sk-..." \
  SUPABASE_JWT_SECRET="<step 2.4 的 JWT Secret>" \
  SUPABASE_URL="<step 2.4 的 Project URL>" \
  SUPABASE_ANON_KEY="<step 2.4 的 anon key>" \
  CORS_ORIGINS="https://trading-forge.pages.dev" \
  PUBLIC_API_BASE_URL="https://trading-forge.fly.dev"
```

### 3.3 首次部署

```bash
fly deploy --config trading-decision-app/fly.toml \
           --dockerfile trading-decision-app/Dockerfile
```

部署成功后访问 `https://trading-forge.fly.dev/health` 应返回 `{"status":"ok"}`。

> 注：用 `scripts/deploy-fly.sh` 的话这一步**已经包含**在脚本里，不用再单独跑。

### 3.4 配置 GitHub Actions 自动部署（可选）

```bash
# 生成只能部署该 app 的 token
fly tokens create deploy -a trading-forge
# 把输出的 token 加到 GitHub: Settings → Secrets → New repository secret
#   Name:  FLY_API_TOKEN
#   Value: <刚才输出的 token>
```

之后每次 `git push origin main`，[`deploy-backend.yml`](.github/workflows/deploy-backend.yml) 会自动滚动部署。

---

## 4. 部署前端到 Cloudflare Pages（5 分钟）

### 4.1 通过 Dashboard 连接 GitHub

1. <https://dash.cloudflare.com> → **Workers & Pages** → **Create application** → **Pages** → **Connect to Git**
2. 授权访问你的仓库 → 选中本仓库
3. **Set up builds and deployments**：
   - **Framework preset**: None
   - **Build command**: `bash trading-decision-app/cloudflare/build.sh`
   - **Build output directory**: `trading-decision-app/dist`

### 4.2 设置环境变量（Production + Preview 都设）

| 变量 | 值 |
|---|---|
| `PUBLIC_API_BASE_URL` | `https://trading-forge.fly.dev` |
| `SUPABASE_URL` | `https://xxxxx.supabase.co` |
| `SUPABASE_ANON_KEY` | `eyJhbGc...` |
| `AUTH_REQUIRED` | `true` |

### 4.3 触发部署

点 **Save and Deploy**。第一次构建约 1 分钟。完成后访问 `https://trading-forge.pages.dev`（如果 Pages 项目名也叫 `trading-forge`；按你实际命名）。

### 4.4 自定义域名（可选）

Pages 项目 → **Custom domains** → **Set up a custom domain** → 输入域名 → CF 自动签 SSL。
然后在 Fly secrets 里更新 `CORS_ORIGINS=https://yourdomain.com`。

---

## 5. 验证

打开你的 Pages 网址：

1. **首页**正常显示 ✓
2. 点右上角 **登录** → 用邮箱密码注册一个账号 ✓
3. **AI 智能决策** → 启动一次分析（用 DEMO 模式快速测试）✓
4. 完成后看左侧 **历史决策** 是否有这条记录 ✓
5. 在另一台设备 / 隐身窗口登录同一账号 → 历史决策应该同步 ✓
6. 在 Supabase Dashboard → **Table Editor → decisions** 应该看到一条新记录，`run_state` JSONB 里有完整的事件 ✓

---

## 6. 各组件说明

| 组件 | 职责 | 限制 |
|---|---|---|
| **Cloudflare Pages** | 全球 CDN 上的静态前端，包括 HTML / CSS / JS / `_redirects` 把 `/api/*` 转发到 Fly | Free 套餐每月 500 次构建、20k 文件、无限请求 |
| **Fly.io** | 跑 FastAPI + TradingAgents 的 Docker 容器，处理 SSE 长连接 | Free 套餐 3 台 256MB shared-cpu-1x，本项目最少 1024MB（约 $2/月）|
| **Supabase** | Auth + Postgres + RLS，用户/历史/profile | Free 套餐 500MB 数据库、50k MAU、2GB 流量/月 |
| **GitHub** | 源代码 + Actions 自动部署 | Public repo 无限免费 |

**月成本估算**：用 1024MB Fly VM 单机大约 **$2-3 / 月**，其余全部 free 额度内。LLM API 按你自己用多少付。

---

## 7. 常见问题

### SSE 连接被代理切断

Fly + Cloudflare 的组合默认会保持 keep-alive。如果你看到 ~100s 后断流，检查：
- `fly.toml` 里 `auto_stop_machines = "off"`（避免 idle stop 中断 SSE）
- 后端心跳 `: ping\n\n` 每 15 秒发一次（`server.py` 已实现）

### CORS 错误

Fly 后端的 `CORS_ORIGINS` 必须包含你的 Pages 域名。每加一个域名都要重新 `fly secrets set CORS_ORIGINS=...`。

### Supabase 邮箱注册收不到邮件

Supabase Auth → **Email Templates** 检查；或在 **Providers → Email** 关掉 "Confirm email" 直接登录（开发环境用）。

### LLM Key 在哪里管理？

只在 Fly secrets 里。**不要**放 Cloudflare Pages 环境变量（前端会泄漏）。前端只通过 `/api/analyze` 间接使用。

### 想完全本地跑、不部署

不需要做任何这些：

```bash
cd trading-decision-app
cp .env.example .env       # 填 OPENAI_API_KEY
python backend/server.py
# 浏览器打开 http://localhost:8000
# 没设 SUPABASE_URL → 自动用 localStorage 本地保存历史
```

---

## 8. 下次部署的简化流程

代码改完后：

```bash
git push origin main
```

完事。
- Cloudflare Pages 自动重新构建前端
- GitHub Actions 自动 `fly deploy` 后端

如要改 secrets：

```bash
fly secrets set NEW_KEY=value          # 后端
# 或在 Cloudflare Pages dashboard 改前端环境变量后手动 redeploy
```

---

## 9. 安全清单

- [ ] `.env` / 任何含真实 API key 的文件已在 `.gitignore`
- [ ] Supabase **Service Role Key** **从未**出现在前端代码（只用 anon key）
- [ ] Fly secrets 里设了 `SUPABASE_JWT_SECRET` —— 否则 `/api/analyze` 是开放的
- [ ] `CORS_ORIGINS` 限定在你的 Pages 域名而不是 `*`
- [ ] Supabase 表的 RLS 已通过 `schema.sql` 启用（验证：在 Auth 注销状态下尝试 `SELECT * FROM decisions` 应返回 0 行）
- [ ] LLM API key 设了**消费上限**（OpenAI dashboard / Anthropic 等都支持）

---

完事 🎉
