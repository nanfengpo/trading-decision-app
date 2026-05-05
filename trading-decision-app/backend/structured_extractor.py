"""
Structured-report extractor.

Takes free-form markdown reports from each of the 4 analysts and runs them
through ``llm.with_structured_output(Schema)`` to produce typed Pydantic
objects. The schemas are the ones defined in
``tradingagents/agents/utils/report_schemas.py`` (foundation file from v9).

Why post-graph instead of in-analyst?
-------------------------------------
We can't add fields to ``AgentState`` without breaking upstream subtree
sync. Doing the extraction AFTER the graph completes:

  - Costs only one extra LLM call per analyst (cheap — quick model OK)
  - Doesn't touch agent code or graph state schema
  - Keeps existing markdown flow untouched (Bull/Bear etc. still consume
    markdown reports)
  - Produces a separate structured payload that lands in
    ``decisions.run_state.structured_reports`` for SQL-style queries

Activation
----------
``cfg["structured_reports"] = True`` (or env
``TRADINGAGENTS_STRUCTURED_REPORTS=1``). Default is False — extraction
is skipped and ``run_state.structured_reports`` stays empty.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# Map from AgentState's report-field names to Pydantic schema names
_FIELD_TO_SCHEMA = {
    "market_report":       "MarketReport",
    "sentiment_report":    "SentimentReport",
    "news_report":         "NewsReport",
    "fundamentals_report": "FundamentalsReport",
}


def _load_schemas():
    """Return the dict of schema name → Pydantic class. None on failure."""
    try:
        from tradingagents.agents.utils.report_schemas import ALL_SCHEMAS  # type: ignore
        return ALL_SCHEMAS
    except Exception as e:
        logger.debug("report_schemas not importable: %s", e)
        return None


def extract_all(final_state: Dict[str, Any], llm: Any) -> Dict[str, Any]:
    """Extract structured reports for every analyst that produced output.

    Args:
        final_state:  the dict returned by ``graph.graph.stream()``'s last
                      chunk — should contain ``market_report`` etc.
        llm:          a langchain LLM instance with ``with_structured_output``.

    Returns:
        ``{"market_report": {...}, "sentiment_report": {...}, ...}``
        Keys missing when the corresponding markdown report is empty or
        the extraction failed (we never raise — extraction is best-effort).
    """
    schemas = _load_schemas()
    if not schemas or llm is None:
        return {}

    out: Dict[str, Any] = {}
    for field, schema_name in _FIELD_TO_SCHEMA.items():
        markdown = (final_state.get(field) or "").strip()
        if not markdown:
            continue
        Schema = schemas.get(field)
        if Schema is None:
            continue

        try:
            structured_llm = llm.with_structured_output(Schema)
            obj = structured_llm.invoke(
                "Extract the structured fields from this analyst report. "
                "Use the schema's field descriptions for guidance. If a field "
                "isn't mentioned in the text, leave it as the schema default. "
                "Always populate `summary_md` with a one-paragraph synthesis "
                "of the key points.\n\n----\n\n"
                + markdown[:6000]   # cap to keep cost predictable
            )
            # Convert pydantic model → dict; works for both v1 + v2
            if hasattr(obj, "model_dump"):
                out[field] = obj.model_dump()
            elif hasattr(obj, "dict"):
                out[field] = obj.dict()  # pydantic v1 fallback
            else:
                logger.warning("structured output for %s was not a pydantic model", field)
        except Exception as e:
            logger.warning("structured extraction for %s failed: %s", field, e)
            continue

    return out
