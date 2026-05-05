# Future work — known optimizations, with design notes

This document tracks optimizations that have been **considered** but **not
shipped**, with concrete implementation paths so a future PR can pick them
up cleanly. Items here are not "wishlist" — each one has been thought
through to the level of "what file changes, in what order, with what
test plan".

---

## #9 · Parallel analyst execution

**Status**: deferred. Touches `AgentState` schema OR adds 100+ lines to
`graph/setup.py`. Recommended as an independent PR with its own design
discussion.

### Why it matters

Wall-clock per LIVE decision today (`research_depth=1`):

| Stage | Time |
|---|---|
| 4 analysts sequential, ~25 s each | ~100 s |
| Bull/Bear debate | ~30 s |
| Risk 3-way debate | ~30 s |
| Trader + Portfolio Manager | ~20 s |
| **Total** | **~3 min** |

With parallel analysts:
- 4 analysts concurrent ≈ slowest (~30 s)
- Rest unchanged → ~90 s
- **Total: ~1.5 min**, ≈ 50 % reduction

### The structural blocker

All 4 analysts read/write `AgentState.messages` (from langgraph's
`MessagesState`). Inside each analyst's tool loop, the chat history
alternates between `AIMessage(tool_calls=...)` and `ToolMessage(...)`. If
4 analysts run concurrently the way `graph/setup.py` is currently
written (each `START → analyst_X` edge), their tool-call/result pairs
would interleave on the same channel and the LLMs would lose track of
which result belongs to which call.

### Two implementation paths

**Path A — namespaced messages** (~40 line patch across 5 files; collides
with upstream)

```python
# tradingagents/agents/utils/agent_states.py
class AgentState(MessagesState):
    market_messages:       Annotated[list, add_messages]
    social_messages:       Annotated[list, add_messages]
    news_messages:         Annotated[list, add_messages]
    fundamentals_messages: Annotated[list, add_messages]
    # ... rest unchanged
```

Then change each analyst factory to read/write its own field instead of
`messages`. Update tool nodes similarly. **Touches agent code**, so
upstream conflicts on every `git subtree pull`.

**Path B — sub-graphs** (~100 line patch confined to `setup.py` —
preferred)

Each analyst becomes a compiled sub-`StateGraph` whose own state schema
includes a local `messages` channel; the parent graph adds it as a node.
LangGraph isolates state at sub-graph boundaries: only `output_schema`
fields propagate back to the parent.

```python
def _build_analyst_subgraph(analyst_node, tool_node, msg_clear_node,
                            condition_fn, report_field: str):
    """Wrap an analyst into a compiled StateGraph with isolated messages.

    Schema: {messages, company_of_interest, trade_date, <report_field>}
    Parent passes the input fields, gets <report_field> back.
    Internal messages never escape.
    """
    sub = StateGraph(AnalystSubState)
    sub.add_node("analyst", analyst_node)
    sub.add_node("tools", tool_node)
    sub.add_node("clear", msg_clear_node)
    sub.add_edge(START, "analyst")
    sub.add_conditional_edges("analyst", condition_fn,
                              ["tools", "clear"])
    sub.add_edge("tools", "analyst")
    sub.add_edge("clear", END)
    return sub.compile()
```

Then in the parent:

```python
for analyst_type, node in analyst_nodes.items():
    sub = _build_analyst_subgraph(...)
    workflow.add_node(f"{cap(analyst_type)} Analyst", sub)
    workflow.add_edge(START, f"{cap(analyst_type)} Analyst")
    workflow.add_edge(f"{cap(analyst_type)} Analyst", "Analysts Done")

# barrier: waits for all parallel analysts to finish
workflow.add_node("Analysts Done", lambda s: {})
workflow.add_edge("Analysts Done", "Bull Researcher")
```

### Validation plan (when implemented)

1. Round-trip apply-patches.sh on a clean checkout
2. Run a LIVE decision twice:
   - Once with `cfg["parallel_analysts"]=True` (new path)
   - Once with `False` (current path)
3. Diff the resulting reports — they should be roughly equivalent in
   content (some variation expected from independent LLM calls)
4. Time both — parallel should be ~3× faster

---

## #10 · Structured analyst reports (Pydantic schemas)

**Status**: foundation laid (`tradingagents/agents/utils/report_schemas.py`),
not yet adopted by analyst factories.

### Why it matters

Analyst reports are currently free-form markdown. Limitations:

1. **Cross-decision queries impossible** — can't ask "show me all Buy
   ratings on stocks where market analyst flagged RSI > 70"
2. **Frontend rendering inconsistent** — different LLMs format differently
3. **Aggregation broken** — can't compute "average trend strength across
   30 NVDA decisions"
4. **Token waste** — boilerplate ("Here is my analysis...") repeats per call

### Structured outputs would unlock

```sql
-- Find stocks where the market analyst saw both extreme RSI AND
-- the news analyst flagged earnings beat in the last 30 days
SELECT d.ticker, d.rating, d.completed_at
FROM decisions d
WHERE d.run_state->'market_report'->>'rsi_zone' = 'overbought'
  AND d.run_state->'news_report'->'flags' @> '["earnings_beat"]'
  AND d.completed_at > now() - interval '30 days';
```

### Implementation

**Step 1 (this PR — done)**: define schemas in
`tradingagents/agents/utils/report_schemas.py`. They're not yet wired
into analyst factories — they're a contract definition for downstream
work.

**Step 2 (future PR)**: add `cfg["structured_reports"]` opt-in flag in
each analyst factory. When True, use `llm.with_structured_output(Schema)`
and emit both the Pydantic dict AND the rendered markdown:

```python
if get_config().get("structured_reports"):
    structured_chain = prompt | llm.with_structured_output(MarketReport)
    obj = structured_chain.invoke(state["messages"])
    report = obj.model_dump_json()    # store as JSON
    summary_md = obj.summary_md       # for the cockpit
else:
    # existing free-form path
    ...
```

**Step 3 (future PR)**: downstream consumers (Bull/Bear, Research Manager)
read structured fields when present.

**Step 4 (future PR)**: frontend renders structured reports with proper
charts/tables for `rsi_zone`, `macd_signal`, etc. instead of just
`mdLite()`.

### Validation plan

1. Schemas are Pydantic v2 — `model_validate(raw_dict)` succeeds for
   demo and live outputs
2. With flag off, behaviour unchanged
3. With flag on, `decisions.run_state.market_report` is a JSON object
   (not a string) — validate via Postgres JSON path
4. Decision quality maintained or improved (subjective check on 10
   real runs)

---

## Other deferred items

- **Nasdaq Data Link / JQData / RQData full integration** — Profile UI
  has key inputs; FMP module shipped in v9; these three remain stubs.
  Easy to add by mirroring `dataflows/finnhub_pro.py`.
- **Per-decision A/B comparison** — let users run NVDA with model X and
  model Y side-by-side to compare. Needs UI + a dual-window mode.
- **Opportunity scanner → independent worker** — currently in-process;
  scaling up needs a separate process / Fly machine.
- **Conditional analyst skipping by instrument type** — crypto runs
  don't really need a fundamentals analyst; saves 1 LLM round-trip.
  Easy frontend change once we add an instrument heuristic.
