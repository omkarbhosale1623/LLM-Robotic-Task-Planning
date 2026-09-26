"""Optional LLM-backed planner (real brain).

This planner prompts a real LLM to decompose a natural-language instruction into
a structured JSON list of primitive actions, then validates the result against
the primitive schema and the world (via :func:`app.domain.planner.validate_plan`).

Backends, all gated behind feature flags so the application *always boots* with
only the base dependencies:

* ``mistral`` — **default**. Mistral Chat Completions via the official
  ``mistralai`` SDK when installed, else a direct REST call to
  ``{mistral_base_url}/chat/completions``. Uses ``response_format={"type":
  "json_object"}`` for structured output. Model :data:`Settings.mistral_model`
  (default ``mistral-large-latest``).
* ``anthropic`` — alternative. Anthropic Claude via the official ``anthropic``
  SDK. Model :data:`Settings.anthropic_model` (default ``claude-opus-4-8``) with
  adaptive thinking and ``output_config`` JSON-schema structured output.

If the configured backend is unavailable — no key, SDK/HTTP not installed, or an
API error — :meth:`LLMPlanner.plan` raises :class:`LLMUnavailable`, and the
caller falls back to the deterministic :class:`~app.domain.planner.HeuristicPlanner`
with a truthful note.

All optional imports (``mistralai``, ``anthropic``, ``httpx``) are deferred to
call time and guarded, so importing this module never fails.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.core.logging import get_logger
from app.domain import primitives
from app.domain.planner import Plan, PlanStep, validate_plan
from app.domain.world_model import WorldModel

logger = get_logger(__name__)


class LLMUnavailable(Exception):
    """Raised when the configured LLM backend cannot produce a valid plan."""


@dataclass
class FewShotExample:
    """A prior (instruction -> plan) pair retrieved from plan memory."""

    instruction: str
    plan: dict[str, Any]


SYSTEM_PROMPT = """You are the planning module of a tabletop robot. You convert a \
natural-language instruction into an ordered list of primitive robot actions that \
a STRIPS-style executor can run.

Available primitives (use these names exactly):
{primitive_block}

