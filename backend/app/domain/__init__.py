"""Domain layer: world model, primitive actions, and planners.

This package holds the project "brains":

* :mod:`world_model` — a STRIPS-like tabletop world (objects, locations, robot).
* :mod:`primitives` — the primitive action set with preconditions/effects.
* :mod:`planner` — the deterministic heuristic NL -> plan parser (always available).
* :mod:`llm_planner` — the optional LLM-backed planner (gated behind settings).

Nothing in this package imports torch/transformers or an LLM SDK at module import
time, so the whole domain layer runs with only the pinned base dependencies.
"""
