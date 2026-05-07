-- =========================================================================
-- 0003 — pinned/rating on decisions + opportunity favorites + LLM key vault
-- Run after 0002. Idempotent.
-- =========================================================================

-- ---- decisions: pinned + manual rating ---------------------------------
alter table public.decisions
    add column if not exists pinned boolean not null default false;

alter table public.decisions
    add column if not exists user_rating int;             -- 0..5 (0 = unrated)

alter table public.decisions
    add column if not exists user_note text;

alter table public.decisions
    drop constraint if exists decisions_rating_chk;
alter table public.decisions
    add constraint decisions_rating_chk
        check (user_rating is null or (user_rating between 0 and 5));

-- pinned items first, then by created_at desc (frontend orders client-side
-- but an index helps when we eventually paginate)
create index if not exists decisions_user_pinned_created_idx
    on public.decisions (user_id, pinned desc, created_at desc);


-- ---- favorites: allow kind='opportunity' --------------------------------
alter table public.favorites
    drop constraint if exists favorites_kind_check;
alter table public.favorites
    add constraint favorites_kind_check
        check (kind in ('strategy', 'decision', 'opportunity'));


-- ---- decisions_summary: surface new fields ------------------------------
-- DROP first because CREATE OR REPLACE VIEW can only append columns, not
-- reorder/rename them — and schema.sql defines an earlier shape.
drop view if exists public.decisions_summary cascade;
create or replace view public.decisions_summary as
    select id, user_id, ticker, trade_date, rating, status,
           started_at, completed_at, created_at, updated_at,
           pinned, user_rating, user_note,
           jsonb_extract_path_text(params, 'llm_provider')   as llm_provider,
           jsonb_extract_path_text(params, 'deep_think_llm') as deep_think_llm,
           jsonb_extract_path_text(params, 'instrument_hint') as instrument_hint
    from public.decisions;

grant select on public.decisions_summary to authenticated;


-- ---- profiles: separate vaults for LLM vs data keys --------------------
-- We already have custom_api_keys (data sources). Add llm_api_keys for
-- LLM provider keys so they don't intermingle.
alter table public.profiles
    add column if not exists llm_api_keys jsonb not null default '{}'::jsonb;


-- ---- usage_counters (per-profile, light, JSONB rolled up) --------------
-- Stored on profiles.settings.usage; this comment is a reminder, no
-- schema change is necessary because settings is already JSONB.
--   profiles.settings = {
--     usage: {
--       last_reset: '2025-...',
--       llm_calls: { openai: 12, anthropic: 4, deepseek: 30, ... },
--       data_calls: { finnhub_pro: 88, polygon_io: 0, ... },
--       tokens_in: 0, tokens_out: 0
--     }
--   }
