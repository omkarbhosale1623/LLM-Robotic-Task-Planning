# Supabase setup — auth, Postgres persistence & pgvector plan memory

The backend uses Supabase for **authentication** (HS256 JWTs verified by the
backend with the Python standard library — no `pyjwt` needed) and, optionally,
for **persistence** (sessions, runs, and pgvector plan memory). With no Supabase
configured the app still boots and runs entirely on the in-memory repository, and
auth can be relaxed for local development via `AUTH_REQUIRED=false`.

## 1. Create a Supabase project

1. Go to <https://supabase.com>, create a project, and wait for it to provision.
2. **Project Settings → API** gives you:
   - **Project URL** → `SUPABASE_URL` (e.g. `https://abcd.supabase.co`)
   - **anon public** key → `SUPABASE_ANON_KEY` (and frontend `NEXT_PUBLIC_SUPABASE_ANON_KEY`)
   - **service_role** key → `SUPABASE_SERVICE_ROLE_KEY` (server-only; never ship to the browser)
3. **Project Settings → API → JWT Settings** gives you the **JWT Secret** →
   `SUPABASE_JWT_SECRET`. This is the HS256 secret the backend uses to verify
   user tokens. (If your project is configured for asymmetric keys, see the
   extension point in `backend/app/core/auth.py`.)
4. **Project Settings → Database → Connection string** gives you the Postgres DSN.
   Use the SQLAlchemy async form for `DATABASE_URL`:
   `postgresql+asyncpg://postgres:[PASSWORD]@db.YOUR-PROJECT.supabase.co:5432/postgres`

## 2. Apply the schema (`schema.sql`)

The schema is idempotent. Apply it either way:

- **SQL editor:** open `infra/supabase/schema.sql`, paste into the Supabase SQL
  editor, and run it.
- **CLI:** `supabase db push` (or `psql "$DATABASE_URL" -f infra/supabase/schema.sql`).

It will:

- `create extension if not exists vector;` (pgvector — required for plan memory).
- Create `sessions`, `runs`, and `plan_memory(... embedding vector(384) ...)`.
- **Enable Row-Level Security** on all three tables with
  `using (auth.uid()::text = user_id)` policies for select/insert/update/delete,
  so Supabase enforces per-user isolation at the database.

## 3. Configure the backend

Copy `backend/.env.example` → `backend/.env` and fill in:

```
SUPABASE_URL=https://YOUR-PROJECT.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SUPABASE_JWT_SECRET=your-jwt-secret-from-supabase-dashboard
DATABASE_URL=postgresql+asyncpg://postgres:[PASSWORD]@db.YOUR-PROJECT.supabase.co:5432/postgres
AUTH_REQUIRED=true
PERSISTENCE_BACKEND=auto      # auto | supabase | memory
```

- `PERSISTENCE_BACKEND=auto` uses Postgres when `DATABASE_URL` is set **and**
  SQLAlchemy + asyncpg import successfully; otherwise it logs a warning and falls
  back to the in-memory repository.

## 4. Create a user / get a token

The frontend ships a Supabase email/password login gate. For manual API testing,
get an access token via the Supabase JS client or the Auth REST API
(`POST {SUPABASE_URL}/auth/v1/token?grant_type=password`) and send it as
`Authorization: Bearer <access_token>` on `/api/v1/**` and as `?token=<access_token>`
on the `/ws/**` WebSocket.

## Scaling model (read this)

- **Persistence is shared via Postgres.** Sessions, runs, and benchmark results
  (including success rate) live in Supabase, so *any* backend instance can read a
  user's history. This part scales horizontally behind a load balancer.
- **Live in-process session state is per-instance.** Each running plan keeps its
  evolving `WorldModel` + `Executor` in the `SessionRegistry` of one process. For
  a heavy live session, use **sticky routing** (route a session_id to the same
  instance) or run a single instance per heavy session. A different instance can
  still read the persisted session/run records, but it starts that session's live
  world fresh from the stored scene config.
- **RLS vs service role.** The backend connects with the service role, which
  bypasses RLS; the application scopes every query by `user_id`. RLS is the
  defence-in-depth layer for any direct anon-key client access.

## pgvector notes

- The `plan_memory.embedding` column is `vector(384)` to match the default
  `EMBEDDING_DIM=384` (the `all-MiniLM-L6-v2` sentence-transformers model). If you
  change `EMBEDDING_MODEL`/`EMBEDDING_DIM`, change the column dimension to match.
- If `sentence-transformers` is unavailable, the backend uses a deterministic
  stdlib hashing embedder (still 384-dim by default) — plan memory keeps working
  with no model download.
- If the `vector` extension cannot be enabled (e.g. a non-Supabase Postgres
  without pgvector), the backend degrades the column to `jsonb` and ranks
  similarity in Python. Plan memory is always optional and non-blocking.
