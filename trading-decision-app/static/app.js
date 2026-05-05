/* =========================================================================
   Trading Decision App — frontend (v2)

   Modules:
     - Theme           dark / light toggle
     - Library         78-strategy filter UI
     - DecisionForm    inputs + provider/model dropdowns
     - DecisionWindow  one analysis run with its own DOM, state, SSE
     - WindowManager   tab strip + concurrent windows
     - History         localStorage persistence + restore
   ========================================================================= */

"use strict";

// =========================================================================
// Shared utilities
// =========================================================================
function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[c]);
}

function mdLite(text) {
  if (!text) return "";
  let out = escapeHtml(text);
  out = out.replace(/^####\s+(.+)$/gm, "<h4>$1</h4>");
  out = out.replace(/^###\s+(.+)$/gm, "<h3>$1</h3>");
  out = out.replace(/^##\s+(.+)$/gm, "<h2>$1</h2>");
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
  out = out.replace(/(\|.+\|\n\|[-: |]+\|\n(?:\|.+\|\n?)+)/g, block => {
    const lines = block.trim().split("\n");
    const head = lines[0].split("|").slice(1, -1).map(c => `<th>${c.trim()}</th>`).join("");
    const rows = lines.slice(2).map(l =>
      "<tr>" + l.split("|").slice(1, -1).map(c => `<td>${c.trim()}</td>`).join("") + "</tr>"
    ).join("");
    return `<table><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table>`;
  });
  out = out.replace(/(^|\n)(\s*[-*]\s+.+(?:\n\s*[-*]\s+.+)*)/g, (_, p, body) => {
    const items = body.trim().split(/\n/).map(l => `<li>${l.replace(/^\s*[-*]\s+/, "")}</li>`).join("");
    return `${p}<ul>${items}</ul>`;
  });
  out = out.replace(/\n{2,}/g, "</p><p>");
  return `<p>${out}</p>`;
}

function uid() { return "w" + Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4); }

function isMostlyChinese(s) {
  if (!s) return true;
  let zh = 0, total = 0;
  for (const c of s) {
    if (/[一-鿿]/.test(c)) zh++;
    if (/[a-zA-Z一-鿿]/.test(c)) total++;
  }
  return total === 0 || zh / total >= 0.30;
}

// =========================================================================
// Theme manager (dark / light)
// =========================================================================
const Theme = {
  KEY: "tda:theme",
  init() {
    const saved = localStorage.getItem(this.KEY);
    const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    const theme = saved || (prefersDark ? "dark" : "light");
    this.set(theme);
    const btn = document.getElementById("theme-toggle");
    if (btn) btn.addEventListener("click", () => this.toggle());
  },
  set(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(this.KEY, theme);
    const btn = document.getElementById("theme-toggle");
    if (btn) btn.textContent = theme === "dark" ? "☀️" : "🌙";
  },
  toggle() {
    const cur = document.documentElement.getAttribute("data-theme") || "light";
    this.set(cur === "dark" ? "light" : "dark");
  },
};

// =========================================================================
// Constants
// =========================================================================
const ANALYST_KEYS = ["market", "social", "news", "fundamentals"];
const CUSTOM_VALUE = "__custom__";

const AGENT_DISPLAY_ZH = {
  "Market Analyst": "市场分析师",
  "Social Analyst": "情绪分析师",
  "News Analyst": "新闻分析师",
  "Fundamentals Analyst": "基本面分析师",
  "Bull Researcher": "牛市研究员",
  "Bear Researcher": "熊市研究员",
  "Research Manager": "研究经理",
  "Trader": "交易员",
  "Aggressive Analyst": "激进风险分析师",
  "Neutral Analyst": "中立风险分析师",
  "Conservative Analyst": "保守风险分析师",
  "Portfolio Manager": "投资组合经理",
};
const TEAM_ZH = {
  "Analyst Team": "数据分析团队",
  "Research Team": "投资研究团队",
  "Trading Team": "交易执行团队",
  "Risk Management": "风险管理团队",
  "Portfolio Management": "投资组合管理",
};
const REPORT_TITLE_ZH = {
  market_report: "市场技术分析",
  sentiment_report: "情绪分析",
  news_report: "新闻分析",
  fundamentals_report: "基本面分析",
  investment_plan: "研究经理 · 投资计划",
  trader_investment_plan: "交易员 · 交易提案",
  final_trade_decision: "投资组合经理 · 最终决策",
};

// =========================================================================
// Tabs (top-level: 首页 / AI 决策 / 策略库)
// =========================================================================
function initTabs() {
  document.querySelectorAll("nav.tabs .tabs-left button").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("nav.tabs .tabs-left button").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const target = btn.dataset.tab;
      document.querySelectorAll("section.tab-content").forEach(s => s.classList.remove("active"));
      document.getElementById(target).classList.add("active");
    });
  });
}

// =========================================================================
// Library (78 strategies — unchanged from v1)
// =========================================================================
const RISK_NAMES = { 1: "极低", 2: "较低", 3: "中等", 4: "较高", 5: "极高" };
const filterState = { cat: [], inst: [], tool: [], view: [], horizon: [], complexity: [], risk: [], search: "" };

function initLibrary() {
  if (typeof STRATEGIES === "undefined") return;
  document.querySelectorAll("[data-filter]").forEach(chip => {
    chip.addEventListener("click", () => {
      const f = chip.dataset.filter, v = chip.dataset.value;
      const arr = filterState[f];
      const i = arr.indexOf(v);
      if (i >= 0) { arr.splice(i, 1); chip.classList.remove("active"); }
      else { arr.push(v); chip.classList.add("active"); }
      renderLibrary();
    });
  });
  const searchEl = document.getElementById("search");
  if (searchEl) {
    searchEl.addEventListener("input", e => { filterState.search = e.target.value.trim().toLowerCase(); renderLibrary(); });
  }
  const clearBtn = document.getElementById("clear-filters");
  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      Object.keys(filterState).forEach(k => filterState[k] = (k === "search" ? "" : []));
      document.querySelectorAll("[data-filter].active").forEach(c => c.classList.remove("active"));
      if (searchEl) searchEl.value = "";
      renderLibrary();
    });
  }
  const totalEl = document.getElementById("stat-total");
  if (totalEl) totalEl.textContent = STRATEGIES.length;
  renderLibrary();
}

function renderLibrary() {
  const list = document.getElementById("strategy-list");
  if (!list) return;
  const filtered = STRATEGIES.filter(s => {
    if (filterState.cat.length && !filterState.cat.includes(s.cat)) return false;
    if (filterState.inst.length && !filterState.inst.some(v => (s.inst || []).includes(v))) return false;
    if (filterState.tool.length && !filterState.tool.some(v => (s.tool || []).includes(v))) return false;
    if (filterState.view.length && !filterState.view.some(v => (s.view || []).includes(v))) return false;
    if (filterState.horizon.length && !filterState.horizon.some(v => (s.horizon || []).includes(v))) return false;
    if (filterState.complexity.length && !filterState.complexity.includes(String(s.complexity))) return false;
    if (filterState.risk.length && !filterState.risk.includes(String(s.risk))) return false;
    if (filterState.search) {
      const blob = (s.name + " " + s.en + " " + (s.desc || "")).toLowerCase();
      if (!blob.includes(filterState.search)) return false;
    }
    return true;
  });
  const countEl = document.getElementById("filter-count");
  if (countEl) countEl.textContent = `显示 ${filtered.length} / ${STRATEGIES.length} 条策略`;
  if (!filtered.length) {
    list.innerHTML = `<div class="no-results">没有匹配的策略。建议减少筛选条件，或点击"清空筛选"重置。</div>`;
    return;
  }
  list.innerHTML = filtered.map(s => `
    <div class="strategy-card" data-id="${s.id}">
      <div class="header">
        <div class="header-content">
          <div class="card-line-1">
            <span class="num">${s.num}</span>
            <span class="name-text">${s.name}</span>
            <span class="en">· ${s.en}</span>
            <button class="fav-btn ${typeof Favorites !== 'undefined' && Favorites.isFavorited('strategy', s.id) ? 'on' : ''}"
                    data-fav-strategy="${s.id}" title="收藏 / 取消收藏"
                    style="margin-left:auto;">${typeof Favorites !== 'undefined' && Favorites.isFavorited('strategy', s.id) ? '★' : '☆'}</button>
          </div>
          <div class="desc">${s.desc || ""}</div>
          <div class="card-tags">
            <span class="tag cat-${s.cat}">${CAT_NAMES[s.cat]}</span>
            <span class="tag-group">
              <span class="tag-label">观点</span>
              ${(s.view || []).map(v => `<span class="tag view-tag">${VIEW_NAMES[v] || v}</span>`).join("")}
            </span>
            <span class="tag-group">
              <span class="tag-label">周期</span>
              ${(s.horizon || []).map(h => `<span class="tag horizon-tag">${HORIZON_NAMES[h] || h}</span>`).join("")}
            </span>
            <span class="tag-group">
              <span class="tag-label">工具</span>
              ${(s.tool || []).map(t => `<span class="tag tool-tag">${TOOL_NAMES[t] || t}</span>`).join("")}
            </span>
          </div>
        </div>
        <div class="card-meta">
          <span class="metric complex">复杂度<span class="stars">${"★".repeat(s.complexity || 1)}</span></span>
          <span class="metric risk-${s.risk || 3}">风险<span class="stars">${"★".repeat(s.risk || 3)}</span></span>
        </div>
      </div>
      <div class="body">
        <div class="row">
          <div>
            <h4>什么时候用</h4><p>${s.when || ""}</p>
            <h4>怎么做</h4><p>${s.how || ""}</p>
          </div>
          <div>
            <h4>关键参数</h4>
            <table class="params-table">
              ${(s.params || []).map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("")}
            </table>
          </div>
        </div>
        <div class="row" style="margin-top:14px;">
          <div><h4>好处</h4><ul>${(s.pros || []).map(x => `<li>${x}</li>`).join("")}</ul></div>
          <div><h4>代价</h4><ul>${(s.cons || []).map(x => `<li>${x}</li>`).join("")}</ul></div>
        </div>
        ${s.example ? `<h4>示例</h4><div class="example-box">${s.example}</div>` : ""}
      </div>
    </div>
  `).join("");
  list.querySelectorAll(".strategy-card .header").forEach(h => {
    h.addEventListener("click", (ev) => {
      // Don't toggle when clicking the favorite star.
      if (ev.target.closest("[data-fav-strategy]")) return;
      h.parentElement.classList.toggle("expanded");
    });
  });
  list.querySelectorAll("[data-fav-strategy]").forEach(btn => {
    btn.addEventListener("click", async ev => {
      ev.stopPropagation();
      const sid = btn.dataset.favStrategy;
      const s = STRATEGIES.find(x => x.id === sid);
      await Favorites.toggle("strategy", sid, s ? { name: s.name, en: s.en, desc: s.desc } : {});
      const isFav = Favorites.isFavorited("strategy", sid);
      btn.classList.toggle("on", isFav);
      btn.textContent = isFav ? "★" : "☆";
    });
  });
}

// =========================================================================
// Decision form (provider/model dropdowns + start handler)
// =========================================================================
let serverConfig = null;
let providerById = {};

function showDecisionForm(show) {
  document.getElementById("decision-launch").style.display = show ? "none" : "block";
  document.getElementById("decision-form-wrap").style.display = show ? "block" : "none";
  if (show) {
    setTimeout(() => document.getElementById("ticker")?.focus(), 50);
  }
}

function initDecisionForm() {
  const form = document.getElementById("decision-form");
  if (!form) return;

  const dateInput = document.getElementById("trade-date");
  if (dateInput && !dateInput.value) {
    dateInput.value = new Date().toISOString().slice(0, 10);
  }

  document.querySelectorAll(".analyst-toggles input").forEach(box => {
    const lbl = box.parentElement;
    if (box.checked) lbl.classList.add("checked");
    box.addEventListener("change", () => lbl.classList.toggle("checked", box.checked));
  });

  // Deferred form: launcher button → expand form; close button → collapse
  document.getElementById("decision-launch-btn").addEventListener("click", e => {
    e.preventDefault();
    showDecisionForm(true);
  });
  document.getElementById("decision-form-close").addEventListener("click", e => {
    e.preventDefault();
    showDecisionForm(false);
  });

  document.getElementById("decision-submit").addEventListener("click", e => {
    e.preventDefault();
    const params = readForm();
    if (!params.ticker || !params.trade_date) {
      alert("请填写股票代码和交易日期");
      return;
    }
    WindowManager.create(params);
    // Auto-collapse the form after launch — feels lighter that way
    showDecisionForm(false);
  });

  document.getElementById("llm-provider").addEventListener("change", e => {
    populateModelDropdowns(e.target.value);
    updateProviderBadge(e.target.value);
  });

  ["deep-llm", "quick-llm"].forEach(id => {
    const sel = document.getElementById(id);
    const custom = document.getElementById(`${id}-custom`);
    sel.addEventListener("change", () => {
      custom.style.display = sel.value === CUSTOM_VALUE ? "block" : "none";
      if (sel.value === CUSTOM_VALUE) custom.focus();
    });
  });

  document.querySelectorAll(".example-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const params = JSON.parse(chip.dataset.params);
      Object.entries(params).forEach(([k, v]) => {
        const el = document.getElementById(k);
        if (el) {
          if (el.type === "checkbox") el.checked = !!v;
          else el.value = v;
        }
      });
    });
  });

  loadServerConfig();
}

