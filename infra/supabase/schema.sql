-- ===========================================================================
-- Supabase schema for the LLM Robotic Task-Planning Agent.
--
-- Idempotent and Supabase-native. Apply via the Supabase SQL editor or
-- `supabase db push`. Enables pgvector for plan-memory few-shot retrieval and
-- Row-Level-Security so each user can only read/write their own rows. The
-- backend additionally scopes every query by user_id, so isolation is enforced
-- at both the application and the database layer.
-- ===========================================================================

-- pgvector: required for the plan_memory similarity search (vector(384)).
create extension if not exists vector;

-- ---------------------------------------------------------------------------
-- sessions: one per (user, planning session). Each holds the user's live world
-- config; live in-process world objects are per-instance, this is the durable
-- record so any backend instance can read a user's session history.
-- ---------------------------------------------------------------------------
create table if not exists public.sessions (
    id          uuid primary key default gen_random_uuid(),
    user_id     text not null,
    project     text not null default 'llm-robotic-task-planning',
    config      jsonb not null default '{}'::jsonb,
    status      text not null default 'active',
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);
create index if not exists sessions_user_id_idx on public.sessions (user_id);

-- ---------------------------------------------------------------------------
-- runs: one row per plan / execute / plan-and-run / benchmark invocation, with
-- result metrics (incl. benchmark success_rate). Lets the UI show run history.
-- ---------------------------------------------------------------------------
create table if not exists public.runs (
    id          uuid primary key default gen_random_uuid(),
    session_id  uuid not null references public.sessions (id) on delete cascade,
    user_id     text not null,
    kind        text not null,                       -- plan | execute | plan-and-run | benchmark | ws-execute
    params      jsonb not null default '{}'::jsonb,
    metrics     jsonb not null default '{}'::jsonb,  -- e.g. {"success_rate": 0.9, "passed": 18}
    created_at  timestamptz not null default now()
);
create index if not exists runs_user_id_idx on public.runs (user_id);
create index if not exists runs_session_id_idx on public.runs (session_id);

-- ---------------------------------------------------------------------------
-- plan_memory: successful (instruction -> plan) pairs with a 384-dim embedding.
-- The backend retrieves the top-k most-similar prior plans for the user and
-- injects them as few-shot context into the LLM prompt.
-- ---------------------------------------------------------------------------
create table if not exists public.plan_memory (
    id          uuid primary key default gen_random_uuid(),
    user_id     text not null,
    instruction text not null,
    plan        jsonb not null,
    embedding   vector(384),
    created_at  timestamptz not null default now()
);
create index if not exists plan_memory_user_id_idx on public.plan_memory (user_id);
-- Approximate-nearest-neighbour index for cosine distance (<=>) on the embedding.
-- ivfflat needs ANALYZE/rows to be effective; safe to create up front.
create index if not exists plan_memory_embedding_idx
    on public.plan_memory using ivfflat (embedding vector_cosine_ops) with (lists = 100);

-- ===========================================================================
-- Row-Level Security: per-user isolation enforced by Supabase.
-- auth.uid() is the authenticated user's UUID; we compare it (as text) to the
-- user_id column the backend writes from the JWT `sub` claim.
-- ===========================================================================
alter table public.sessions     enable row level security;
alter table public.runs         enable row level security;
alter table public.plan_memory  enable row level security;

-- sessions policies -----------------------------------------------------------
drop policy if exists sessions_select on public.sessions;
create policy sessions_select on public.sessions for select
    using (auth.uid()::text = user_id);
drop policy if exists sessions_insert on public.sessions;
create policy sessions_insert on public.sessions for insert
    with check (auth.uid()::text = user_id);
drop policy if exists sessions_update on public.sessions;
create policy sessions_update on public.sessions for update
    using (auth.uid()::text = user_id) with check (auth.uid()::text = user_id);
drop policy if exists sessions_delete on public.sessions;
create policy sessions_delete on public.sessions for delete
    using (auth.uid()::text = user_id);

-- runs policies ---------------------------------------------------------------
drop policy if exists runs_select on public.runs;
create policy runs_select on public.runs for select
    using (auth.uid()::text = user_id);
drop policy if exists runs_insert on public.runs;
create policy runs_insert on public.runs for insert
    with check (auth.uid()::text = user_id);
drop policy if exists runs_update on public.runs;
create policy runs_update on public.runs for update
    using (auth.uid()::text = user_id) with check (auth.uid()::text = user_id);
drop policy if exists runs_delete on public.runs;
create policy runs_delete on public.runs for delete
    using (auth.uid()::text = user_id);

-- plan_memory policies --------------------------------------------------------
drop policy if exists plan_memory_select on public.plan_memory;
create policy plan_memory_select on public.plan_memory for select
    using (auth.uid()::text = user_id);
drop policy if exists plan_memory_insert on public.plan_memory;
create policy plan_memory_insert on public.plan_memory for insert
    with check (auth.uid()::text = user_id);
drop policy if exists plan_memory_update on public.plan_memory;
create policy plan_memory_update on public.plan_memory for update
    using (auth.uid()::text = user_id) with check (auth.uid()::text = user_id);
drop policy if exists plan_memory_delete on public.plan_memory;
create policy plan_memory_delete on public.plan_memory for delete
    using (auth.uid()::text = user_id);

-- ===========================================================================
-- NOTE on the service role: the backend connects with the service-role
-- credentials (DATABASE_URL / SUPABASE_SERVICE_ROLE_KEY), which BYPASS RLS. The
-- application still scopes every query by user_id, so isolation holds. RLS is
-- the defence-in-depth layer for any direct (anon-key) access from clients.
-- ===========================================================================
