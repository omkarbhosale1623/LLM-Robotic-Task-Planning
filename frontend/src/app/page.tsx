"use client";

import { useQuery } from "@tanstack/react-query";
import { Cpu, Boxes, Gauge, Workflow, AlertTriangle, LogOut } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/AuthProvider";
import { BenchmarkDashboard } from "@/components/BenchmarkDashboard";
import { ExecutionTimeline } from "@/components/ExecutionTimeline";
import {
  InstructionConsole,
  type ConsoleEntry,
} from "@/components/InstructionConsole";
import { LoginGate } from "@/components/LoginGate";
import { PlanVisualiser } from "@/components/PlanVisualiser";
import { SceneVisualiser } from "@/components/SceneVisualiser";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Toggle } from "@/components/ui/Toggle";
import { useExecutionSocket } from "@/hooks/useExecutionSocket";
import { api } from "@/lib/api";
import type { PlannerMode } from "@/lib/types";

const SUGGESTIONS = [
  "pick up the red block and place it on the shelf",
  "move the green ball to the bin",
  "put the blue block in the right zone",
  "stack the red block on the blue block",
];

let entryCounter = 0;
const nextId = () => `e${entryCounter++}`;

export default function HomePage() {
  return (
    <LoginGate>
      <Dashboard />
    </LoginGate>
  );
}

