-- 0006 — Watchlist + custom groups.
--
-- One row per (user, ticker). The 'market' column is auto-detected on insert
-- by the frontend and used for built-in grouping (us / hk / cn / crypto /
-- commodity / forex / other). 'custom_group' is a free-form user-defined
-- group label; null → "ungrouped".

create table if not exists public.watchlist (
    id            uuid primary key default gen_random_uuid(),
    user_id       uuid not null references auth.users(id) on delete cascade,
    ticker        text not null,
    display_name  text,           -- short label like 比亚迪 / Tesla
    market        text,           -- us | hk | cn | crypto | commodity | forex | other
    custom_group  text,           -- user's group name (optional)
    sort_order    int  default 0, -- drag-to-reorder
    note          text,
    added_at      timestamptz default now(),
    unique (user_id, ticker)
);

alter table public.watchlist enable row level security;

create policy "watchlist owner read"   on public.watchlist for select using (auth.uid() = user_id);
create policy "watchlist owner insert" on public.watchlist for insert with check (auth.uid() = user_id);
create policy "watchlist owner update" on public.watchlist for update using (auth.uid() = user_id);
create policy "watchlist owner delete" on public.watchlist for delete using (auth.uid() = user_id);

create index if not exists watchlist_user_idx on public.watchlist(user_id);
create index if not exists watchlist_ticker_idx on public.watchlist(user_id, ticker);
