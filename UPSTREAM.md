# TradingAgents 上游同步指南

`TradingAgents/` 子目录是从 [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) 用 `git subtree` 引入的。本指南列出常用维护操作。

## 一次性配置（克隆此仓库后）

```bash
git remote add tradingagents-upstream https://github.com/TauricResearch/TradingAgents.git
```

如果你 fork 了官方仓库（推荐，便于回贡献），同时加：

```bash
git remote add tradingagents-fork git@github.com:<your-username>/TradingAgents.git
```

## 拉上游新功能 / bug 修复

```bash
# 1) 看一眼上游有什么新东西
git fetch tradingagents-upstream
git log HEAD..tradingagents-upstream/main --oneline -- ':(exclude)*'

# 2) 合并到本仓库的 TradingAgents/ 子目录
git subtree pull --prefix=TradingAgents tradingagents-upstream main --squash

# 3) 解决冲突（如果有），跑下我们的 smoke test
cd trading-decision-app/backend
python -c "import server; print('ok')"

# 4) 提交（subtree pull 已生成一个 merge commit，但记得 push）
git push origin main
```

## 我们做了什么改动需要保护？

**目前为止：0 处源码改动**。所有增强都在外部：

- Kimi (Moonshot) provider — 通过 `trading-decision-app/backend/agent_runner.py::_patch_tradingagents_for_extra_providers()` 在导入时 monkey-patch
- 翻译层 — 在我们的 backend 拦截 SSE 事件
- 付费数据源（Finnhub Pro / Polygon / Alpha Vantage / AkShare） — 独立的 `dataflows/` 包，文档说明了如何无破坏地接入 TradingAgents

未来如果你要直接改 TradingAgents 源码（比如把 dataflows 真正接到 analysts 工具列表里），改动会进入 `git subtree pull` 的合并视野，**届时合并冲突可能集中在你改过的文件**。届时 workflow 如下：

```bash
# 把本地补丁单独拎出来作为一个 patch series（避免每次 subtree pull 都重做）
cd TradingAgents
git format-patch HEAD~3 -o ../patches/

# subtree pull 之后重新 apply
cd ..
git subtree pull --prefix=TradingAgents tradingagents-upstream main --squash
cd TradingAgents
git am ../patches/*.patch
```

## 给上游回贡献

```bash
# 假设你修了个 bug，已经在主仓库提交了
git subtree push --prefix=TradingAgents tradingagents-fork bugfix/some-thing
# 然后到 GitHub 网页用这个分支开 PR 回 TauricResearch/TradingAgents
```

## 切换到特定上游版本

```bash
git fetch tradingagents-upstream
# 查看 tags
git tag -l --sort=-version:refname | grep -i agents | head
# 切到某个 tag
git subtree pull --prefix=TradingAgents tradingagents-upstream v0.2.4 --squash
```

## 不再使用 subtree（紧急回退）

```bash
# 把 TradingAgents 目录里所有内容平铺到本仓库历史，断开 subtree 关系
git rm -rf TradingAgents
git commit -m "Drop TradingAgents subtree"
# 之后通过 pip install 或 submodule 改用其他方式
```