async function loadServerConfig() {
  try {
    const apiBase = (window.APP_CONFIG && window.APP_CONFIG.API_BASE_URL) || "";
    const r = await fetch(`${apiBase}/api/config`);
    if (!r.ok) throw new Error(`config ${r.status}`);
    serverConfig = await r.json();
  } catch (err) {
    console.error("config load failed:", err);
    return;
  }
  providerById = {};
  serverConfig.providers.forEach(p => { providerById[p.id] = p; });
  const providerEl = document.getElementById("llm-provider");
  providerEl.innerHTML = serverConfig.providers.map(p => {
    const tag = p.key_present ? " · ✓ key" : " · ✗ no key";
    return `<option value="${p.id}">${p.label}${tag}</option>`;
  }).join("");
  const d = serverConfig.defaults || {};
  if (d.llm_provider) providerEl.value = d.llm_provider;
  populateModelDropdowns(providerEl.value, d.deep_think_llm, d.quick_think_llm);
  updateProviderBadge(providerEl.value);
  setIfPresent("ticker", d.ticker);
  setIfPresent("instrument", d.instrument_hint);
  setIfPresent("risk-tolerance", d.risk_tolerance ? String(d.risk_tolerance) : null);
  setIfPresent("depth", d.research_depth ? String(d.research_depth) : null);
  setIfPresent("language", d.output_language);
}

function setIfPresent(id, value) {
  if (!value) return;
  const el = document.getElementById(id);
  if (!el) return;
  if (el.tagName === "SELECT") {
    if (Array.from(el.options).some(o => o.value === value)) el.value = value;
  } else {
    el.value = value;
  }
}

function populateModelDropdowns(providerId, presetDeep, presetQuick) {
  const provider = providerById[providerId];
  if (!provider) return;
  const deepSel = document.getElementById("deep-llm");
  const quickSel = document.getElementById("quick-llm");
  const deepCustom = document.getElementById("deep-llm-custom");
  const quickCustom = document.getElementById("quick-llm-custom");
  const renderOpts = (models) => {
    const std = (models || []).map(m =>
      `<option value="${m.value}">${m.label}</option>`
    ).join("");
    return std + `<option value="${CUSTOM_VALUE}">— 自定义模型 ID …</option>`;
  };
  deepSel.innerHTML = renderOpts(provider.models?.deep);
  quickSel.innerHTML = renderOpts(provider.models?.quick);
  const applyPreset = (sel, custom, val) => {
    if (!val) return;
    if (Array.from(sel.options).some(o => o.value === val)) {
      sel.value = val;
      custom.style.display = "none";
    } else {
      sel.value = CUSTOM_VALUE;
      custom.value = val;
      custom.style.display = "block";
    }
  };
  applyPreset(deepSel, deepCustom, presetDeep);
  applyPreset(quickSel, quickCustom, presetQuick);
}

function updateProviderBadge(providerId) {
  const provider = providerById[providerId];
  const badge = document.getElementById("provider-key-badge");
  const hint = document.getElementById("provider-hint");
  if (!badge || !provider) return;
  if (provider.key_present) {
    badge.className = "pill live";
    badge.textContent = "API KEY ✓";
    if (hint) hint.textContent = `已检测到 ${provider.key_env} — 可使用 LIVE 模式。`;
  } else {
    badge.className = "pill demo";
    badge.textContent = "无 KEY";
    if (hint) hint.textContent = `未检测到 ${provider.key_env} — 选 LIVE 会失败，建议改用 DEMO 或在 .env 里配置。`;
  }
}

function readSelectOrCustom(id) {
  const sel = document.getElementById(id);
  const custom = document.getElementById(`${id}-custom`);
  if (!sel) return "";
  if (sel.value === CUSTOM_VALUE) {
    return (custom && custom.value.trim()) || "";
  }
  return sel.value.trim();
}

function readForm() {
  const analysts = ANALYST_KEYS.filter(k => document.getElementById(`an-${k}`).checked);
  return {
    ticker: document.getElementById("ticker").value.trim().toUpperCase(),
    trade_date: document.getElementById("trade-date").value,
    analysts: analysts.length ? analysts : ANALYST_KEYS,
    llm_provider: document.getElementById("llm-provider").value,
    deep_think_llm: readSelectOrCustom("deep-llm"),
    quick_think_llm: readSelectOrCustom("quick-llm"),
    research_depth: parseInt(document.getElementById("depth").value, 10) || 1,
    output_language: document.getElementById("language").value,
    risk_tolerance: parseInt(document.getElementById("risk-tolerance").value, 10) || 3,
    instrument_hint: document.getElementById("instrument").value,
    mode: document.getElementById("mode").value,
    parallel_analysts: !!document.getElementById("opt-parallel-analysts")?.checked,
    structured_reports: !!document.getElementById("opt-structured-reports")?.checked,
  };
}

// =========================================================================
// Cockpit DOM template (per-window, classes only)
// =========================================================================
function buildCockpitDOM() {
  const root = document.createElement("div");
  root.className = "cockpit";
  root.innerHTML = `
    <div class="cockpit-toolbar">
      <h3 class="cockpit-ticker"></h3>
      <div class="toolbar-actions">
        <span class="mode-pill pill"></span>
        <span class="translation-pill pill" title="翻译层状态"></span>
        <span class="status-text muted" style="font-size:12px;"></span>
        <button class="btn secondary download-md" disabled>⬇ Markdown</button>
        <button class="btn secondary download-json" disabled>⬇ JSON</button>
        <button class="btn secondary save-history" disabled>📌 保存到历史</button>
      </div>
    </div>

    <div class="cockpit-shell">
      <aside class="cockpit-sidebar">
        <div class="sidebar-section-title">导航</div>
        <ul class="sidebar-nav">
          <li data-section="progress" class="active">
            <span class="icon">📊</span><span class="label">智能体进度</span>
            <span class="badge" data-badge="progress">—</span>
          </li>
          <li data-section="logs">
            <span class="icon">📡</span><span class="label">事件流</span>
            <span class="badge" data-badge="logs">0</span>
          </li>
          <li data-section="past-context">
            <span class="icon">📝</span><span class="label">历史回顾</span>
            <span class="badge" data-badge="past-context">—</span>
          </li>
          <li class="sidebar-group">分析师报告</li>
          <li data-section="report-market_report">
            <span class="icon">📈</span><span class="label">市场技术</span>
            <span class="badge" data-badge="market_report">—</span>
          </li>
          <li data-section="report-sentiment_report">
            <span class="icon">💬</span><span class="label">情绪</span>
            <span class="badge" data-badge="sentiment_report">—</span>
          </li>
          <li data-section="report-news_report">
            <span class="icon">📰</span><span class="label">新闻</span>
            <span class="badge" data-badge="news_report">—</span>
          </li>
          <li data-section="report-fundamentals_report">
            <span class="icon">💼</span><span class="label">基本面</span>
            <span class="badge" data-badge="fundamentals_report">—</span>
          </li>
          <li class="sidebar-group">辩论与决策</li>
          <li data-section="debate">
            <span class="icon">🐂🐻</span><span class="label">投资辩论</span>
            <span class="badge" data-badge="debate">0</span>
          </li>
          <li data-section="report-investment_plan">
            <span class="icon">📋</span><span class="label">研究计划</span>
            <span class="badge" data-badge="investment_plan">—</span>
          </li>
          <li data-section="report-trader_investment_plan">
            <span class="icon">🧾</span><span class="label">交易提案</span>
            <span class="badge" data-badge="trader_investment_plan">—</span>
          </li>
          <li data-section="risk-debate">
            <span class="icon">⚖️</span><span class="label">风险辩论</span>
            <span class="badge" data-badge="risk-debate">0</span>
          </li>
          <li data-section="final">
            <span class="icon">🎯</span><span class="label">最终决策 + 策略</span>
            <span class="badge" data-badge="final">—</span>
          </li>
        </ul>
      </aside>

      <main class="cockpit-main">
        <section class="cockpit-section active" data-section="progress">
          <div class="panel"><div class="head">智能体执行进度</div>
            <div class="body agents-board"><div class="muted" style="font-size:12px;">等待启动…</div></div>
          </div>
        </section>
        <section class="cockpit-section" data-section="logs">
          <div class="panel"><div class="head">实时事件流</div>
            <div class="body" style="padding:10px;"><div class="log-stream"></div></div>
          </div>
        </section>
        <section class="cockpit-section" data-section="past-context">
          <div class="panel"><div class="head">📝 历史回顾 — 来自 TradingAgents 记忆库</div>
            <div class="body section-body past-context-body">
              <div class="muted">无历史数据 — 同标的第一次跑或 5 天内无回溯。</div>
            </div>
          </div>
        </section>
        ${[
          ["market_report", "市场技术分析报告"],
          ["sentiment_report", "情绪分析报告"],
          ["news_report", "新闻分析报告"],
          ["fundamentals_report", "基本面分析报告"],
          ["investment_plan", "研究经理 · 投资计划"],
          ["trader_investment_plan", "交易员 · 交易提案"],
        ].map(([k, t]) => `
          <section class="cockpit-section" data-section="report-${k}">
            <div class="panel"><div class="head">${t}</div>
              <div class="body section-body" data-section-key="${k}"><div class="muted">未生成。</div></div>
            </div>
          </section>
        `).join("")}
        <section class="cockpit-section" data-section="debate">
          <div class="panel"><div class="head">🐂 vs 🐻 投资观点辩论</div>
            <div class="body debate-area"></div>
          </div>
        </section>
        <section class="cockpit-section" data-section="risk-debate">
          <div class="panel"><div class="head">⚖️ 风险三方辩论</div>
            <div class="body risk-debate-area"></div>
          </div>
        </section>
        <section class="cockpit-section" data-section="final">
          <div class="panel"><div class="head">最终决策 + 策略库匹配</div>
            <div class="body final-card"><div class="muted">最终决策与策略推荐尚未就绪。</div></div>
          </div>
        </section>
      </main>
    </div>
  `;
  return root;
}

// =========================================================================
// DecisionWindow — one analysis run, isolated state + DOM
// =========================================================================
class DecisionWindow {
  constructor(params, opts = {}) {
    this.id = opts.id || uid();
    this.params = params;
    this.es = null;
    this.status = "idle";   // idle | running | done | error | restored
    this.startedAt = opts.startedAt || new Date().toISOString();
    this.completedAt = opts.completedAt || null;

    this.runState = opts.runState || {
      agents: {},
      events: [],
      reports: {},
      debate: { bull: [], bear: [] },
      riskDebate: { aggressive: [], neutral: [], conservative: [] },
      finalDecision: null,
      matchedStrategies: null,
      translation: null,
    };

    this.dom = buildCockpitDOM();
    this.dom.classList.add("window-instance");
    this.dom.dataset.windowId = this.id;
    this._wireDOM();
  }

  _wireDOM() {
    this.q = sel => this.dom.querySelector(sel);
    this.qa = sel => this.dom.querySelectorAll(sel);

    // sidebar nav
    this.qa(".sidebar-nav li[data-section]").forEach(li => {
      li.addEventListener("click", () => this.activateSection(li.dataset.section));
    });

    // toolbar buttons
    this.q(".download-md").addEventListener("click", () => this.download("md"));
    this.q(".download-json").addEventListener("click", () => this.download("json"));
    this.q(".save-history").addEventListener("click", async () => {
      await History.save(this);
      this.q(".save-history").textContent = "✓ 已保存";
      setTimeout(() => this.q(".save-history").textContent = "📌 保存到历史", 2000);
    });
  }

  activateSection(sectionId) {
    this.qa(".sidebar-nav li[data-section]").forEach(li => {
      li.classList.toggle("active", li.dataset.section === sectionId);
    });
    this.qa(".cockpit-section").forEach(s => {
      s.classList.toggle("active", s.dataset.section === sectionId);
    });
  }

  setBadge(key, value, state) {
    const el = this.q(`[data-badge="${key}"]`);
    if (!el) return;
    el.textContent = value;
    el.classList.remove("ready", "in-progress");
    if (state) el.classList.add(state);
  }

  setStatusText(s) { this.q(".status-text").textContent = s || ""; }

  setModePill(mode) {
    const pill = this.q(".mode-pill");
    pill.className = "mode-pill pill " + (mode || "");
    pill.textContent = mode === "live" ? "LIVE" : mode === "demo" ? "DEMO" : (mode || "").toUpperCase();
  }

  setTranslationPill(status) {
    const pill = this.q(".translation-pill");
    if (!status) { pill.className = "translation-pill pill"; pill.textContent = ""; return; }
    if (status.target?.toLowerCase() === "english") {
      pill.className = "translation-pill pill demo"; pill.textContent = "EN";
    } else if (status.available) {
      pill.className = "translation-pill pill live"; pill.textContent = `翻译 · ${status.provider}`;
    } else {
      pill.className = "translation-pill pill demo"; pill.textContent = "翻译未启用";
    }
  }

  // ---- start / stop / events ----------------------------------------

  /**
   * Read the signed-in user's API keys (LLM + data) from their Supabase
   * profile and merge into a single dict. Returns {} when not signed in
   * (single-tenant fallback uses backend .env keys).
   */
  /**
   * Bulk-insert the run's usage_events to the user's Supabase
   * `usage_events` table. RLS ensures each row attaches to auth.uid().
   * No-op when not signed in (data stays in localStorage via History).
   */
  async _flushUsageEvents() {
    const events = this.runState.usage_events || [];
    if (!events.length) return;
    if (!window.Auth?.isSignedIn() || !window.Auth.rawClient) return;
    const u = window.Auth.user();
    const rows = events.map(e => ({
      user_id: u.id,
      decision_id: this.id,
      ts: e.ts,
      kind: e.kind,
      provider: e.provider || null,
      model: e.model || null,
      tokens_in: e.tokens_in || 0,
      tokens_out: e.tokens_out || 0,
      tool_name: e.tool_name || null,
    }));
    const { error } = await window.Auth.rawClient().from("usage_events").insert(rows);
    if (error) console.warn("usage_events insert error:", error.message);
  }

  async _readUserKeys() {
    if (!window.Auth || !window.Auth.isSignedIn() || !window.Auth.rawClient) return {};
    try {
      const u = window.Auth.user();
      const { data, error } = await window.Auth.rawClient()
        .from("profiles")
        .select("llm_api_keys, custom_api_keys")
        .eq("id", u.id)
        .single();
      if (error) return {};
      return Object.assign({}, data?.llm_api_keys || {}, data?.custom_api_keys || {});
    } catch (e) {
      console.warn("readUserKeys", e);
      return {};
    }
  }

