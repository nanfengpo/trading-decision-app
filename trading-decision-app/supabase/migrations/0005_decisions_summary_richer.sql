-- 0005 — Expose more filterable fields on decisions_summary so the UI can
-- filter by LLM provider / deep model / quick model / research depth / mode
-- / output language without re-fetching the full row.

drop view if exists public.decisions_summary cascade;

create or replace view public.decisions_summary as
    select
        id, user_id, ticker, trade_date, rating, status,
        started_at, completed_at, created_at, updated_at,
        pinned, user_rating, user_note,
        -- denormalised JSONB extractions (text — easy to filter on)
        jsonb_extract_path_text(params, 'llm_provider')     as llm_provider,
        jsonb_extract_path_text(params, 'deep_think_llm')   as deep_think_llm,
        jsonb_extract_path_text(params, 'quick_think_llm')  as quick_think_llm,
        jsonb_extract_path_text(params, 'instrument_hint')  as instrument_hint,
        jsonb_extract_path_text(params, 'mode')             as mode,
        jsonb_extract_path_text(params, 'output_language')  as output_language,
        coalesce(
            nullif(jsonb_extract_path_text(params, 'research_depth'), '')::int,
            null
        ) as research_depth,
        -- full params blob too (frontend convenience for future filters)
        params
    from public.decisions;

grant select on public.decisions_summary to authenticated;
