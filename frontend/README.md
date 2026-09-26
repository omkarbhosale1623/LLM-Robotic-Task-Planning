# Frontend — LLM Robotic Task-Planning Agent

Next.js 14 (App Router) + TypeScript (strict) + TailwindCSS dashboard: a chat-style
instruction console, a status-aware plan visualiser (mini-DAG), a top-down SVG
tabletop scene that animates as the plan executes, an execution timeline, and a
benchmark dashboard (20-command suite, completion-rate gauge).

## Stack
- Next.js 14, React 18, TypeScript (strict)
- TailwindCSS, lucide-react
- @tanstack/react-query (REST), native WebSocket (`/ws/execution`)
- recharts

## Run
```bash
npm install
cp .env.local.example .env.local   # NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
npm run dev                         # http://localhost:3000
```
`npm run build` produces the standalone server used by the Dockerfile.

## Structure
```
src/
  app/        layout, dashboard page
  components/ InstructionConsole, PlanVisualiser, SceneVisualiser, ExecutionTimeline,
              BenchmarkDashboard, Providers, ui/
  hooks/      useExecutionSocket (WebSocket)
  lib/        typed api client, types, utils
```

## Configuration
| Var | Default | Purpose |
|-----|---------|---------|
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | Backend REST + WS base |