function Dashboard() {
  const { session, signOut } = useAuth();
  const [mode, setMode] = useState<PlannerMode>("heuristic");
  const [scene, setScene] = useState("default");
  const [tab, setTab] = useState<"workspace" | "benchmark">("workspace");
  const [history, setHistory] = useState<ConsoleEntry[]>([]);

  const { state, run } = useExecutionSocket();

  const capabilities = useQuery({
    queryKey: ["capabilities"],
    queryFn: api.capabilities,
  });

  const world = useQuery({
    queryKey: ["world"],
    queryFn: api.getWorld,
  });

  const llmAvailable = capabilities.data?.llm_available ?? false;
  const scenes = capabilities.data?.scenes ?? ["default", "stack", "sorting", "empty"];

  // Reset the world when the scene picker changes.
  const onSceneChange = useCallback(
    async (next: string) => {
      setScene(next);
      await api.resetWorld(next);
      world.refetch();
    },
    [world],
  );

  const submit = useCallback(
    (instruction: string) => {
      setHistory((h) => [...h, { id: nextId(), role: "user", text: instruction }]);
      run({ instruction, mode, reset_scene: scene });
    },
    [mode, scene, run],
  );

  // When a run finishes, append an agent summary to the console.
  useEffect(() => {
    if (!state.result) return;
    const ok = state.result.success;
    const planner = state.plannerUsed ?? "heuristic";
    setHistory((h) => {
      if (h.length && h[h.length - 1].role === "agent") return h;
      return [
        ...h,
        {
          id: nextId(),
          role: "agent",
          text: ok
            ? `Done — executed ${state.steps.length} primitives successfully.`
            : `Stopped: ${state.result?.message ?? "execution failed"}`,
          tone: ok ? "ok" : "bad",
          meta: `${planner} planner`,
        },
      ];
    });
  }, [state.result, state.plannerUsed, state.steps.length]);

  // The live world comes from the socket while running, else from the query.
  const liveWorld = state.world ?? world.data ?? null;
  const highlight = useMemo(() => {
    if (state.activeIndex < 0) return null;
    const step = state.plan?.steps[state.activeIndex];
    return (step?.args?.target as string) ?? null;
  }, [state.activeIndex, state.plan]);

  const modeOptions: { value: PlannerMode; label: string; disabled?: boolean }[] = [
    { value: "heuristic", label: "Heuristic" },
    { value: "llm", label: "LLM", disabled: !llmAvailable },
    { value: "auto", label: "Auto" },
  ];

  return (
    <main className="mx-auto max-w-7xl px-4 py-6">
      {/* Header */}
      <header className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-accent/15 text-accent">
            <Cpu className="h-6 w-6" />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-slate-100">
              LLM Robotic Task-Planning Agent
            </h1>
            <p className="text-xs text-slate-400">
              Natural language → validated primitive plan → simulated tabletop execution
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={llmAvailable ? "ok" : "neutral"}>
            <Cpu className="h-3 w-3" />
            {llmAvailable ? "LLM ready" : "Heuristic mode"}
          </Badge>
          {capabilities.data && (
            <Badge tone="accent">{capabilities.data.primitives.length} primitives</Badge>
          )}
          {session?.user?.email && (
            <span className="hidden text-xs text-slate-400 sm:inline">
              {session.user.email}
            </span>
          )}
          <Button variant="secondary" onClick={() => void signOut()}>
            <LogOut className="h-4 w-4" /> Sign out
          </Button>
        </div>
      </header>

      {/* Tabs */}
      <div className="mb-4 flex items-center gap-2">
        <Toggle
          options={[
            { value: "workspace", label: "Workspace" },
            { value: "benchmark", label: "Benchmark" },
          ]}
          value={tab}
          onChange={(v) => setTab(v as typeof tab)}
        />
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <span className="text-xs text-slate-500">Planner</span>
          <Toggle options={modeOptions} value={mode} onChange={setMode} />
          <span className="ml-2 text-xs text-slate-500">Scene</span>
          <Toggle
            options={scenes.map((s) => ({ value: s, label: s }))}
            value={scene}
            onChange={onSceneChange}
          />
        </div>
      </div>

      {/* LLM-unavailable note when LLM mode is requested but unavailable */}
      {mode === "llm" && !llmAvailable && (
        <div className="mb-4 flex items-start gap-2 rounded-lg border border-warn/40 bg-warn/5 px-3 py-2 text-sm text-warn">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{capabilities.data?.llm_note ?? "LLM planner unavailable; the heuristic planner will be used instead."}</span>
        </div>
      )}

      {tab === "benchmark" ? (
        <BenchmarkDashboard mode={mode} />
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
          {/* Left: instruction console */}
          <div className="lg:col-span-4">
            <Card
              title="Instruction console"
              subtitle="Chat with the robot. Enter to run, Shift+Enter for newline."
              className="h-[560px]"
              bodyClassName="h-[calc(560px-3.25rem)]"
            >
              <InstructionConsole
                history={history}
                onSubmit={submit}
                disabled={state.running}
                suggestions={SUGGESTIONS}
              />
            </Card>
          </div>

          {/* Middle: scene + timeline */}
          <div className="space-y-4 lg:col-span-5">
            <Card
              title={
                <span className="flex items-center gap-2">
                  <Boxes className="h-4 w-4" /> Tabletop scene
                </span>
              }
              subtitle={`Scene: ${liveWorld?.scene_name ?? scene}`}
              actions={
                state.running ? (
                  <Badge tone="accent">running</Badge>
                ) : state.result ? (
                  <Badge tone={state.result.success ? "ok" : "bad"}>
                    {state.result.success ? "success" : "failed"}
                  </Badge>
                ) : null
              }
            >
              <SceneVisualiser world={liveWorld} highlightId={highlight} />
            </Card>

            <Card
              title={
                <span className="flex items-center gap-2">
                  <Gauge className="h-4 w-4" /> Execution timeline
                </span>
              }
            >
              <ExecutionTimeline events={state.steps} activeIndex={state.activeIndex} />
              {state.error && (
                <p className="mt-2 text-sm text-bad">Error: {state.error}</p>
              )}
            </Card>
          </div>

          {/* Right: plan visualiser */}
          <div className="lg:col-span-3">
            <Card
              title={
                <span className="flex items-center gap-2">
                  <Workflow className="h-4 w-4" /> Plan
                </span>
              }
              subtitle={
                state.plan
                  ? `${state.plannerUsed ?? "heuristic"} · ${state.plan.steps.length} steps${
                      state.validation && !state.validation.valid ? " · invalid" : ""
                    }`
                  : "decomposed action sequence"
              }
              className="h-[560px]"
              bodyClassName="h-[calc(560px-3.25rem)] overflow-y-auto"
            >
              {state.plan?.notes && state.plan.notes.length > 0 && (
                <div className="mb-3 rounded-lg border border-warn/30 bg-warn/5 px-3 py-2 text-xs text-warn">
                  {state.plan.notes.join(" ")}
                </div>
              )}
              <PlanVisualiser
                plan={state.plan}
                events={state.steps}
                activeIndex={state.activeIndex}
              />
            </Card>
          </div>
        </div>
      )}

      <footer className="mt-8 border-t border-line pt-4 text-center text-xs text-slate-500">
        Heuristic + optional LLM planner · STRIPS-style validation · WebSocket-streamed execution
        {capabilities.data && <> · {capabilities.data.scenes.length} scenes</>}.
      </footer>
    </main>
  );
}
