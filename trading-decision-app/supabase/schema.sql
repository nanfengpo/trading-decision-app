-- =========================================================================
-- Trading Decision App — Supabase schema
-- Run this in the Supabase SQL Editor (or via `supabase db push`).
-- Idempotent: safe to re-run.
-- =========================================================================

-- ---- profiles -----------------------------------------------------------
-- One row per auth.users user; populated automatically via trigger so the
-- frontend can store user-facing settings (display name, theme, …) without
-- touching the auth schema directly.

create table if not exists public.profiles (
    id              uuid primary key references auth.users(id) on delete cascade,
    display_name    text,
    theme           text default 'light',         -- 'light' | 'dark'
    default_provider text,
    default_deep_llm  text,
    default_quick_llm text,
    created_at      timestamptz default now(),
    updated_at      timestamptz default now()
);

alter table public.profiles enable row level security;

drop policy if exists "profiles_select_own" on public.profiles;
create policy "profiles_select_own"
    on public.profiles for select
    using (auth.uid() = id);

drop policy if exists "profiles_insert_own" on public.profiles;
create policy "profiles_insert_own"
    on public.profiles for insert
    with check (auth.uid() = id);

drop policy if exists "profiles_update_own" on public.profiles;
create policy "profiles_update_own"
    on public.profiles for update
    using (auth.uid() = id);

-- Auto-create a profile row on signup
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into public.profiles (id, display_name)
    values (new.id, coalesce(new.raw_user_meta_data->>'display_name', split_part(new.email, '@', 1)));
    return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
    after insert on auth.users
    for each row execute function public.handle_new_user();


-- ---- decisions ----------------------------------------------------------
-- One row per analysis run. Stored as JSONB so we don't lock ourselves into
-- a fixed schema as the agent runner evolves. RLS guarantees a user can
-- only see / mutate their own rows.

create table if not exists public.decisions (
    id           text primary key,                 -- frontend-generated window id
    user_id      uuid not null references auth.users(id) on delete cascade,
    ticker       text not null,
    trade_date   date not null,
    rating       text,                              -- Buy/Overweight/Hold/Underweight/Sell
    status       text not null default 'running',  -- running | done | error | restored
    started_at   timestamptz default now(),
    completed_at timestamptz,
    params       jsonb not null default '{}'::jsonb,
    run_state    jsonb not null default '{}'::jsonb,
    created_at   timestamptz default now(),
    updated_at   timestamptz default now()
);

create index if not exists decisions_user_created_idx
    on public.decisions (user_id, created_at desc);
create index if not exists decisions_user_ticker_idx
    on public.decisions (user_id, ticker);

alter table public.decisions enable row level security;

drop policy if exists "decisions_select_own" on public.decisions;
create policy "decisions_select_own"
    on public.decisions for select
    using (auth.uid() = user_id);

drop policy if exists "decisions_insert_own" on public.decisions;
create policy "decisions_insert_own"
    on public.decisions for insert
    with check (auth.uid() = user_id);

drop policy if exists "decisions_update_own" on public.decisions;
create policy "decisions_update_own"
    on public.decisions for update
    using (auth.uid() = user_id);

drop policy if exists "decisions_delete_own" on public.decisions;
create policy "decisions_delete_own"
    on public.decisions for delete
    using (auth.uid() = user_id);

-- updated_at maintenance
create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists decisions_touch_updated_at on public.decisions;
create trigger decisions_touch_updated_at
    before update on public.decisions
    for each row execute function public.touch_updated_at();


-- ---- helpful view: decisions summary (history sidebar) ------------------
-- The frontend list view doesn't need run_state (heavy). Selecting only
-- the lightweight columns keeps initial loads fast.
create or replace view public.decisions_summary as
    select id, user_id, ticker, trade_date, rating, status,
           started_at, completed_at, created_at, updated_at,
           jsonb_extract_path_text(params, 'llm_provider') as llm_provider,
           jsonb_extract_path_text(params, 'deep_think_llm') as deep_think_llm
    from public.decisions;

-- The view inherits RLS from the underlying table.
grant select on public.decisions_summary to authenticated;