Rules:
- Output ONLY a JSON object: {{"steps": [{{"action": "...", "args": {{...}}, \
"rationale": "..."}}]}}.
- "target" must be the exact id of an object or location from the world state.
- Respect preconditions: move_to a target before pick/place; the gripper must be \
empty and open before picking; to place, the robot must be holding an object and \
be at the destination; clear any object stacked on a target before grasping it.
- For "pick up X and place on Y": move_to X, pick X, move_to Y, place Y.
- Do not invent object or location ids that are not in the world state.
"""


def _format_primitive_block() -> str:
    lines = []
    for spec in primitives.PRIMITIVES.values():
        arg_sig = ", ".join(spec.args) if spec.args else "(none)"
        lines.append(f"- {spec.name}({arg_sig}): {spec.description}")
    return "\n".join(lines)


def _format_few_shots(few_shots: list[FewShotExample]) -> str:
    if not few_shots:
        return ""
    blocks = ["Here are similar instructions you planned correctly before:"]
    for ex in few_shots:
        steps = ex.plan.get("steps", [])
        compact = {"steps": [{"action": s.get("action"), "args": s.get("args", {})} for s in steps]}
        blocks.append(f'Instruction: "{ex.instruction}"\nPlan: {json.dumps(compact)}')
    blocks.append("Use them as guidance; adapt to the CURRENT world state below.\n")
    return "\n\n".join(blocks)


def _build_user_prompt(
    instruction: str, world: WorldModel, few_shots: list[FewShotExample]
) -> str:
    state = world.snapshot()
    objects = [
        {"id": o["id"], "color": o["color"], "shape": o["shape"], "on_top_of": o["on_top_of"]}
        for o in state["objects"]
    ]
    locations = [{"id": loc["id"], "name": loc["name"], "kind": loc["kind"]} for loc in state["locations"]]
    few_shot_block = _format_few_shots(few_shots)
    return (
        f"{few_shot_block}"
        "World state:\n"
        f"objects = {json.dumps(objects)}\n"
        f"locations = {json.dumps(locations)}\n"
        f"robot = {json.dumps(state['robot'])}\n\n"
        f"Instruction: {instruction}\n\n"
        "Return the JSON plan now."
    )


class LLMPlanner:
    """Dispatches to the configured LLM backend and validates its output."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # -- availability --------------------------------------------------------

    def is_available(self) -> bool:
        """True if the configured backend *could* run (key + SDK/HTTP present)."""

        backend = self.settings.llm_backend.lower()
        if backend == "mistral":
            return bool(self.settings.mistral_api_key) and (
                _module_available("mistralai") or _module_available("httpx")
            )
        if backend == "anthropic":
            return bool(self.settings.anthropic_api_key) and _module_available("anthropic")
        return False

    def availability_note(self) -> str:
        """Human-readable explanation of LLM availability for the UI."""

        backend = self.settings.llm_backend.lower()
        if not self.settings.enable_llm:
            return "LLM planner disabled via ENABLE_LLM=false; using heuristic planner."
        if backend == "mistral":
            if not self.settings.mistral_api_key:
                return (
                    "Mistral backend selected but MISTRAL_API_KEY is not set; "
                    "using heuristic planner."
                )
            if not (_module_available("mistralai") or _module_available("httpx")):
                return (
                    "Mistral backend selected but neither the 'mistralai' SDK nor "
                    "'httpx' is installed; using heuristic planner."
                )
            transport = "mistralai SDK" if _module_available("mistralai") else "REST/httpx"
            return f"Mistral backend ready (model={self.settings.mistral_model}, via {transport})."
        if backend == "anthropic":
            if not self.settings.anthropic_api_key:
                return (
                    "Anthropic backend selected but ANTHROPIC_API_KEY is not set; "
                    "using heuristic planner."
                )
            if not _module_available("anthropic"):
                return (
                    "Anthropic backend selected but the 'anthropic' SDK is not "
                    "installed; using heuristic planner."
                )
            return f"Anthropic backend ready (model={self.settings.anthropic_model})."
        return f"Unknown LLM backend '{backend}'; using heuristic planner."

    # -- planning ------------------------------------------------------------

    def plan(
        self,
        instruction: str,
        world: WorldModel,
        few_shots: list[FewShotExample] | None = None,
    ) -> Plan:
        """Produce a validated plan via the configured backend.

        Raises :class:`LLMUnavailable` if the backend cannot run or returns an
        unparseable/invalid plan, so the caller can fall back to heuristics.
        """

        if not self.settings.enable_llm:
            raise LLMUnavailable("LLM planning disabled via settings")

        few_shots = few_shots or []
        backend = self.settings.llm_backend.lower()
        if backend == "mistral":
            raw = self._call_mistral(instruction, world, few_shots)
        elif backend == "anthropic":
            raw = self._call_anthropic(instruction, world, few_shots)
        else:
            raise LLMUnavailable(f"unknown LLM backend '{backend}'")

        plan = self._parse_plan(instruction, raw)
        validation = validate_plan(plan, world)
        if not validation.valid:
            raise LLMUnavailable(
                "LLM produced an invalid plan: " + "; ".join(validation.errors)
            )
        return plan

    # -- Mistral backend (default) ------------------------------------------

    def _call_mistral(
        self, instruction: str, world: WorldModel, few_shots: list[FewShotExample]
    ) -> str:
        if not self.settings.mistral_api_key:
            raise LLMUnavailable("MISTRAL_API_KEY is not configured")

        system = SYSTEM_PROMPT.format(primitive_block=_format_primitive_block())
        user = _build_user_prompt(instruction, world, few_shots)

        # Prefer the official SDK; fall back to a direct REST call via httpx.
        if _module_available("mistralai"):
            return self._call_mistral_sdk(system, user)
        if _module_available("httpx"):
            return self._call_mistral_rest(system, user)
        raise LLMUnavailable("neither 'mistralai' SDK nor 'httpx' is installed")

    def _call_mistral_sdk(self, system: str, user: str) -> str:  # pragma: no cover - network/SDK
        try:
            from mistralai import Mistral  # type: ignore  # deferred optional import
        except ImportError as exc:
            raise LLMUnavailable("the 'mistralai' SDK is not installed") from exc

        try:
            client = Mistral(api_key=self.settings.mistral_api_key)
            response = client.chat.complete(
                model=self.settings.mistral_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
                max_tokens=self.settings.llm_max_tokens,
                temperature=0.0,
            )
        except Exception as exc:
            raise LLMUnavailable(f"Mistral request failed: {exc}") from exc

        try:
            text = response.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as exc:
            raise LLMUnavailable(f"Mistral returned an unexpected response: {exc}") from exc
        if isinstance(text, list):  # newer SDKs may return content chunks
            text = "".join(getattr(c, "text", "") or "" for c in text)
        if not text:
            raise LLMUnavailable("Mistral returned no content")
        return text

    def _call_mistral_rest(self, system: str, user: str) -> str:  # pragma: no cover - network
        try:
            import httpx  # type: ignore  # deferred optional import
        except ImportError as exc:
            raise LLMUnavailable("'httpx' is not installed for the Mistral REST fallback") from exc

        url = f"{self.settings.mistral_base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.settings.mistral_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": self.settings.llm_max_tokens,
            "temperature": 0.0,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.mistral_api_key}",
            "Content-Type": "application/json",
        }
        try:
            resp = httpx.post(
                url, json=payload, headers=headers, timeout=self.settings.llm_timeout_seconds
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as exc:
            raise LLMUnavailable(f"Mistral REST request failed: {exc}") from exc

    # -- Anthropic backend (alternative) ------------------------------------

    def _call_anthropic(
        self, instruction: str, world: WorldModel, few_shots: list[FewShotExample]
    ) -> str:  # pragma: no cover - network/SDK
        if not self.settings.anthropic_api_key:
            raise LLMUnavailable("ANTHROPIC_API_KEY is not configured")
        try:
            import anthropic  # type: ignore  # deferred optional import
        except ImportError as exc:
            raise LLMUnavailable("the 'anthropic' SDK is not installed") from exc

        client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
        system = SYSTEM_PROMPT.format(primitive_block=_format_primitive_block())
        user = _build_user_prompt(instruction, world, few_shots)

        try:
            # Adaptive thinking + structured JSON output. Streaming keeps long
            # responses under the SDK HTTP timeout.
            with client.messages.stream(
                model=self.settings.anthropic_model,
                max_tokens=self.settings.llm_max_tokens,
                system=system,
                thinking={"type": "adaptive"},
                output_config={
                    "format": {
                        "type": "json_schema",
                        "schema": _PLAN_JSON_SCHEMA,
                    }
                },
                messages=[{"role": "user", "content": user}],
            ) as stream:
                message = stream.get_final_message()
        except Exception as exc:
            raise LLMUnavailable(f"Anthropic request failed: {exc}") from exc

        text = next((b.text for b in message.content if b.type == "text"), "")
        if not text:
            raise LLMUnavailable("Anthropic returned no text content")
        return text

    # -- parsing -------------------------------------------------------------

    def _parse_plan(self, instruction: str, raw: str) -> Plan:
        data = _extract_json(raw)
        if data is None:
            raise LLMUnavailable("could not extract JSON from LLM output")
        steps_data = data.get("steps")
        if not isinstance(steps_data, list) or not steps_data:
            raise LLMUnavailable("LLM JSON missing a non-empty 'steps' array")
        try:
            steps = [PlanStep.from_dict(s) for s in steps_data]
        except (ValueError, TypeError) as exc:
            raise LLMUnavailable(f"malformed plan step: {exc}") from exc
        return Plan(instruction=instruction, steps=steps, planner="llm")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PLAN_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "args": {"type": "object", "additionalProperties": True},
                    "rationale": {"type": "string"},
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["steps"],
    "additionalProperties": False,
}


def _module_available(name: str) -> bool:
    """True if a module can be imported without actually importing it heavily."""

    import importlib.util

    return importlib.util.find_spec(name) is not None


def _extract_json(text: str) -> dict[str, Any] | None:
    """Best-effort extraction of a JSON object from raw model text."""

    text = text.strip()
    # Direct parse.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Strip code fences.
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass
    # Greedy outermost-object match.
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None
