// Typed contract mirroring the FastAPI backend's response models.

export type PlannerMode = "heuristic" | "llm" | "auto";

export interface Vec2 {
  x: number;
  y: number;
}

export interface WorldObject {
  id: string;
  color: string;
  shape: string;
  position: Vec2;
  on_top_of: string | null;
  inside: string | null;
  size: number;
}

export type LocationKind = "surface" | "container" | "zone";

export interface WorldLocation {
  id: string;
  name: string;
  kind: LocationKind;
  anchor: Vec2;
  width: number;
  height: number;
}

export interface RobotState {
  pose: Vec2;
  gripper_open: boolean;
  holding: string | null;
}

export interface WorldState {
  scene_name: string;
  objects: WorldObject[];
  locations: WorldLocation[];
  robot: RobotState;
}

export interface PlanStep {
  action: string;
  args: Record<string, unknown>;
  rationale: string;
}

export interface Plan {
  instruction: string;
  planner: string;
  steps: PlanStep[];
  notes: string[];
}

export interface Validation {
  valid: boolean;
  errors: string[];
  grounded_targets: string[];
}

export interface PlanResponse {
  plan: Plan;
  validation: Validation;
  planner_used: string;
  requested_mode: string;
  llm_available: boolean;
  notes: string[];
}

export interface StepEvent {
  index: number;
  action: string;
  args: Record<string, unknown>;
  rationale: string;
  success: boolean;
  reason: string;
  pre_state: WorldState;
  post_state: WorldState;
}

export interface ExecutionResponse {
  success: boolean;
  steps_total: number;
  steps_executed: number;
  steps_succeeded: number;
  events: StepEvent[];
  final_state: WorldState | null;
  message: string;
}

export interface PlanAndRunResponse {
  plan: Plan;
  validation: Validation;
  planner_used: string;
  llm_available: boolean;
  notes: string[];
  execution: ExecutionResponse | null;
}

export interface BenchmarkCommandResult {
  id: number;
  instruction: string;
  scene: string;
  description: string;
  planner_used: string;
  plan_valid: boolean;
  executed_ok: boolean;
  outcome_ok: boolean;
  passed: boolean;
  detail: string;
  step_count: number;
  notes: string[];
}

export interface BenchmarkReport {
  total: number;
  passed: number;
  completion_rate: number;
  mode: string;
  results: BenchmarkCommandResult[];
}

export interface PrimitiveSpec {
  name: string;
  args: string[];
  description: string;
}

export interface BenchmarkCommandSpec {
  id: number;
  instruction: string;
  scene: string;
  description: string;
}

export interface Capabilities {
  primitives: PrimitiveSpec[];
  scenes: string[];
  benchmark_commands: BenchmarkCommandSpec[];
  planner_modes: PlannerMode[];
  llm_available: boolean;
  llm_note: string;
}

export interface HealthResponse {
  status: string;
  app: string;
  version: string;
  llm_available: boolean;
  llm_note: string;
}

// WebSocket message envelope (from /ws/execution).
export type WsMessage =
  | {
      type: "plan";
      plan: Plan;
      validation?: Validation;
      planner_used: string;
      llm_available?: boolean;
      notes: string[];
    }
  | { type: "world"; state: WorldState }
  | ({ type: "step" } & StepEvent)
  | {
      type: "result";
      success: boolean;
      steps_total?: number;
      steps_executed?: number;
      steps_succeeded?: number;
      final_state?: WorldState;
      message: string;
    }
  | { type: "error"; message: string };
