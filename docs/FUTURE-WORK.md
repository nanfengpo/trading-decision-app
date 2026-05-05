# Future work — known optimizations not yet applied

## Parallel analyst execution (was Phase B.1)

**Status**: deferred — needs structural change to `AgentState`.

### The problem

All 4 analysts share `AgentState.messages`. Inside each analyst's tool loop, the
chat history alternates between AIMessage (with `tool_calls`) and ToolMessage
(with results). If we ran 4 analysts concurrently the way `setup.py` is currently
written (`workflow.add_edge(START, each_analyst)`), their tool-call/result pairs
would interleave on the same channel and the LLMs would lose track of which
result belongs to which call.

### Two paths forward

**Path A — namespaced messages (smallest patch)**

Add per-analyst message channels to `AgentState`:

```python
class AgentState(MessagesState):
    market_messages: Annotated[list, add_messages]
    social_messages: Annotated[list, add_messages]
    news_messages:   Annotated[list, add_messages]
    fundamentals_messages: Annotated[list, add_messages]
    # … rest unchanged
```

Then change each analyst factory to read/write its own field instead of
`messages`. Update `tool_nodes` similarly. Roughly 40-line patch across 5 files
in TradingAgents — but it touches *agent code*, not just orchestration, so it
collides with our "改插座，不改电路" rule.

**Path B — sub-graphs (cleaner conceptually)**

Each analyst becomes a compiled `StateGraph` whose own state schema includes a
local `messages` channel; the parent graph adds it as a node. LangGraph
isolates state at subgraph boundaries.

Roughly 100-line patch confined to `setup.py` (no analyst-code changes).

### Expected gain

Wall-clock per LIVE decision today (`research_depth=1`):
- 4 analysts sequential, each ~25 s → ~100 s
- Bull/Bear debate ~30 s
- Risk 3-way ~30 s
- Trader + PM ~20 s
- **Total: ~3 min**

With parallel analysts:
- 4 analysts concurrent ≈ slowest (~30 s)
- Rest unchanged → ~90 s
- **Total: ~1.5 min**, ≈ 50 % reduction

Wall-clock dominates user perception more than token cost, so this is high-impact
when scheduled.

### Why not now

- Modifying `AgentState` collides with upstream changes in `agents/` files —
  every `git subtree pull` would risk a conflict at the schema level
- Path B (sub-graphs) is cleaner but still needs careful testing of the
  message-clear semantics across the boundary
- B.2 (cache) + B.3 (token tracking) already give meaningful wins on rerun
  scenarios and observability — recommend shipping those first, then
  tackling B.1 in its own focused PR