  async start() {
    this.status = "running";
    this.q(".cockpit-ticker").textContent = `${this.params.ticker} · ${this.params.trade_date}`;
    WindowManager.renderTabs();

    try {
      const headers = { "Content-Type": "application/json" };
      // Attach Supabase JWT when signed in — required if backend has
      // SUPABASE_JWT_SECRET set; harmless otherwise.
      const tok = window.Auth?.accessToken?.();
      if (tok) headers["Authorization"] = `Bearer ${tok}`;

      // Multi-tenant: pull this user's saved API keys from their Supabase
      // profile and attach them to the request body. The backend uses
      // KeyInjector to set them in env for the duration of graph
      // construction, then restores. Single-tenant deployments (no
      // signed-in user) skip this and the backend uses .env keys.
      const userKeys = await this._readUserKeys();

      const apiBase = (window.APP_CONFIG && window.APP_CONFIG.API_BASE_URL) || "";
      const r = await fetch(`${apiBase}/api/analyze`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          ...this.params,
          api_keys: userKeys,
          user_id: window.Auth?.user?.()?.id || null,
        }),
      });
      if (!r.ok) throw new Error(await r.text());
      const { session_id } = await r.json();
      this.es = new EventSource(`${apiBase}/api/stream/${session_id}`);
      this.es.onmessage = ev => {
        try { this.handleEvent(JSON.parse(ev.data)); } catch (e) { console.warn("bad event", e); }
      };
      this.es.onerror = () => {
        this.setStatusText("连接中断");
        this.markStatus("error");
        if (this.es) { this.es.close(); this.es = null; }
      };
    } catch (err) {
      this.setStatusText(`无法启动会话：${err.message}`);
      this.markStatus("error");
    }
  }

  stop() {
    if (this.es) { this.es.close(); this.es = null; }
    this.markStatus("done");
  }

  markStatus(s) {
    this.status = s;
    if (s === "done") this.completedAt = new Date().toISOString();
    WindowManager.renderTabs();
    if (s === "done" || s === "restored") {
      this.q(".download-md").disabled = false;
      this.q(".download-json").disabled = false;
      this.q(".save-history").disabled = false;
    }
  }

  handleEvent(evt) {
    this.runState.events.push(evt);
    switch (evt.type) {
      case "ready": this.setStatusText("会话已建立"); break;
      case "init":
        this.runState.translation = evt.translation;
        this.setTranslationPill(evt.translation);
        this.renderAgentBoard(evt.agents, evt.selected_analysts);
        break;
      case "mode": this.setModePill(evt.mode); break;
      case "agent_status": this.updateAgentStatus(evt.agent_id, evt.status); this.bumpProgressBadge(); break;
      case "log": this.appendLog(evt); break;
      case "tool_call":
        this.appendLog({ kind: "tool", content: `→ ${evt.name}(${this.formatArgs(evt.args)})`, ts: evt.ts });
        break;
      case "report": this.renderReport(evt); break;
      case "debate": this.renderDebate(evt); break;
      case "risk_debate": this.renderRiskDebate(evt); break;
      case "final_decision": this.renderFinal(evt); break;
      case "translation": this.applyTranslationPatch(evt); break;
      case "usage": this.runState.usage = evt.stats; break;
      case "usage_event":
        (this.runState.usage_events ||= []).push(evt);
        break;
      case "past_context":
        this.runState.past_context = evt.content;
        this.renderPastContext();
        break;
      case "structured_reports":
        // Optional opt-in (#10). Stored alongside markdown reports —
        // History.save() persists this in decisions.run_state for SQL queries.
        this.runState.structured_reports = evt.reports;
        break;
      case "complete":
        this.setStatusText("分析完成 ✔");
        this.markStatus("done");
        if (this.es) { this.es.close(); this.es = null; }
        // auto-save to history (Supabase if signed in, else localStorage)
        saveHistorySafely(this);
        // Persist granular usage_events to Supabase (RLS keeps per-user)
        this._flushUsageEvents().catch(e => console.warn("usage flush", e));
        break;
      case "error":
        this.setStatusText(`错误：${evt.message}`);
        this.markStatus("error");
        break;
    }
  }

  formatArgs(args) {
    if (!args) return "";
    try {
      const s = typeof args === "string" ? args : JSON.stringify(args);
      return s.length > 90 ? s.slice(0, 90) + "…" : s;
    } catch { return String(args).slice(0, 90); }
  }

  // ---- render: agents / log / reports / debate / final ---------------

  renderAgentBoard(agents, selected) {
    this.runState.agents = {};
    agents.forEach(a => { this.runState.agents[a.id] = { ...a, status: "pending" }; });
    if (selected && selected.length) this.runState.agents[selected[0]].status = "in_progress";
    this.drawAgentBoard();
  }

  drawAgentBoard() {
    const teams = {};
    Object.values(this.runState.agents).forEach(a => { (teams[a.team] ||= []).push(a); });
    const board = this.q(".agents-board");
    const statusZh = s => ({ pending: "等待", in_progress: "进行中", completed: "完成" }[s] || s);
    board.innerHTML = Object.entries(teams).map(([team, members]) => `
      <div class="team-block">
        <div class="team-label">${TEAM_ZH[team] || team}</div>
        ${members.map(a => `
          <div class="agent-row ${a.status}" data-agent="${a.id}">
            <span class="dot"></span>
            <span class="name">${AGENT_DISPLAY_ZH[a.name] || a.name}</span>
            <span class="badge">${statusZh(a.status)}</span>
          </div>
        `).join("")}
      </div>
    `).join("");
  }

  updateAgentStatus(id, status) {
    if (!this.runState.agents[id]) return;
    this.runState.agents[id].status = status;
    const row = this.q(`.agent-row[data-agent="${id}"]`);
    if (!row) return;
    const statusZh = s => ({ pending: "等待", in_progress: "进行中", completed: "完成" }[s] || s);
    row.className = `agent-row ${status}`;
    row.querySelector(".badge").textContent = statusZh(status);
  }

  bumpProgressBadge() {
    const total = Object.keys(this.runState.agents).length;
    if (!total) return this.setBadge("progress", "—");
    const done = Object.values(this.runState.agents).filter(a => a.status === "completed").length;
    const inProgress = Object.values(this.runState.agents).some(a => a.status === "in_progress");
    this.setBadge("progress", `${done}/${total}`, inProgress ? "in-progress" : (done === total ? "ready" : ""));
  }

  appendLog(evt) {
    const stream = this.q(".log-stream");
    const line = document.createElement("div");
    line.className = "line";
    line.innerHTML = `
      <span class="ts">${evt.ts || ""}</span>
      <span class="kind ${evt.kind || "system"}">${(evt.kind || "system").toUpperCase()}</span>
      <span class="content">${escapeHtml(evt.content || "")}</span>
    `;
    stream.appendChild(line);
    stream.scrollTop = stream.scrollHeight;
    this.setBadge("logs", String(stream.querySelectorAll(".line").length));
  }

  /**
   * Render the past_context (TradingAgents memory log) into the cockpit's
   * "📝 历史回顾" section. Called when a `past_context` SSE event arrives.
   */
  renderPastContext() {
    const ctx = this.runState.past_context;
    const body = this.q(".past-context-body");
    if (!body) return;
    if (!ctx || !ctx.trim()) {
      body.innerHTML = `<div class="muted">无历史数据 — 同标的第一次跑或 5 天内无回溯。</div>`;
      this.setBadge("past-context", "—");
      return;
    }
    body.innerHTML = mdLite(ctx);
    // count entries roughly by counting "[YYYY-MM-DD" headers
    const matches = (ctx.match(/\[\d{4}-\d{2}-\d{2}/g) || []).length;
    this.setBadge("past-context", String(matches), "ready");
  }

  renderReport(evt) {
    const body = this.q(`.section-body[data-section-key="${evt.section}"]`);
    if (!body) return;
    body.dataset.msgId = evt.msg_id || "";
    body.innerHTML = mdLite(evt.content || "");
    if (this.runState.translation?.available && !isMostlyChinese(evt.content || "")) {
      const hint = document.createElement("div");
      hint.className = "pending-translation";
      hint.textContent = "🔄 中文翻译生成中…";
      body.prepend(hint);
    }
    this.runState.reports[evt.section] = {
      title: evt.title, msg_id: evt.msg_id,
      content_en: evt.content, content_zh: null,
      section: evt.section,
    };
    this.setBadge(evt.section, "✓", "ready");
  }

  renderDebate(evt) {
    const wrap = this.q(".debate-area");
    if (!wrap.dataset.init) {
      wrap.innerHTML = `
        <div class="debate-grid">
          <div class="debate-side bull"><div class="head">🐂 牛市研究员</div><div class="turns" data-side="bull"></div></div>
          <div class="debate-side bear"><div class="head">🐻 熊市研究员</div><div class="turns" data-side="bear"></div></div>
        </div>
      `;
      wrap.dataset.init = "1";
    }
    const target = wrap.querySelector(`.turns[data-side="${evt.side}"]`);
    if (!target) return;
    const turn = document.createElement("div");
    turn.className = "turn";
    turn.dataset.msgId = evt.msg_id || "";
    turn.dataset.ts = evt.ts || "";
    turn.innerHTML = `<div class="muted" style="font-size:11px;">${evt.ts || ""}</div>${mdLite(evt.content || "")}`;
    target.appendChild(turn);
    target.scrollTop = target.scrollHeight;
    this.runState.debate[evt.side].push({
      ts: evt.ts, msg_id: evt.msg_id,
      content_en: evt.content, content_zh: null,
    });
    this.setBadge("debate", String(this.runState.debate.bull.length + this.runState.debate.bear.length));
  }

  renderRiskDebate(evt) {
    const wrap = this.q(".risk-debate-area");
    if (!wrap.dataset.init) {
      wrap.innerHTML = `
        <div class="risk-grid">
          <div class="debate-side aggressive"><div class="head">🔥 激进</div><div class="turns" data-side="aggressive"></div></div>
          <div class="debate-side neutral"><div class="head">⚖️ 中立</div><div class="turns" data-side="neutral"></div></div>
          <div class="debate-side conservative"><div class="head">🛡️ 保守</div><div class="turns" data-side="conservative"></div></div>
        </div>
      `;
      wrap.dataset.init = "1";
    }
    const target = wrap.querySelector(`.turns[data-side="${evt.side}"]`);
    if (!target) return;
    const turn = document.createElement("div");
    turn.className = "turn";
    turn.dataset.msgId = evt.msg_id || "";
    turn.dataset.ts = evt.ts || "";
    turn.innerHTML = `<div class="muted" style="font-size:11px;">${evt.ts || ""}</div>${mdLite(evt.content || "")}`;
    target.appendChild(turn);
    target.scrollTop = target.scrollHeight;
    this.runState.riskDebate[evt.side].push({
      ts: evt.ts, msg_id: evt.msg_id,
      content_en: evt.content, content_zh: null,
    });
    const total = this.runState.riskDebate.aggressive.length + this.runState.riskDebate.neutral.length + this.runState.riskDebate.conservative.length;
    this.setBadge("risk-debate", String(total));
  }

  renderFinal(evt) {
    const dec = evt.decision || {};
    const matched = evt.matched_strategies || { items: [], parsed: {} };
    this.runState.finalDecision = {
      rating: dec.rating, confidence: dec.confidence, msg_id: evt.msg_id,
      raw_en: dec.raw, raw_zh: null,
      trader_plan_en: dec.trader_plan, trader_plan_zh: null,
      research_plan_en: dec.research_plan, research_plan_zh: null,
      parsed: matched.parsed,
    };
    this.runState.matchedStrategies = matched.items || [];
    this.rerenderFinalCard();
    this.setBadge("final", dec.rating || "✓", "ready");
    WindowManager.renderTabs();  // tab label often wants to show rating
  }

  rerenderFinalCard() {
    if (!this.runState.finalDecision) return;
    const dec = this.runState.finalDecision;
    const matched = this.runState.matchedStrategies || [];
    const parsed = dec.parsed || {};
    const card = this.q(".final-card");
    const tags = [
      parsed.view && `<span class="tag view-tag">${VIEW_NAMES[parsed.view] || parsed.view}</span>`,
      parsed.horizon && `<span class="tag horizon-tag">${HORIZON_NAMES[parsed.horizon] || parsed.horizon}</span>`,
      parsed.volatility && `<span class="tag">${VIEW_NAMES[parsed.volatility] || parsed.volatility}</span>`,
    ].filter(Boolean).join("");

    const matchHtml = matched.map((m, i) => `
      <div class="match-card">
        <div class="rank">${i + 1}</div>
        <div class="info">
          <div>
            <span class="title">${m.name}</span>
            <span class="en">${m.en || ""}</span>
            <span class="tag cat-${m.cat}" style="margin-left:6px;">${CAT_NAMES[m.cat] || m.cat}</span>
          </div>
          <div class="desc">${m.desc || ""}</div>
          <div class="reasons">${(m.reasons || []).map(r => `<span class="reason">${r}</span>`).join("")}</div>
          <details>
            <summary>展开操作细节</summary>
            <p><strong>怎么做：</strong>${m.how || ""}</p>
            <table class="params-table">${(m.params || []).map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("")}</table>
            ${m.pros ? `<p><strong>好处：</strong></p><ul>${m.pros.map(x => `<li>${x}</li>`).join("")}</ul>` : ""}
            ${m.cons ? `<p><strong>代价：</strong></p><ul>${m.cons.map(x => `<li>${x}</li>`).join("")}</ul>` : ""}
            ${m.example ? `<p><strong>示例：</strong>${m.example}</p>` : ""}
          </details>
        </div>
        <div class="score"><span class="num">${m.score}</span><span>匹配分</span></div>
      </div>
    `).join("") || `<div class="muted">未找到匹配策略 — 可能是观点信号过弱。</div>`;

    const raw = dec.raw_zh || dec.raw_en || "";
    const transHint = (!dec.raw_zh && dec.raw_en && !isMostlyChinese(dec.raw_en) && this.runState.translation?.available)
      ? `<div class="pending-translation">🔄 中文翻译生成中…</div>` : "";

    card.innerHTML = `
      <div class="decision-card">
        <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
          <span class="decision-rating ${dec.rating || "Hold"}">${dec.rating || "Hold"}</span>
          ${dec.confidence ? `<span class="muted">信心：${dec.confidence}</span>` : ""}
        </div>
        <div class="parsed-tags">${tags}</div>
        ${transHint}
        <div style="margin-top:14px;">${mdLite(raw)}</div>
      </div>
      <h3>📚 来自策略库的匹配方案（按匹配度排序）</h3>
      <div class="match-list">${matchHtml}</div>
    `;
  }

  applyTranslationPatch(evt) {
    const { msg_id, target, content } = evt;
    if (!msg_id || !content) return;
    const reportBody = this.q(`.section-body[data-msg-id="${msg_id}"]`);
    if (reportBody) {
      reportBody.innerHTML = mdLite(content);
      const key = reportBody.dataset.sectionKey;
      if (key && this.runState.reports[key]) this.runState.reports[key].content_zh = content;
      return;
    }
    const turn = this.dom.querySelector(`.turn[data-msg-id="${msg_id}"]`);
    if (turn) {
      const ts = turn.dataset.ts || "";
      turn.innerHTML = `<div class="muted" style="font-size:11px;">${ts}</div>${mdLite(content)}`;
      ["bull", "bear"].forEach(side => {
        const f = this.runState.debate[side].find(t => t.msg_id === msg_id);
        if (f) f.content_zh = content;
      });
      ["aggressive", "neutral", "conservative"].forEach(side => {
        const f = this.runState.riskDebate[side].find(t => t.msg_id === msg_id);
        if (f) f.content_zh = content;
      });
      return;
    }
    if (target?.startsWith("decision.") && this.runState.finalDecision) {
      const field = target.split(".")[1];
      this.runState.finalDecision[`${field}_zh`] = content;
      this.rerenderFinalCard();
    }
  }

  // ---- restore from history (replay state without SSE) -----------------

  static fromHistory(entry) {
    const w = new DecisionWindow(entry.params, {
      id: entry.id,
      runState: entry.runState,
      startedAt: entry.startedAt,
      completedAt: entry.completedAt,
    });
    w.status = "restored";
    // Replay state into the DOM
    w.q(".cockpit-ticker").textContent = `${entry.params.ticker} · ${entry.params.trade_date}`;
    w.setModePill("restored");
    w.q(".mode-pill").textContent = "RESTORED";
    w.setTranslationPill(entry.runState.translation);

    // agent board
    const agentArr = Object.values(entry.runState.agents || {});
    if (agentArr.length) {
      w.runState.agents = entry.runState.agents;
      w.drawAgentBoard();
      w.bumpProgressBadge();
    }

    // logs
    (entry.runState.events || []).forEach(e => {
      if (e.type === "log") w.appendLog(e);
      if (e.type === "tool_call") w.appendLog({ kind: "tool", content: `→ ${e.name}(${w.formatArgs(e.args)})`, ts: e.ts });
    });

    // reports
    Object.entries(entry.runState.reports || {}).forEach(([k, r]) => {
      const body = w.q(`.section-body[data-section-key="${k}"]`);
      if (!body) return;
      body.innerHTML = mdLite(r.content_zh || r.content_en || "");
      w.setBadge(k, "✓", "ready");
    });

    // debates
    ["bull", "bear"].forEach(side => {
      (entry.runState.debate?.[side] || []).forEach(t => {
        w.renderDebate({ side, content: t.content_zh || t.content_en, ts: t.ts, msg_id: t.msg_id });
      });
    });
    ["aggressive", "neutral", "conservative"].forEach(side => {
      (entry.runState.riskDebate?.[side] || []).forEach(t => {
        w.renderRiskDebate({ side, content: t.content_zh || t.content_en, ts: t.ts, msg_id: t.msg_id });
      });
    });

    // final
    if (entry.runState.finalDecision) {
      w.runState.finalDecision = entry.runState.finalDecision;
      w.runState.matchedStrategies = entry.runState.matchedStrategies;
      w.rerenderFinalCard();
      w.setBadge("final", entry.runState.finalDecision.rating || "✓", "ready");
    }

    // enable downloads / save
    w.q(".download-md").disabled = false;
    w.q(".download-json").disabled = false;
    w.q(".save-history").disabled = true;  // already in history
    w.q(".save-history").textContent = "已在历史";
    w.setStatusText(`回看：${new Date(entry.completedAt || entry.startedAt).toLocaleString()}`);
    return w;
  }

  // ---- download ------------------------------------------------------

  download(format) {
    const ticker = this.params.ticker;
    const date = this.params.trade_date;
    let blob, filename;
    if (format === "json") {
      const payload = {
        meta: {
          generated_at: new Date().toISOString(),
          window_id: this.id, ticker, trade_date: date,
          status: this.status, started_at: this.startedAt, completed_at: this.completedAt,
          params: this.params, translation: this.runState.translation,
        },
        reports: this.runState.reports,
        debate: this.runState.debate,
        risk_debate: this.runState.riskDebate,
        final_decision: this.runState.finalDecision,
        matched_strategies: this.runState.matchedStrategies,
        events: this.runState.events,
      };
      blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
      filename = `decision_${ticker}_${date}.json`;
    } else {
      blob = new Blob([this.buildMarkdownReport()], { type: "text/markdown;charset=utf-8" });
      filename = `decision_${ticker}_${date}.md`;
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 0);
  }

  buildMarkdownReport() {
    const p = this.params || {};
    const dec = this.runState.finalDecision || {};
    const parsed = dec.parsed || {};
    const usage = this.runState.usage || {};

    // ---- TOC + section visibility scan ---------------------------------
    // Determine which sections actually have content. The TOC is generated
    // dynamically so empty sections don't appear as broken anchors.
    const has = {
      decision: Boolean(dec.rating || dec.raw_zh || dec.raw_en),
      strategies: (this.runState.matchedStrategies || []).length > 0,
      reports: ["market_report","sentiment_report","news_report","fundamentals_report"]
                  .some(k => this.runState.reports[k]),
      debate: (this.runState.debate.bull.length + this.runState.debate.bear.length) > 0,
      risk: (this.runState.riskDebate.aggressive.length
             + this.runState.riskDebate.neutral.length
             + this.runState.riskDebate.conservative.length) > 0,
      research_plan: Boolean(this.runState.reports["investment_plan"]),
      trader_plan: Boolean(this.runState.reports["trader_investment_plan"]),
      usage: usage && (usage.tokens_in || usage.tokens_out || usage.llm_calls),
    };

    // Big rating badge in the header. Markdown viewers render bold + emoji
    // — and Markdown→HTML pipelines (gh, GitLab) keep the colour intent.
    const ratingEmoji = {
      Buy: "🟢", Overweight: "🟢",
      Hold: "⚪",
      Sell: "🔴", Underweight: "🔴",
    }[dec.rating] || "⚪";
    const ratingBadge = dec.rating
      ? `**${ratingEmoji} ${dec.rating}${dec.confidence ? `** · 信心 ${dec.confidence}` : "**"}`
      : "**⚪ 未生成**";

    const lines = [];

    // ---- HEADER ---------------------------------------------------------
    lines.push(`# 📊 智能交易决策报告 — ${p.ticker || ""}`);
    lines.push("");
    lines.push(`> ${ratingBadge}`);
    lines.push("");

    // metadata table for cleaner rendering
    lines.push("| 字段 | 值 |");
    lines.push("|---|---|");
    lines.push(`| 分析日期 | ${p.trade_date || "—"} |`);
    lines.push(`| 运行时间 | ${this.startedAt || "—"} → ${this.completedAt || "(进行中)"} |`);
    lines.push(`| LLM 提供商 | \`${p.llm_provider || "—"}\` |`);
    lines.push(`| 深思模型 | \`${p.deep_think_llm || "—"}\` |`);
    lines.push(`| 轻思模型 | \`${p.quick_think_llm || "—"}\` |`);
    lines.push(`| 研究深度 | ${p.research_depth || 1} 轮 |`);
    if (this.runState.translation) {
      const t = this.runState.translation;
      lines.push(`| 翻译层 | ${t.available ? `\`${t.provider}/${t.model}\`` : "未启用"} |`);
    }
    if (has.usage) {
      lines.push(`| Token 用量 | input ${usage.tokens_in || 0} · output ${usage.tokens_out || 0} · ${usage.llm_calls || 0} 次 LLM 调用 |`);
    }
    lines.push("");

    // ---- TABLE OF CONTENTS ---------------------------------------------
    lines.push("## 📑 目录");
    lines.push("");
    if (has.decision)      lines.push("- [🎯 最终决策](#最终决策)");
    if (has.strategies)    lines.push(`- [📚 策略库匹配 (${this.runState.matchedStrategies.length})](#策略库匹配)`);
    if (has.reports) {
      lines.push("- [📝 分析师报告](#分析师报告)");
      ["market_report","sentiment_report","news_report","fundamentals_report"].forEach(k => {
        if (!this.runState.reports[k]) return;
        const slug = k.replace(/_/g, "-");
        lines.push(`  - [${REPORT_TITLE_ZH[k] || k}](#${slug})`);
      });
    }
    if (has.debate)        lines.push("- [🐂 vs 🐻 投资观点辩论](#投资观点辩论)");
    if (has.risk)          lines.push("- [⚖️ 风险三方辩论](#风险三方辩论)");
    if (has.research_plan) lines.push("- [📋 研究经理 · 投资计划](#研究经理-投资计划)");
    if (has.trader_plan)   lines.push("- [🧾 交易员 · 交易提案](#交易员-交易提案)");
    lines.push("");
    lines.push("---");
    lines.push("");

    // ---- DECISION (anchor: 最终决策) -----------------------------------
    if (has.decision) {
      lines.push("## 🎯 最终决策");
      lines.push("");
      lines.push(`> ${ratingBadge}`);
      lines.push("");
      // Signal tags row
      const tags = [];
      if (parsed.view)       tags.push(`观点: \`${parsed.view}\``);
      if (parsed.horizon)    tags.push(`周期: \`${parsed.horizon}\``);
      if (parsed.volatility) tags.push(`波动: \`${parsed.volatility}\``);
      if (tags.length)       lines.push("**信号**: " + tags.join(" · "));
      lines.push("");
      lines.push(dec.raw_zh || dec.raw_en || "_(未生成)_");
      lines.push("");
    }

    // ---- STRATEGY MATCHES (anchor: 策略库匹配) -------------------------
    if (has.strategies) {
      lines.push("## 📚 策略库匹配");
      lines.push("");
      // Compact summary table first
      lines.push("| # | 策略 | 类别 | 匹配分 |");
      lines.push("|---|---|---|---|");
      (this.runState.matchedStrategies || []).forEach((m, i) => {
        const cat = (typeof CAT_NAMES !== "undefined" && CAT_NAMES[m.cat]) || m.cat;
        lines.push(`| ${i + 1} | **${m.name}** _(${m.en || ""})_ | ${cat} | ${m.score} |`);
      });
      lines.push("");
      // Detailed cards
      (this.runState.matchedStrategies || []).forEach((m, i) => {
        lines.push(`### ${i + 1}. ${m.name} _(${m.en || ""})_`);
        lines.push("");
        lines.push(`- **类别**: ${(typeof CAT_NAMES !== "undefined" && CAT_NAMES[m.cat]) || m.cat}`);
        lines.push(`- **匹配分**: ${m.score}`);
        lines.push(`- **描述**: ${m.desc || ""}`);
        lines.push(`- **怎么做**: ${m.how || ""}`);
        if (m.params?.length) lines.push(`- **关键参数**: ${m.params.map(([k, v]) => `${k}=${v}`).join("; ")}`);
        lines.push(`- **匹配原因**: ${(m.reasons || []).join("； ")}`);
        if (m.example) lines.push(`- **示例**: ${m.example}`);
        lines.push("");
      });
    }

    // ---- ANALYST REPORTS (anchor: 分析师报告) --------------------------
    if (has.reports) {
      lines.push("## 📝 分析师报告");
      lines.push("");
      ["market_report", "sentiment_report", "news_report", "fundamentals_report"].forEach(k => {
        const r = this.runState.reports[k];
        if (!r) return;
        lines.push(`### ${REPORT_TITLE_ZH[k] || k}`);
        lines.push("");
        lines.push(r.content_zh || r.content_en || "_(未生成)_");
        lines.push("");
      });
    }

    // ---- DEBATE (anchor: 投资观点辩论) ---------------------------------
    if (has.debate) {
      lines.push("## 🐂 vs 🐻 投资观点辩论");
      lines.push("");
      ["bull", "bear"].forEach(side => {
        const arr = this.runState.debate[side];
        if (!arr.length) return;
        lines.push(`### ${side === "bull" ? "🐂 牛市研究员" : "🐻 熊市研究员"}`);
        lines.push("");
        arr.forEach((t, i) => {
          lines.push(`**回合 ${i + 1}** _(${t.ts || ""})_`);
          lines.push("");
          lines.push(t.content_zh || t.content_en || "");
          lines.push("");
        });
      });
    }

    // ---- RISK DEBATE (anchor: 风险三方辩论) ----------------------------
    if (has.risk) {
      lines.push("## ⚖️ 风险三方辩论");
      lines.push("");
      ["aggressive", "neutral", "conservative"].forEach(side => {
        const arr = this.runState.riskDebate[side];
        if (!arr.length) return;
        const label = { aggressive: "🔥 激进", neutral: "⚖️ 中立", conservative: "🛡️ 保守" }[side];
        lines.push(`### ${label}`);
        lines.push("");
        arr.forEach((t, i) => {
          lines.push(`**回合 ${i + 1}** _(${t.ts || ""})_`);
          lines.push("");
          lines.push(t.content_zh || t.content_en || "");
          lines.push("");
        });
      });
    }

    // ---- RESEARCH PLAN -------------------------------------------------
    if (has.research_plan) {
      lines.push("## 📋 研究经理 · 投资计划");
      lines.push("");
      const r = this.runState.reports["investment_plan"];
      lines.push(r.content_zh || r.content_en || "");
      lines.push("");
    }

    // ---- TRADER PLAN ---------------------------------------------------
    if (has.trader_plan) {
      lines.push("## 🧾 交易员 · 交易提案");
      lines.push("");
      const r = this.runState.reports["trader_investment_plan"];
      lines.push(r.content_zh || r.content_en || "");
      lines.push("");
    }

    // ---- FOOTER --------------------------------------------------------
    lines.push("---");
    lines.push("");
    lines.push("_本报告由 **TradingForge · 智策** 自动生成。教育目的，不构成投资建议。_");
    return lines.join("\n");
  }
}

// =========================================================================
// WindowManager — multiple concurrent DecisionWindows
// =========================================================================
const WindowManager = {
  windows: new Map(),
  activeId: null,

  init() {
    this.tabsEl = document.getElementById("window-tabs");
    this.containerEl = document.getElementById("windows-container");
  },

  create(params) {
    const w = new DecisionWindow(params);
    this.windows.set(w.id, w);
    this.containerEl.appendChild(w.dom);
    this.activate(w.id);
    w.start();
    this.renderTabs();
    return w;
  },

  openHistorical(entry) {
    // If a window already open with this history id, just activate
    if (this.windows.has(entry.id)) { this.activate(entry.id); return; }
    const w = DecisionWindow.fromHistory(entry);
    this.windows.set(w.id, w);
    this.containerEl.appendChild(w.dom);
    this.activate(w.id);
    this.renderTabs();
    return w;
  },

  activate(id) {
    this.activeId = id;
    this.windows.forEach((w, wid) => {
      w.dom.classList.toggle("active", wid === id);
    });
    this.renderTabs();
  },

  close(id) {
    const w = this.windows.get(id);
    if (!w) return;
    if (w.es) w.es.close();
    w.dom.remove();
    this.windows.delete(id);
    if (this.activeId === id) {
      const next = this.windows.keys().next().value;
      if (next) this.activate(next);
      else { this.activeId = null; this.renderTabs(); }
    } else {
      this.renderTabs();
    }
  },

  renderTabs() {
    if (!this.tabsEl) return;
    if (this.windows.size === 0) {
      this.tabsEl.innerHTML = `<span class="muted" style="font-size:12px; padding:4px 8px;">尚未启动任何决策窗口</span>`;
      return;
    }
    const tabs = [];
    this.windows.forEach((w, wid) => {
      const isActive = wid === this.activeId;
      const rating = w.runState.finalDecision?.rating;
      const labelTxt = `${w.params.ticker} · ${w.params.trade_date}`;
      tabs.push(`
        <div class="window-tab ${isActive ? "active" : ""} ${w.status}" data-window-id="${wid}">
          <span class="status-dot"></span>
          <span class="label">${labelTxt}${rating ? " · " + rating : ""}</span>
          <span class="close" data-close="${wid}" title="关闭">×</span>
        </div>
      `);
    });
    this.tabsEl.innerHTML = tabs.join("");
    this.tabsEl.querySelectorAll(".window-tab").forEach(el => {
      el.addEventListener("click", e => {
        if (e.target.dataset.close) {
          this.close(e.target.dataset.close);
        } else {
          this.activate(el.dataset.windowId);
        }
      });
    });
  },
};

// =========================================================================
// History — Supabase when signed in, localStorage fallback otherwise
// =========================================================================
const History = {
  LOCAL_KEY: "tda:history",
  LOCAL_MAX: 200,                   // bumped from 50 — pin/rate makes more entries valuable
  cache: [],

  // UI state
  sort: "time-desc",
  filterDirection: "all",
  filterInstrument: "all",
  filterStars: "all",
  search: "",

  async init() {
    this.listEl = document.getElementById("history-list");
    this.emptyEl = document.getElementById("history-empty");
    this.controlsEl = document.getElementById("history-controls");

    document.getElementById("history-clear").addEventListener("click", async () => {
      if (!confirm("确定要清空所有历史决策？此操作无法撤销。")) return;
      if (this._useRemote()) {
        await window.Decisions.deleteAll();
      } else {
        localStorage.removeItem(this.LOCAL_KEY);
      }
      await this.refresh();
    });
    document.getElementById("history-toggle-filter").addEventListener("click", () => {
      const open = this.controlsEl.style.display !== "none";
      this.controlsEl.style.display = open ? "none" : "block";
    });

    document.getElementById("history-sort").addEventListener("change", e => {
      this.sort = e.target.value; this.render();
    });
    document.getElementById("history-filter-rating").addEventListener("change", e => {
      this.filterDirection = e.target.value; this.render();
    });
    document.getElementById("history-filter-instrument").addEventListener("change", e => {
      this.filterInstrument = e.target.value; this.render();
    });
    document.getElementById("history-filter-stars").addEventListener("change", e => {
      this.filterStars = e.target.value; this.render();
    });
    document.getElementById("history-search").addEventListener("input", e => {
      this.search = e.target.value.trim().toLowerCase(); this.render();
    });

    if (window.Auth) window.Auth.onChange(() => this.refresh());
    await this.refresh();
  },

  // ---- helpers ----------------------------------------------------------

  _direction(rating) {
    if (!rating) return "hold";
    const r = String(rating).toLowerCase();
    if (r === "buy" || r === "overweight") return "bull";
    if (r === "sell" || r === "underweight") return "bear";
    return "hold";
  },

  _instrument(entry) {
    const t = (entry.ticker || "").toUpperCase();
    if (entry.params?.instrument_hint) return entry.params.instrument_hint;
    if (t.endsWith("-USD") || t.endsWith("USDT") || t.startsWith("BTC") || t.startsWith("ETH")) return "crypto";
    if (/^(SPY|QQQ|DIA|IWM|VTI|VOO|XL[A-Z]|GLD|SLV|TLT|IEF|BND|AGG|HYG|EEM|VEA|VWO)$/.test(t)) return "etf";
    if (/^(GC|SI|CL|NG|HG|ZC|ZW)/.test(t)) return "commodity";
    if (/^[A-Z]{6}=X$|^USD|^EUR|^GBP|^JPY|^CNY/.test(t)) return "forex";
    return "stock";
  },

  _useRemote() {
    return Boolean(window.Decisions && window.Auth && window.Auth.isSignedIn());
  },

  async refresh() {
    if (this._useRemote()) {
      const rows = await window.Decisions.list();
      this.cache = rows.map(r => ({
        id: r.id, ticker: r.ticker, trade_date: r.trade_date,
        rating: r.rating, status: r.status,
        startedAt: r.started_at, completedAt: r.completed_at,
        pinned: !!r.pinned,
        user_rating: r.user_rating || 0,
        user_note: r.user_note || "",
        params: { instrument_hint: r.instrument_hint },
        _remote: true,
      }));
    } else {
      this.cache = this._readLocal();
    }
    this.render();
  },

  async setPinned(id, pinned) {
    if (this._useRemote()) {
      await window.Auth.rawClient().from("decisions")
        .update({ pinned }).eq("id", id);
    } else {
      const all = this._readLocal();
      const e = all.find(x => x.id === id);
      if (e) { e.pinned = pinned; localStorage.setItem(this.LOCAL_KEY, JSON.stringify(all)); }
    }
    await this.refresh();
  },

  async setRating(id, rating) {
    if (this._useRemote()) {
      await window.Auth.rawClient().from("decisions")
        .update({ user_rating: rating }).eq("id", id);
    } else {
      const all = this._readLocal();
      const e = all.find(x => x.id === id);
      if (e) { e.user_rating = rating; localStorage.setItem(this.LOCAL_KEY, JSON.stringify(all)); }
    }
    await this.refresh();
  },

  _readLocal() {
    try { return JSON.parse(localStorage.getItem(this.LOCAL_KEY) || "[]"); }
    catch { return []; }
  },

  /**
   * Returns the full entry (with runState) by id. Local entries already have
   * everything; remote ones lazy-fetch run_state from Supabase.
   */
  async getEntry(id) {
    const stub = this.cache.find(e => e.id === id);
    if (!stub) return null;
    if (!stub._remote) return stub;  // local has full payload
    const row = await window.Decisions.get(id);
    if (!row) return null;
    return {
      id: row.id, ticker: row.ticker, trade_date: row.trade_date,
      rating: row.rating, status: row.status,
      startedAt: row.started_at, completedAt: row.completed_at,
      params: row.params, runState: row.run_state,
    };
  },

  async save(window_) {
    // Preserve any pin/rating already attached to an existing entry
    const existing = this.cache.find(e => e.id === window_.id) || {};
    const entry = {
      id: window_.id,
      ticker: window_.params.ticker,
      trade_date: window_.params.trade_date,
      rating: window_.runState.finalDecision?.rating || null,
      status: window_.status,
      startedAt: window_.startedAt,
      completedAt: window_.completedAt || new Date().toISOString(),
      pinned: existing.pinned || false,
      user_rating: existing.user_rating || 0,
      user_note: existing.user_note || "",
      params: window_.params,
      runState: window_.runState,
    };
    if (this._useRemote()) {
      await window.Decisions.upsert(entry);
    } else {
      const all = this._readLocal();
      const idx = all.findIndex(e => e.id === entry.id);
      if (idx >= 0) all[idx] = entry; else all.unshift(entry);
      const trimmed = all.slice(0, this.LOCAL_MAX);
      try { localStorage.setItem(this.LOCAL_KEY, JSON.stringify(trimmed)); }
      catch (e) {
        console.warn("history quota — pruning");
        try { localStorage.setItem(this.LOCAL_KEY, JSON.stringify(trimmed.slice(0, Math.floor(this.LOCAL_MAX / 2)))); }
        catch (e2) { console.error("history save failed:", e2); }
      }
    }
    await this.refresh();
  },

  async delete(id) {
    if (this._useRemote()) {
      await window.Decisions.delete(id);
    } else {
      const all = this._readLocal().filter(e => e.id !== id);
      localStorage.setItem(this.LOCAL_KEY, JSON.stringify(all));
    }
    await this.refresh();
  },

  _filteredSorted() {
    let items = [...this.cache];

    // filters
    if (this.filterDirection !== "all") {
      items = items.filter(e => this._direction(e.rating) === this.filterDirection);
    }
    if (this.filterInstrument !== "all") {
      items = items.filter(e => this._instrument(e) === this.filterInstrument);
    }
    if (this.filterStars !== "all") {
      const f = this.filterStars;
      if (f === "rated")        items = items.filter(e => (e.user_rating || 0) > 0);
      else if (f === "unrated") items = items.filter(e => !(e.user_rating || 0));
      else                       items = items.filter(e => (e.user_rating || 0) >= parseInt(f, 10));
    }
    if (this.search) {
      const q = this.search;
      items = items.filter(e =>
        (e.ticker || "").toLowerCase().includes(q) ||
        (e.user_note || "").toLowerCase().includes(q)
      );
    }

    // sort — pinned always group first, then by selected sort
    const cmp = (() => {
      switch (this.sort) {
        case "time-asc":   return (a, b) => new Date(a.completedAt || a.startedAt) - new Date(b.completedAt || b.startedAt);
        case "rating-desc":return (a, b) => (b.user_rating || 0) - (a.user_rating || 0)
                                             || new Date(b.completedAt || b.startedAt) - new Date(a.completedAt || a.startedAt);
        case "ticker":     return (a, b) => (a.ticker || "").localeCompare(b.ticker || "");
        default:           return (a, b) => new Date(b.completedAt || b.startedAt) - new Date(a.completedAt || a.startedAt);
      }
    })();
    items.sort(cmp);

    return items;
  },

  render() {
    if (!this.cache.length) {
      this.emptyEl.style.display = "block";
      this.emptyEl.textContent = this._useRemote()
        ? "云端无记录。完成一次分析后会自动保存。"
        : "暂无记录。完成一次分析后会自动保存（仅当前浏览器；登录可云端同步）。";
      this.listEl.innerHTML = "";
      return;
    }
    this.emptyEl.style.display = "none";

    const items = this._filteredSorted();
    if (!items.length) {
      this.listEl.innerHTML = `<li class="muted" style="padding:14px; cursor:default;">无匹配记录。调整筛选条件。</li>`;
      return;
    }

    // Pinned group on top, regular group below
    const pinned = items.filter(x => x.pinned);
    const rest = items.filter(x => !x.pinned);

    const renderRow = (e) => {
      const stars = e.user_rating || 0;
      const dir = this._direction(e.rating);
      const dirEmoji = { bull: "🟢", bear: "🔴", hold: "⚪" }[dir] || "";
      return `
        <li data-history-id="${e.id}" class="${e.pinned ? "pinned" : ""}">
          <span class="ticker">${dirEmoji} ${escapeHtml(e.ticker)}</span>
          <span class="rating-pill ${e.rating || ""}">${escapeHtml(e.rating || "—")}</span>
          <span class="date">${escapeHtml(e.trade_date)}</span>
          <span class="ts">${new Date(e.completedAt || e.startedAt).toLocaleString()}</span>
          <div class="row-line2">
            <button class="pin-btn ${e.pinned ? "on" : ""}" data-pin="${e.id}" title="${e.pinned ? "取消置顶" : "置顶"}">${e.pinned ? "📌" : "📍"}</button>
            <span class="stars-mini" data-rate-id="${e.id}">
              ${[1,2,3,4,5].map(n => `<span class="star ${stars >= n ? "on" : ""}" data-star="${n}">★</span>`).join("")}
            </span>
            <button class="delete-btn" data-delete="${e.id}" style="margin-left:auto;">删除</button>
          </div>
        </li>`;
    };

    let html = "";
    if (pinned.length) {
      html += `<li class="group-divider">📌 已置顶 (${pinned.length})</li>`;
      html += pinned.map(renderRow).join("");
    }
    if (rest.length) {
      if (pinned.length) html += `<li class="group-divider">其他 (${rest.length})</li>`;
      html += rest.map(renderRow).join("");
    }
    this.listEl.innerHTML = html;

    // open entry
    this.listEl.querySelectorAll("li[data-history-id]").forEach(li => {
      li.addEventListener("click", async ev => {
        if (ev.target.dataset.delete || ev.target.dataset.pin || ev.target.dataset.star
            || ev.target.classList.contains("stars-mini") || ev.target.classList.contains("pin-btn")) return;
        const entry = await History.getEntry(li.dataset.historyId);
        if (!entry) return;
        document.querySelector('nav.tabs button[data-tab="decision"]').click();
        WindowManager.openHistorical(entry);
      });
    });
    // delete
    this.listEl.querySelectorAll("[data-delete]").forEach(b => {
      b.addEventListener("click", async ev => {
        ev.stopPropagation();
        await History.delete(b.dataset.delete);
      });
    });
    // pin toggle
    this.listEl.querySelectorAll("[data-pin]").forEach(b => {
      b.addEventListener("click", async ev => {
        ev.stopPropagation();
        const id = b.dataset.pin;
        const entry = this.cache.find(e => e.id === id);
        await this.setPinned(id, !(entry && entry.pinned));
      });
    });
    // star rate (with hover preview)
    this.listEl.querySelectorAll(".stars-mini").forEach(group => {
      const stars = group.querySelectorAll(".star");
      const id = group.dataset.rateId;
      stars.forEach((s, i) => {
        s.addEventListener("mouseenter", () => {
          stars.forEach((x, j) => x.classList.toggle("hov-on", j <= i));
        });
        s.addEventListener("click", async ev => {
          ev.stopPropagation();
          const rating = i + 1;
          const cur = (this.cache.find(e => e.id === id) || {}).user_rating || 0;
          await this.setRating(id, cur === rating ? 0 : rating);  // click same → clear
        });
      });
      group.addEventListener("mouseleave", () => {
        stars.forEach(x => x.classList.remove("hov-on"));
      });
    });
  },
};

// =========================================================================
// Auth UI — login / signup / magic-link modal
// =========================================================================
const AuthUI = {
  mode: "signin",
  init() {
    this.modal = document.getElementById("auth-modal");
    this.titleEl = document.getElementById("auth-title");
    this.errEl = document.getElementById("auth-error");
    this.hintEl = document.getElementById("auth-hint");
    this.pwdField = document.querySelector(".auth-pwd-field");
    this.nameField = document.querySelector(".auth-name-field");
    this.submitBtn = document.getElementById("auth-submit");
    this.statusEl = document.getElementById("auth-status");
    this.btnEl = document.getElementById("auth-button");

    this.btnEl.addEventListener("click", () => this.toggle());
    document.getElementById("auth-close").addEventListener("click", () => this.close());
    this.modal.addEventListener("click", e => { if (e.target === this.modal) this.close(); });
    document.querySelectorAll(".auth-tab").forEach(t => {
      t.addEventListener("click", () => this.setMode(t.dataset.mode));
    });
    document.getElementById("auth-form").addEventListener("submit", e => { e.preventDefault(); this.submit(); });
    this.submitBtn.addEventListener("click", e => { e.preventDefault(); this.submit(); });

    // Reflect current auth state immediately + on changes
    if (window.Auth) {
      window.Auth.onChange(() => this.renderStatus());
    }
    this.renderStatus();
  },

  renderStatus() {
    const auth = window.Auth;
    if (!auth || !auth.isConfigured()) {
      this.btnEl.style.display = "none";
      this.statusEl.style.display = "inline";
      this.statusEl.innerHTML = `<span class="muted">本地模式 · 历史保存于浏览器</span>`;
      return;
    }
    if (auth.isSignedIn()) {
      const u = auth.user();
      const name = u?.user_metadata?.display_name || u?.email || "user";
      this.btnEl.textContent = "退出登录";
      this.btnEl.title = u?.email || "";
      this.statusEl.style.display = "inline";
      this.statusEl.innerHTML = `<span class="name">👤 ${escapeHtml(name)}</span>`;
    } else {
      this.btnEl.textContent = "👤 登录";
      this.btnEl.title = "登录 / 注册";
      this.statusEl.style.display = "none";
    }
  },

  toggle() {
    const auth = window.Auth;
    if (!auth || !auth.isConfigured()) return;
    if (auth.isSignedIn()) {
      auth.signOut();
      return;
    }
    this.open();
  },

  open() { this.modal.style.display = "flex"; this.errEl.textContent = ""; this.hintEl.textContent = ""; document.getElementById("auth-email").focus(); },
  close() { this.modal.style.display = "none"; },

  setMode(mode) {
    this.mode = mode;
    document.querySelectorAll(".auth-tab").forEach(t => t.classList.toggle("active", t.dataset.mode === mode));
    this.titleEl.textContent = ({ signin: "登录", signup: "注册", magic: "魔法链接登录" })[mode];
    this.submitBtn.textContent = ({ signin: "登录", signup: "创建账户", magic: "发送链接" })[mode];
    this.pwdField.style.display = mode === "magic" ? "none" : "flex";
    this.nameField.style.display = mode === "signup" ? "flex" : "none";
    this.errEl.textContent = "";
    this.hintEl.textContent = mode === "magic"
      ? "我们会发送一封含登录链接的邮件，无需记忆密码。"
      : "";
  },

  async submit() {
    const email = document.getElementById("auth-email").value.trim();
    const password = document.getElementById("auth-password").value;
    const displayName = document.getElementById("auth-display-name").value.trim();
    if (!email) { this.errEl.textContent = "请输入邮箱"; return; }
    if (this.mode !== "magic" && password.length < 6) { this.errEl.textContent = "密码至少 6 位"; return; }
    this.submitBtn.disabled = true;
    this.errEl.textContent = "";
    try {
      if (this.mode === "signin") {
        await window.Auth.signIn(email, password);
        this.hintEl.textContent = "登录成功。";
        setTimeout(() => this.close(), 600);
      } else if (this.mode === "signup") {
        await window.Auth.signUp(email, password, displayName);
        this.hintEl.textContent = "注册成功。请检查邮箱以确认账户（若已禁用邮箱确认则可直接登录）。";
      } else if (this.mode === "magic") {
        await window.Auth.signInWithMagicLink(email);
        this.hintEl.textContent = "登录链接已发送，请检查邮箱。";
      }
    } catch (e) {
      this.errEl.textContent = e.message || String(e);
    } finally {
      this.submitBtn.disabled = false;
    }
  },
};

// =========================================================================
// Opportunities — 24h trading-opportunity feed
// =========================================================================
const Opportunities = {
  pollInterval: 30000,
  cache: [],
  filterSev: "all",
  filterInst: "all",
  _timer: null,

  init() {
    this.listEl = document.getElementById("opps-list");
    this.statusEl = document.getElementById("opps-status");
    this.navBadgeEl = document.getElementById("opps-nav-badge");

    document.getElementById("opps-refresh").addEventListener("click", () => this.refresh());

    document.querySelectorAll("[data-opps-sev]").forEach(b => {
      b.addEventListener("click", () => {
        document.querySelectorAll("[data-opps-sev]").forEach(x => x.classList.remove("active"));
        b.classList.add("active");
        this.filterSev = b.dataset.oppsSev;
        this.render();
      });
    });
    document.querySelectorAll("[data-opps-inst]").forEach(b => {
      b.addEventListener("click", () => {
        document.querySelectorAll("[data-opps-inst]").forEach(x => x.classList.remove("active"));
        b.classList.add("active");
        this.filterInst = b.dataset.oppsInst;
        this.render();
      });
    });

    this.refresh();
    this._timer = setInterval(() => this.refresh(), this.pollInterval);
  },

  // Instrument inference from ticker/type — kept on the frontend so we don't
  // need to backfill the backend payload for already-emitted opportunities.
  inferInstrument(opp) {
    const t = (opp.ticker || "").toUpperCase();
    const ty = (opp.type || "").toLowerCase();
    if (!t) return ty.includes("macro") ? "macro" : "macro";
    if (t.endsWith("-USD") || t.endsWith("USDT") || t.startsWith("BTC") || t.startsWith("ETH"))
      return "crypto";
    if (/^(SPY|QQQ|DIA|IWM|VTI|VOO|XL[A-Z]|GLD|SLV|TLT|IEF|BND|AGG|HYG|EEM|VEA|VWO)$/.test(t))
      return "etf";
    if (/^(GC|SI|CL|NG|HG|ZC|ZW)/.test(t)) return "commodity";
    if (/^[A-Z]{6}=X$|^USD|^EUR|^GBP|^JPY|^CNY/.test(t)) return "forex";
    return "stock";
  },

  async refresh() {
    try {
      const apiBase = (window.APP_CONFIG && window.APP_CONFIG.API_BASE_URL) || "";
      const r = await fetch(`${apiBase}/api/opportunities?limit=50`);
      if (!r.ok) throw new Error(`opps ${r.status}`);
      const j = await r.json();
      const newCount = (j.items || []).length;
      const seenBefore = this.cache.length;
      this.cache = j.items || [];
      this.render();
      if (this.statusEl) this.statusEl.textContent = `共 ${newCount} 条 · 更新于 ${new Date().toLocaleTimeString()}`;
      // Show a red badge in nav when there are unseen high/critical items
      const urgent = this.cache.filter(o => o.severity === "high" || o.severity === "critical").length;
      if (this.navBadgeEl) {
        this.navBadgeEl.style.display = urgent > 0 ? "inline-block" : "none";
        this.navBadgeEl.textContent = urgent;
      }
    } catch (e) {
      if (this.statusEl) this.statusEl.textContent = `获取失败：${e.message}`;
    }
  },

  render() {
    let filtered = this.cache;
    if (this.filterSev !== "all") filtered = filtered.filter(o => o.severity === this.filterSev);
    if (this.filterInst !== "all") filtered = filtered.filter(o => this.inferInstrument(o) === this.filterInst);
    if (!filtered.length) {
      this.listEl.innerHTML = `<div class="muted" style="padding:32px; text-align:center;">该过滤条件下暂无机会。</div>`;
      return;
    }
    const sevEmoji = { critical: "🔴", high: "🟠", watch: "🟡", info: "⚪" };
    const instEmoji = { stock: "📈", etf: "🧺", crypto: "₿", commodity: "🛢", forex: "💱", macro: "🌐" };
    const stratNameById = (id) => (typeof STRATEGIES !== "undefined" && STRATEGIES.find(s => s.id === id)?.name) || id;

    this.listEl.innerHTML = filtered.map(o => {
      const ts = new Date(o.created_at);
      const ago = (Date.now() - ts.getTime()) / 60000;
      const agoStr = ago < 1 ? "刚刚" : ago < 60  ? `${Math.round(ago)}m 前` : `${Math.round(ago/60)}h 前`;
      const isFav = Favorites.isFavorited("opportunity", o.id);
      const inst = this.inferInstrument(o);
      return `
        <div class="opp-card severity-${o.severity}">
          <div class="severity"></div>
          <div class="info">
            <div class="row1">
              <span title="重要度: ${o.severity}">${sevEmoji[o.severity] || "⚪"}</span>
              ${o.ticker ? `<span class="ticker">${escapeHtml(o.ticker)}</span>` : ""}
              <span class="inst-badge" title="品种: ${inst}">${instEmoji[inst] || ""} ${inst}</span>
              <span class="type">${escapeHtml(o.type)}</span>
              <span class="ts">${agoStr} · ${ts.toLocaleString()}</span>
            </div>
            <div class="headline">${escapeHtml(o.headline)}</div>
            ${o.body ? `<div class="body">${escapeHtml(o.body)}</div>` : ""}
            ${(o.suggested_strategies && o.suggested_strategies.length) ? `
              <div class="strats">
                <span class="muted" style="font-size:11px;">建议策略:</span>
                ${o.suggested_strategies.map(sid => `<span class="strat" data-strategy-id="${sid}">${escapeHtml(stratNameById(sid))}</span>`).join("")}
              </div>` : ""}
          </div>
          <div class="actions">
            <button class="star ${isFav ? "on" : ""}" data-opp-fav="${o.id}" title="收藏">${isFav ? "★" : "☆"}</button>
          </div>
        </div>
      `;
    }).join("");

    // strategy chip → jump to library tab
    this.listEl.querySelectorAll(".strat").forEach(el => {
      el.addEventListener("click", () => {
        document.querySelector('nav.tabs button[data-tab="library"]').click();
        setTimeout(() => {
          const card = document.querySelector(`.strategy-card[data-id="${el.dataset.strategyId}"]`);
          if (card) {
            card.scrollIntoView({ block: "center" });
            card.classList.add("expanded");
          }
        }, 100);
      });
    });
    // star → toggle favorite
    this.listEl.querySelectorAll("[data-opp-fav]").forEach(btn => {
      btn.addEventListener("click", e => {
        e.stopPropagation();
        const oppId = btn.dataset.oppFav;
        const opp = this.cache.find(o => o.id === oppId);
        Favorites.toggle("opportunity", oppId, opp ? {
          headline: opp.headline, ticker: opp.ticker, severity: opp.severity, type: opp.type,
        } : {});
        this.render();
      });
    });
  },
};

// =========================================================================
// Favorites — local storage (and Supabase via Auth.client when signed in)
// =========================================================================
const Favorites = {
  LOCAL_KEY: "tda:favorites",
  cache: [],
  activeTab: "strategy",

  init() {
    this.listEl = document.getElementById("favorites-list");
    document.querySelectorAll("[data-fav-tab]").forEach(b => {
      b.addEventListener("click", () => {
        document.querySelectorAll("[data-fav-tab]").forEach(x => x.classList.remove("active"));
        b.classList.add("active");
        this.activeTab = b.dataset.favTab;
        this.render();
      });
    });
    if (window.Auth) window.Auth.onChange(() => this.refresh());
    this.refresh();
  },

  _useRemote() { return Boolean(window.Auth && window.Auth.isSignedIn() && window.Auth.rawClient()); },

  async refresh() {
    if (this._useRemote()) {
      const { data } = await window.Auth.rawClient()
        .from("favorites").select("*")
        .order("created_at", { ascending: false }).limit(500);
      this.cache = (data || []).map(r => ({
        id: r.id, kind: r.kind, ref_id: r.ref_id,
        label: r.label || {}, created_at: r.created_at,
      }));
    } else {
      try { this.cache = JSON.parse(localStorage.getItem(this.LOCAL_KEY) || "[]"); }
      catch { this.cache = []; }
    }
    this.render();
    this._updateCounts();
  },

  isFavorited(kind, refId) {
    return this.cache.some(f => f.kind === kind && f.ref_id === refId);
  },

  async toggle(kind, refId, label = {}) {
    if (this.isFavorited(kind, refId)) {
      await this.remove(kind, refId);
    } else {
      await this.add(kind, refId, label);
    }
  },

  async add(kind, refId, label = {}) {
    if (this._useRemote()) {
      await window.Auth.rawClient().from("favorites").upsert({
        user_id: window.Auth.user().id, kind, ref_id: refId, label,
      }, { onConflict: "user_id,kind,ref_id" });
    } else {
      const all = this._readLocal();
      if (!all.some(f => f.kind === kind && f.ref_id === refId)) {
        all.unshift({ id: Date.now(), kind, ref_id: refId, label, created_at: new Date().toISOString() });
        localStorage.setItem(this.LOCAL_KEY, JSON.stringify(all));
      }
    }
    await this.refresh();
  },

  async remove(kind, refId) {
    if (this._useRemote()) {
      await window.Auth.rawClient().from("favorites").delete()
        .eq("kind", kind).eq("ref_id", refId);
    } else {
      const all = this._readLocal().filter(f => !(f.kind === kind && f.ref_id === refId));
      localStorage.setItem(this.LOCAL_KEY, JSON.stringify(all));
    }
    await this.refresh();
  },

  _readLocal() {
    try { return JSON.parse(localStorage.getItem(this.LOCAL_KEY) || "[]"); }
    catch { return []; }
  },

  _updateCounts() {
    document.getElementById("fav-count-strategy").textContent    = this.cache.filter(f => f.kind === "strategy").length;
    document.getElementById("fav-count-decision").textContent    = this.cache.filter(f => f.kind === "decision").length;
    const oppEl = document.getElementById("fav-count-opportunity");
    if (oppEl) oppEl.textContent = this.cache.filter(f => f.kind === "opportunity").length;
    const stat = document.getElementById("stat-favorites");
    if (stat) stat.textContent = this.cache.length;
  },

  render() {
    const items = this.cache.filter(f => f.kind === this.activeTab);
    if (!items.length) {
      this.listEl.innerHTML = `<div class="muted" style="padding:32px; text-align:center;">${
        this.activeTab === "strategy" ? "未收藏任何策略。在策略库点击 ★ 添加。"
                                      : "未收藏任何决策。在历史决策右键添加。"
      }</div>`;
      return;
    }
    if (this.activeTab === "strategy") {
      this.listEl.innerHTML = items.map(f => {
        const s = (typeof STRATEGIES !== "undefined") ? STRATEGIES.find(x => x.id === f.ref_id) : null;
        const name = s?.name || f.label?.name || f.ref_id;
        const desc = s?.desc || f.label?.desc || "";
        return `
          <div class="favorite-card" data-strategy-id="${f.ref_id}">
            <div class="icon">📚</div>
            <div class="info">
              <div class="title">${escapeHtml(name)}</div>
              <div class="meta">${escapeHtml(desc)}</div>
            </div>
            <button class="unfav" data-unfav-kind="strategy" data-unfav-ref="${f.ref_id}">取消收藏</button>
          </div>`;
      }).join("");
      this.listEl.querySelectorAll(".favorite-card").forEach(card => {
        card.addEventListener("click", ev => {
          if (ev.target.dataset.unfavKind) return;
          document.querySelector('nav.tabs button[data-tab="library"]').click();
          setTimeout(() => {
            const sCard = document.querySelector(`.strategy-card[data-id="${card.dataset.strategyId}"]`);
            if (sCard) { sCard.scrollIntoView({ block: "center" }); sCard.classList.add("expanded"); }
          }, 100);
        });
      });
    } else if (this.activeTab === "decision") {
      this.listEl.innerHTML = items.map(f => {
        const lbl = f.label || {};
        return `
          <div class="favorite-card" data-decision-id="${f.ref_id}">
            <div class="icon">🎯</div>
            <div class="info">
              <div class="title">${escapeHtml(lbl.ticker || f.ref_id)} · ${escapeHtml(lbl.rating || "—")}</div>
              <div class="meta">${escapeHtml(lbl.trade_date || "")}  ·  收藏于 ${new Date(f.created_at).toLocaleString()}</div>
            </div>
            <button class="unfav" data-unfav-kind="decision" data-unfav-ref="${f.ref_id}">取消收藏</button>
          </div>`;
      }).join("");
      this.listEl.querySelectorAll(".favorite-card").forEach(card => {
        card.addEventListener("click", async ev => {
          if (ev.target.dataset.unfavKind) return;
          const id = card.dataset.decisionId;
          const entry = await History.getEntry(id);
          if (!entry) { alert("找不到原始决策（可能已删除）"); return; }
          document.querySelector('nav.tabs button[data-tab="decision"]').click();
          WindowManager.openHistorical(entry);
        });
      });
    } else if (this.activeTab === "opportunity") {
      const sevEmoji = { critical: "🔴", high: "🟠", watch: "🟡", info: "⚪" };
      this.listEl.innerHTML = items.map(f => {
        const lbl = f.label || {};
        const sev = sevEmoji[lbl.severity] || "⚪";
        return `
          <div class="favorite-card" data-opp-id="${f.ref_id}">
            <div class="icon">${sev}</div>
            <div class="info">
              <div class="title">${escapeHtml(lbl.ticker || lbl.type || f.ref_id)}</div>
              <div class="meta">${escapeHtml(lbl.headline || "")}  ·  收藏于 ${new Date(f.created_at).toLocaleString()}</div>
            </div>
            <button class="unfav" data-unfav-kind="opportunity" data-unfav-ref="${f.ref_id}">取消收藏</button>
          </div>`;
      }).join("");
      this.listEl.querySelectorAll(".favorite-card").forEach(card => {
        card.addEventListener("click", async ev => {
          if (ev.target.dataset.unfavKind) return;
          // Jump to 24h opportunities tab and try to scroll to the same id
          document.querySelector('nav.tabs button[data-tab="opportunities"]').click();
        });
      });
    }
    this.listEl.querySelectorAll("[data-unfav-kind]").forEach(btn => {
      btn.addEventListener("click", async ev => {
        ev.stopPropagation();
        await Favorites.remove(btn.dataset.unfavKind, btn.dataset.unfavRef);
      });
    });
  },
};

// =========================================================================
// Profile — 资料 / 用量 / 设置 sub-tabs
// =========================================================================
const Profile = {
  // ── settings: data-source vendor keys
  DATA_KEYS: [
    { id: "FINNHUB_API_KEY",          label: "Finnhub Pro",          dash: "https://finnhub.io/dashboard" },
    { id: "POLYGON_API_KEY",          label: "Polygon.io",           dash: "https://polygon.io/dashboard" },
    { id: "ALPHA_VANTAGE_API_KEY",    label: "Alpha Vantage Premium",dash: "https://www.alphavantage.co/account/" },
    { id: "FMP_API_KEY",              label: "FMP Premium",          dash: "https://site.financialmodelingprep.com/dashboard" },
    { id: "NASDAQ_DATA_LINK_API_KEY", label: "Nasdaq Data Link",     dash: "https://data.nasdaq.com/account/profile" },
    { id: "DASHSCOPE_API_KEY",        label: "Qwen / DashScope (可选: 仅作数据源时)", dash: "https://dashscope.console.aliyun.com" },
    { id: "JQDATA_USERNAME",          label: "JQData (用户名)",       dash: "https://www.joinquant.com/help/api/data-help" },
    { id: "JQDATA_PASSWORD",          label: "JQData (密码)" },
    { id: "RQDATA_USERNAME",          label: "RQData 米筐 (用户名)",  dash: "https://www.ricequant.com/welcome/rqdata" },
    { id: "RQDATA_PASSWORD",          label: "RQData 米筐 (密码)" },
  ],

  // ── settings: LLM provider keys
  LLM_KEYS: [
    { id: "OPENAI_API_KEY",     label: "OpenAI (GPT-5.x)",          dash: "https://platform.openai.com/usage" },
    { id: "ANTHROPIC_API_KEY",  label: "Anthropic (Claude 4.x)",    dash: "https://console.anthropic.com/settings/usage" },
    { id: "GOOGLE_API_KEY",     label: "Google (Gemini 3.x)",       dash: "https://aistudio.google.com" },
    { id: "DEEPSEEK_API_KEY",   label: "DeepSeek (V4)",             dash: "https://platform.deepseek.com/usage" },
    { id: "DASHSCOPE_API_KEY",  label: "Qwen 通义千问 (3.6)",       dash: "https://dashscope.console.aliyun.com" },
    { id: "MOONSHOT_API_KEY",   label: "Kimi (Moonshot K2.6)",      dash: "https://platform.moonshot.cn/console" },
    { id: "ZHIPU_API_KEY",      label: "智谱 GLM (5)",              dash: "https://open.bigmodel.cn/usercenter" },
  ],

  init() {
    // Sub-tab switcher
    document.querySelectorAll(".profile-tab").forEach(b => {
      b.addEventListener("click", () => {
        document.querySelectorAll(".profile-tab").forEach(x => x.classList.remove("active"));
        b.classList.add("active");
        document.querySelectorAll(".profile-pane").forEach(p => p.classList.remove("active"));
        document.querySelector(`[data-profile-pane="${b.dataset.profileTab}"]`).classList.add("active");
      });
    });

    if (window.Auth) window.Auth.onChange(() => this.renderAll());
    this.renderAll();
  },

  async renderAll() {
    await Promise.all([
      this.renderInfo(),
      this.renderUsage(),
      this.renderDataKeys(),
      this.renderLlmKeys(),
      this.renderPrefs(),
      this.fetchDataflows(),
    ]);
  },

  // ────────────────────────────────────────────── 资料 (info)
  async renderInfo() {
    const el = document.getElementById("profile-info");
    if (!el) return;
    if (!window.Auth || !window.Auth.isSignedIn()) {
      el.innerHTML = `<div class="muted" style="padding:12px 0;">未登录 — 请右上角登录后管理账号、保存 API key、查看历史与用量。</div>`;
      ["stat-decisions", "stat-favorites", "stat-pinned", "stat-rated"].forEach(id => {
        const e = document.getElementById(id); if (e) e.textContent = "—";
      });
      return;
    }
    const u = window.Auth.user();
    let profile = null;
    try {
      const { data } = await window.Auth.rawClient().from("profiles").select("*").eq("id", u.id).single();
      profile = data;
    } catch {}
    const dn = profile?.display_name || u.user_metadata?.display_name || "";
    el.innerHTML = `
      <dl>
        <dt>邮箱</dt><dd>${escapeHtml(u.email || "")}</dd>
        <dt>显示名称</dt>
        <dd>
          <input type="text" id="profile-display-name" value="${escapeHtml(dn)}" />
          <button class="btn secondary small" id="profile-save-name" style="margin-left:6px;">保存</button>
          <span class="muted" id="profile-save-status" style="font-size:11px; margin-left:6px;"></span>
        </dd>
        <dt>注册时间</dt><dd>${new Date(u.created_at).toLocaleString()}</dd>
        <dt>用户 ID</dt><dd style="font-family:monospace; font-size:11px; word-break:break-all;">${escapeHtml(u.id)}</dd>
      </dl>
    `;
    document.getElementById("profile-save-name").addEventListener("click", async () => {
      const name = document.getElementById("profile-display-name").value.trim();
      const status = document.getElementById("profile-save-status");
      const { error } = await window.Auth.rawClient().from("profiles").upsert({ id: u.id, display_name: name });
      status.textContent = error ? `失败: ${error.message}` : "✓ 已保存";
      if (!error) AuthUI.renderStatus();
      setTimeout(() => status.textContent = "", 2000);
    });
    // Activity stats from cached History + Favorites
    document.getElementById("stat-decisions").textContent = History.cache.length;
    document.getElementById("stat-favorites").textContent = Favorites.cache.length;
    document.getElementById("stat-pinned").textContent    = History.cache.filter(e => e.pinned).length;
    document.getElementById("stat-rated").textContent     = History.cache.filter(e => (e.user_rating || 0) > 0).length;
  },

  // ────────────────────────────────────────────── 用量 (usage)
  /**
   * Fetch the backend's per-model price table once per session and
   * cache it. Returned shape: { provider: [{model, input_per_1m_usd,
   * output_per_1m_usd}] }. Returns {} if the fetch fails so callers can
   * still render a degraded UI ("—" for cost).
   */
  async _fetchCostTable() {
    if (this._costTableCache) return this._costTableCache;
    try {
      const apiBase = (window.APP_CONFIG && window.APP_CONFIG.API_BASE_URL) || "";
      const r = await fetch(`${apiBase}/api/cost-table`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      this._costTableCache = await r.json();
    } catch (e) {
      console.warn("cost-table fetch failed:", e);
      this._costTableCache = {};
    }
    return this._costTableCache;
  },

  /**
   * Look up the per-1M USD prices for a (provider, model) pair against
   * a cost-table object (shape returned by _fetchCostTable). Mirrors
   * the longest-prefix-wins logic of backend/cost_table.py so the
   * front-end and back-end agree on cost numbers.
   */
  _lookupPrice(costTable, provider, model) {
    const p = (provider || "").toLowerCase();
    const m = (model || "").toLowerCase();
    const rows = costTable[p] || [];
    let best = null;
    for (const row of rows) {
      const mp = (row.model || "").toLowerCase();
      if (m.startsWith(mp) && (!best || mp.length > best.model.length)) {
        best = { model: mp, input: row.input_per_1m_usd, output: row.output_per_1m_usd };
      }
    }
    return best;
  },

  /**
   * Format a USD amount for the .cost column. Returns "—" if the price
   * lookup failed (unknown model) so the user sees a clear "no data"
   * marker rather than a misleading $0.00.
   */
  _formatCost(usd) {
    if (usd === null || usd === undefined) return "—";
    if (usd === 0) return "$0.00";
    if (usd < 0.01) return "<$0.01";
    return `$${usd.toFixed(2)}`;
  },

  async renderUsage() {
    const llmEl = document.getElementById("usage-llm");
    const dataEl = document.getElementById("usage-data");
    if (!llmEl || !dataEl) return;

    if (!window.Auth || !window.Auth.isSignedIn()) {
      llmEl.innerHTML = `<div class="muted" style="padding:12px 0;">登录后查看决策中的模型使用频次。</div>`;
      dataEl.innerHTML = `<div class="muted" style="padding:12px 0;">登录后查看数据源调用频次估算。</div>`;
      return;
    }

    // Tally LLM usage from decisions.params.llm_provider in last 90d
    const llmCounts = {};
    const dataCounts = { news: 0, market: 0, fundamentals: 0, social: 0 };
    const cutoff = Date.now() - 90 * 86400 * 1000;
    for (const e of History.cache) {
      const ts = new Date(e.completedAt || e.startedAt).getTime();
      if (ts < cutoff) continue;
      const p = (e.params || {}).llm_provider || "unknown";
      llmCounts[p] = (llmCounts[p] || 0) + 1;
      // every LIVE decision triggers ~4 dataflow calls (one per analyst)
      Object.keys(dataCounts).forEach(c => { dataCounts[c] += 1; });
    }

    // Fetch the cost table + sum tokens per provider over the last 90d
    // so each row can show a $-cost estimate alongside the call count.
    // We try Supabase first (the system-of-record once usage_events is
    // flushed there), and fall back to History.cache if the query
    // fails or returns no rows (e.g. RLS not yet provisioned).
    const costTable = await this._fetchCostTable();
    const cutoffIso = new Date(cutoff).toISOString();
    const usageByProv = {};   // provId -> [{model, tokens_in, tokens_out}]
    let usedSupabase = false;
    if (window.Auth?.rawClient) {
      try {
        const { data, error } = await window.Auth.rawClient()
          .from("usage_events")
          .select("provider, model, tokens_in, tokens_out")
          .eq("kind", "llm_call")
          .gte("ts", cutoffIso);
        if (!error && Array.isArray(data)) {
          usedSupabase = true;
          for (const row of data) {
            const pid = (row.provider || "unknown").toLowerCase();
            (usageByProv[pid] ||= []).push({
              model: row.model || "",
              tokens_in: row.tokens_in || 0,
              tokens_out: row.tokens_out || 0,
            });
          }
        }
      } catch (e) {
        console.warn("usage_events query failed, falling back to cache:", e);
      }
    }
    if (!usedSupabase) {
      // Walk History.cache for entries' runState.usage_events. Same
      // aggregation shape as the Supabase branch above.
      for (const e of History.cache) {
        const ts = new Date(e.completedAt || e.startedAt).getTime();
        if (ts < cutoff) continue;
        const events = (e.runState && e.runState.usage_events) || [];
        for (const ev of events) {
          if (ev.kind && ev.kind !== "llm_call") continue;
          const pid = (ev.provider || "unknown").toLowerCase();
          (usageByProv[pid] ||= []).push({
            model: ev.model || "",
            tokens_in: ev.tokens_in || 0,
            tokens_out: ev.tokens_out || 0,
          });
        }
      }
    }

    // Sum cost per provider. If every event in a provider lacks pricing
    // data we render "—"; otherwise we render the partial sum (unknown
    // models contribute $0 and we silently skip them).
    const costByProv = {};
    for (const [pid, events] of Object.entries(usageByProv)) {
      let total = 0;
      let priced = 0;
      for (const ev of events) {
        const price = this._lookupPrice(costTable, pid, ev.model);
        if (!price) continue;
        priced += 1;
        total += (ev.tokens_in / 1_000_000) * price.input
               + (ev.tokens_out / 1_000_000) * price.output;
      }
      costByProv[pid] = priced > 0 ? total : null;
    }

    const llmRows = this.LLM_KEYS.map(p => {
      const k = p.id.replace(/_API_KEY$/, "").toLowerCase();
      // map env → provider id used in /api/config
      const provMap = {
        openai_api_key: "openai", anthropic_api_key: "anthropic",
        google_api_key: "google", deepseek_api_key: "deepseek",
        dashscope_api_key: "qwen", moonshot_api_key: "kimi", zhipu_api_key: "glm",
      };
      const provId = provMap[p.id.toLowerCase()] || k;
      const count = llmCounts[provId] || 0;
      const cost = this._formatCost(costByProv[provId]);
      return `
        <div class="usage-row">
          <span class="icon">🧠</span>
          <div>
            <div class="name">${escapeHtml(p.label)}</div>
            <div class="meta">用作 deep / quick 模型 · 近 90 天 ${count} 次决策</div>
          </div>
          <div class="count">${count}</div>
          <div class="cost">${cost}</div>
          ${p.dash ? `<a class="dash-link" href="${p.dash}" target="_blank" rel="noopener">vendor 用量 ↗</a>` : `<span></span>`}
        </div>`;
    }).join("");
    llmEl.innerHTML = llmRows;

    const dataRows = Object.entries(dataCounts).map(([cat, n]) => `
      <div class="usage-row">
        <span class="icon">${ {market:"📈", news:"📰", fundamentals:"💼", social:"💬"}[cat] || "📊"}</span>
        <div>
          <div class="name">${cat}</div>
          <div class="meta">分析师调用估算（每次 LIVE 决策 ×1）</div>
        </div>
        <div class="count">${n}</div>
        <span></span>
        <span></span>
      </div>`).join("");
    dataEl.innerHTML = dataRows;
  },

  // ────────────────────────────────────────────── 设置: data API keys
  renderDataKeys() {
    const el = document.getElementById("settings-data-keys");
    if (!el) return;
    if (!window.Auth || !window.Auth.isSignedIn()) {
      el.innerHTML = `<div class="muted" style="padding:8px 0; font-size:13px;">登录后可保存数据源 API key（云端同步）。</div>`;
      return;
    }
    el.innerHTML = this.DATA_KEYS.map(k => this._keyRow(k, "data")).join("");
    this._loadKeys("data");
    el.querySelectorAll("[data-save-key]").forEach(btn => {
      btn.addEventListener("click", () => this._saveKey(btn.dataset.saveKey, "data"));
    });
  },

  // ────────────────────────────────────────────── 设置: LLM API keys
  renderLlmKeys() {
    const el = document.getElementById("settings-llm-keys");
    if (!el) return;
    if (!window.Auth || !window.Auth.isSignedIn()) {
      el.innerHTML = `<div class="muted" style="padding:8px 0; font-size:13px;">登录后可保存大模型 API key（云端同步）。</div>`;
      return;
    }
    el.innerHTML = this.LLM_KEYS.map(k => this._keyRow(k, "llm")).join("");
    this._loadKeys("llm");
    el.querySelectorAll("[data-save-key]").forEach(btn => {
      btn.addEventListener("click", () => this._saveKey(btn.dataset.saveKey, "llm"));
    });
  },

  _keyRow(k, kind) {
    const dashLink = k.dash ? ` <a href="${k.dash}" target="_blank" rel="noopener" class="dash-link" style="margin-left:4px;">用量 ↗</a>` : "";
    return `
      <div class="api-key-row" data-kind="${kind}">
        <span class="label-col">${escapeHtml(k.label)}${dashLink}</span>
        <input type="password" placeholder="${escapeHtml(k.id)}" data-api-key="${k.id}" data-kind="${kind}" autocomplete="off" />
        <button class="btn secondary save-btn" data-save-key="${k.id}" data-kind="${kind}">保存</button>
        <span class="status" data-key-status="${k.id}"></span>
      </div>`;
  },

  _columnFor(kind) {
    return kind === "llm" ? "llm_api_keys" : "custom_api_keys";
  },

  async _loadKeys(kind) {
    if (!window.Auth?.isSignedIn()) return;
    const u = window.Auth.user();
    const col = this._columnFor(kind);
    try {
      const { data } = await window.Auth.rawClient().from("profiles").select(col).eq("id", u.id).single();
      const keys = (data || {})[col] || {};
      const list = (kind === "llm" ? this.LLM_KEYS : this.DATA_KEYS);
      list.forEach(k => {
        const inp = document.querySelector(`[data-api-key="${k.id}"][data-kind="${kind}"]`);
        const stat = document.querySelector(`[data-key-status="${k.id}"]`);
        if (inp && keys[k.id]) {
          inp.value = "•".repeat(8);
          inp.dataset.hasValue = "1";
          if (stat) stat.textContent = "✓";
        }
      });
    } catch (e) { console.warn("load keys", kind, e); }
  },

  async _saveKey(envName, kind) {
    const inp = document.querySelector(`[data-api-key="${envName}"][data-kind="${kind}"]`);
    const stat = document.querySelector(`[data-key-status="${envName}"]`);
    const value = inp.value;
    if (!value || value.startsWith("•")) { stat.textContent = "—"; return; }
    const u = window.Auth.user();
    const client = window.Auth.rawClient();
    const col = this._columnFor(kind);
    try {
      const { data } = await client.from("profiles").select(col).eq("id", u.id).single();
      const keys = (data || {})[col] || {};
      keys[envName] = value;
      const update = { id: u.id }; update[col] = keys;
      const { error } = await client.from("profiles").upsert(update);
      stat.textContent = error ? `❌ ${error.message.slice(0, 30)}` : "✓";
      if (!error) {
        inp.value = "•".repeat(8);
        inp.dataset.hasValue = "1";
      }
    } catch (e) { stat.textContent = `❌ ${e.message}`; }
  },

  // ────────────────────────────────────────────── 设置: prefs
  async renderPrefs() {
    const el = document.getElementById("settings-prefs");
    if (!el) return;
    if (!window.Auth || !window.Auth.isSignedIn()) {
      el.innerHTML = `<div class="muted" style="padding:8px 0; font-size:13px;">登录后保存默认 LLM 提供商、研究深度等偏好。</div>`;
      return;
    }
    el.innerHTML = `
      <div class="muted" style="font-size:12px; margin-bottom:8px;">这些偏好作为新决策的默认值（保存到 <code>profiles.settings.prefs</code>）。</div>
      <div class="api-key-row" style="grid-template-columns: 120px 1fr auto;">
        <span class="label-col">主题</span>
        <select id="pref-theme">
          <option value="light">浅色</option>
          <option value="dark">深色</option>
        </select>
        <button class="btn secondary save-btn" id="prefs-save-btn">保存所有偏好</button>
      </div>
      <div class="api-key-row" style="grid-template-columns: 120px 1fr auto;">
        <span class="label-col">默认研究深度</span>
        <select id="pref-depth">
          <option value="1">1 轮（快速）</option>
          <option value="2">2 轮</option>
          <option value="3">3 轮</option>
          <option value="5">5 轮（极致）</option>
        </select>
        <span></span>
      </div>
      <span id="prefs-save-status" class="muted" style="font-size:11px;"></span>
    `;
    // load existing prefs
    const u = window.Auth.user();
    try {
      const { data } = await window.Auth.rawClient().from("profiles").select("settings, theme").eq("id", u.id).single();
      const prefs = (data?.settings || {}).prefs || {};
      document.getElementById("pref-theme").value = data?.theme || prefs.theme || "light";
      document.getElementById("pref-depth").value = String(prefs.research_depth || 1);
    } catch {}
    document.getElementById("prefs-save-btn").addEventListener("click", async () => {
      const theme = document.getElementById("pref-theme").value;
      const depth = parseInt(document.getElementById("pref-depth").value, 10) || 1;
      const status = document.getElementById("prefs-save-status");
      const { data } = await window.Auth.rawClient().from("profiles").select("settings").eq("id", u.id).single();
      const settings = data?.settings || {};
      settings.prefs = Object.assign({}, settings.prefs || {}, { theme, research_depth: depth });
      const { error } = await window.Auth.rawClient().from("profiles").upsert({ id: u.id, settings, theme });
      status.textContent = error ? `失败: ${error.message}` : "✓ 已保存";
      if (!error) { Theme.set(theme); }
      setTimeout(() => status.textContent = "", 2000);
    });
  },

  async fetchDataflows() {
    const el = document.getElementById("dataflows-status");
    if (!el) return;
    try {
      const apiBase = (window.APP_CONFIG && window.APP_CONFIG.API_BASE_URL) || "";
      const r = await fetch(`${apiBase}/api/dataflows`);
      const data = await r.json();
      const rows = [];
      Object.entries(data).forEach(([cat, vendors]) => {
        if (!vendors.length) {
          rows.push(`<div class="dataflow-row"><span class="cat">${cat}</span><span class="vendor">未注册</span><span class="status miss">—</span></div>`);
        } else {
          vendors.forEach(v => {
            rows.push(`
              <div class="dataflow-row">
                <span class="cat">${cat}</span>
                <span class="vendor">${escapeHtml(v.display_name)} <code style="font-size:10px;">${v.api_key_env}</code></span>
                <span class="status ${v.configured ? "ok" : "miss"}">${v.configured ? "已配置" : "未配置"}</span>
              </div>`);
          });
        }
      });
      el.innerHTML = rows.join("");
    } catch (e) {
      el.innerHTML = `<div class="muted" style="font-size:12px;">无法连接后端</div>`;
    }
  },
};

// =========================================================================
// Bootstrap
// =========================================================================
document.addEventListener("DOMContentLoaded", async () => {
  Theme.init();
  initTabs();
  initLibrary();
  initDecisionForm();
  WindowManager.init();

  // Wait for Supabase JS to be loaded (or skipped, if not configured).
  // auth.js triggers `supabase-ready` either way.
  await new Promise(resolve => {
    if (window.supabase || !window.APP_CONFIG?.SUPABASE_URL) return resolve();
    window.addEventListener("supabase-ready", resolve, { once: true });
  });

  // Init auth + UI + history (in order so History sees the auth state)
  if (window.Auth) await window.Auth.init();
  AuthUI.init();
  await History.init();
  Favorites.init();
  Opportunities.init();
  Profile.init();
});

// History.save needs to be async-safe — DecisionWindow calls it on complete
async function saveHistorySafely(window_) {
  try { await History.save(window_); } catch (e) { console.error("history save", e); }
}
