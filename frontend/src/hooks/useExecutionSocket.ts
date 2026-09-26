"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { wsUrl } from "@/lib/api";
import type { Plan, StepEvent, Validation, WorldState, WsMessage } from "@/lib/types";

export type ConnectionStatus = "idle" | "connecting" | "open" | "closed" | "error";

export interface ExecutionRequest {
  instruction?: string;
  plan?: Plan["steps"];
  mode?: string;
  reset_scene?: string;
}

export interface ExecutionStreamState {
  status: ConnectionStatus;
  running: boolean;
  plan: Plan | null;
  validation: Validation | null;
  plannerUsed: string | null;
  notes: string[];
  world: WorldState | null;
  steps: StepEvent[];
  activeIndex: number; // index of the step currently animating, -1 when none
  result: {
    success: boolean;
    message: string;
    final_state?: WorldState;
  } | null;
  error: string | null;
}

const INITIAL: ExecutionStreamState = {
  status: "idle",
  running: false,
  plan: null,
  validation: null,
  plannerUsed: null,
  notes: [],
  world: null,
  steps: [],
  activeIndex: -1,
  result: null,
  error: null,
};

/**
 * Streams plan execution events from the backend's /ws/execution endpoint.
 *
 * The hook opens a fresh WebSocket per `run()` call so the scene visualiser and
 * timeline animate live as each primitive is applied server-side.
 */
export function useExecutionSocket() {
  const [state, setState] = useState<ExecutionStreamState>(INITIAL);
  const socketRef = useRef<WebSocket | null>(null);

  const cleanup = useCallback(() => {
    if (socketRef.current) {
      socketRef.current.onmessage = null;
      socketRef.current.onerror = null;
      socketRef.current.onclose = null;
      socketRef.current.close();
      socketRef.current = null;
    }
  }, []);

  useEffect(() => cleanup, [cleanup]);

  const run = useCallback(
    (req: ExecutionRequest) => {
      cleanup();
      setState({ ...INITIAL, status: "connecting", running: true });

      const ws = new WebSocket(wsUrl("/ws/execution"));
      socketRef.current = ws;

      ws.onopen = () => {
        setState((s) => ({ ...s, status: "open" }));
        ws.send(JSON.stringify(req));
      };

      ws.onmessage = (event) => {
        let msg: WsMessage;
        try {
          msg = JSON.parse(event.data) as WsMessage;
        } catch {
          return;
        }
        setState((s) => reduce(s, msg));
      };

      ws.onerror = () => {
        setState((s) => ({ ...s, status: "error", running: false, error: "WebSocket error" }));
      };

      ws.onclose = () => {
        setState((s) => ({
          ...s,
          status: s.status === "error" ? "error" : "closed",
          running: false,
          activeIndex: -1,
        }));
      };
    },
    [cleanup],
  );

  const reset = useCallback(() => {
    cleanup();
    setState(INITIAL);
  }, [cleanup]);

  return { state, run, reset };
}

function reduce(state: ExecutionStreamState, msg: WsMessage): ExecutionStreamState {
  switch (msg.type) {
    case "plan":
      return {
        ...state,
        plan: msg.plan,
        validation: msg.validation ?? null,
        plannerUsed: msg.planner_used,
        notes: msg.notes ?? [],
      };
    case "world":
      return { ...state, world: msg.state };
    case "step": {
      const event: StepEvent = {
        index: msg.index,
        action: msg.action,
        args: msg.args,
        rationale: msg.rationale,
        success: msg.success,
        reason: msg.reason,
        pre_state: msg.pre_state,
        post_state: msg.post_state,
      };
      return {
        ...state,
        steps: [...state.steps, event],
        world: event.post_state,
        activeIndex: event.index,
      };
    }
    case "result":
      return {
        ...state,
        running: false,
        activeIndex: -1,
        world: msg.final_state ?? state.world,
        result: {
          success: msg.success,
          message: msg.message,
          final_state: msg.final_state,
        },
      };
    case "error":
      return { ...state, running: false, error: msg.message, activeIndex: -1 };
    default:
      return state;
  }
}
