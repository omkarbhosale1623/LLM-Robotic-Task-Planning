"""Tests for the real-brain pieces: auth verifier, embedder, plan memory,
LLM planner availability/fallback, and the in-memory repository.

All run offline with no provider key — the LLM backend is unavailable so the
planner falls back to the deterministic heuristic with a truthful note.
"""

from __future__ import annotations

import pytest
from app.config import Settings
from app.core.auth import AuthError, User, verify_supabase_jwt
from app.db.memory_repo import MemoryRepository
from app.db.repository import PlanMemoryRecord, RunRecord, SessionRecord, get_repository
from app.domain.embeddings import Embedder
from app.domain.llm_planner import FewShotExample, LLMPlanner, LLMUnavailable
from app.domain.world_model import WorldModel
from app.services.planning_service import PlanningService

from tests.conftest import TEST_JWT_SECRET, make_token

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def _settings(**kw: object) -> Settings:
    base: dict[str, object] = {
        "enable_llm": False,
        "auth_required": True,
        "supabase_jwt_secret": TEST_JWT_SECRET,
        "persistence_backend": "memory",
    }
    base.update(kw)
    return Settings(**base)


def test_verify_valid_token() -> None:
    user = verify_supabase_jwt(make_token(sub="u1", email="a@b.c"), _settings())
    assert isinstance(user, User)
    assert user.id == "u1"
    assert user.email == "a@b.c"


def test_verify_rejects_bad_signature() -> None:
    with pytest.raises(AuthError):
        verify_supabase_jwt(make_token(secret="nope"), _settings())


def test_verify_rejects_expired() -> None:
    with pytest.raises(AuthError):
        verify_supabase_jwt(make_token(exp_in=-10), _settings())


def test_verify_rejects_malformed() -> None:
    with pytest.raises(AuthError):
        verify_supabase_jwt("not.a.jwt.token", _settings())


def test_verify_requires_configured_secret() -> None:
    with pytest.raises(AuthError):
        verify_supabase_jwt(make_token(), Settings(supabase_jwt_secret=None))


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------


def test_hashing_embedder_is_deterministic_and_normalised() -> None:
    emb = Embedder(_settings(embedding_dim=64))
    v1 = emb._hash_embed("pick up the red block")
    v2 = emb._hash_embed("pick up the red block")
    assert v1 == v2
    assert len(v1) == 64
    norm = sum(x * x for x in v1) ** 0.5
    assert abs(norm - 1.0) < 1e-6


def test_embedder_embed_never_raises() -> None:
    emb = Embedder(_settings())
    vec = emb.embed("move the green ball to the bin")
    assert isinstance(vec, list) and vec


# ---------------------------------------------------------------------------
# Repository factory + in-memory repo
# ---------------------------------------------------------------------------


def test_get_repository_defaults_to_memory() -> None:
    repo = get_repository(_settings())
    assert isinstance(repo, MemoryRepository)


def test_get_repository_auto_without_dsn_is_memory() -> None:
    repo = get_repository(_settings(persistence_backend="auto", database_url=None))
    assert repo.backend == "memory"


@pytest.mark.asyncio
async def test_memory_repo_isolates_users_and_persists_runs() -> None:
    repo = MemoryRepository()
    s1 = await repo.create_session(SessionRecord(user_id="u1"))
    await repo.create_session(SessionRecord(user_id="u2"))

    assert await repo.get_session("u1", s1.id) is not None
    # u2 cannot read u1's session.
    assert await repo.get_session("u2", s1.id) is None

    await repo.save_run(RunRecord(session_id=s1.id, user_id="u1", kind="plan"))
    runs = await repo.list_runs("u1")
    assert len(runs) == 1
    assert await repo.list_runs("u2") == []


@pytest.mark.asyncio
async def test_plan_memory_search_ranks_by_similarity() -> None:
    repo = MemoryRepository()
    emb = Embedder(_settings(embedding_dim=64))
    a = emb._hash_embed("pick up the red block and place it on the shelf")
    b = emb._hash_embed("move the green ball to the bin")
    await repo.save_plan_memory(
        PlanMemoryRecord(user_id="u1", instruction="A", plan={"steps": [1]}, embedding=a)
    )
    await repo.save_plan_memory(
        PlanMemoryRecord(user_id="u1", instruction="B", plan={"steps": [2]}, embedding=b)
    )
    query = emb._hash_embed("pick up the red block and place it on the shelf")
    top = await repo.search_plan_memory("u1", query, top_k=1)
    assert top and top[0].instruction == "A"


# ---------------------------------------------------------------------------
# LLM planner availability + fallback (no key, offline)
# ---------------------------------------------------------------------------


def test_llm_unavailable_without_mistral_key() -> None:
    planner = LLMPlanner(_settings(enable_llm=True, llm_backend="mistral", mistral_api_key=None))
    assert planner.is_available() is False
    assert "MISTRAL_API_KEY" in planner.availability_note()


def test_default_mode_llm_when_key_present() -> None:
    s = _settings(enable_llm=True, llm_backend="mistral", mistral_api_key="sk-test")
    assert s.default_planner_mode == "llm"
    s2 = _settings(enable_llm=True, llm_backend="mistral", mistral_api_key=None)
    assert s2.default_planner_mode == "heuristic"


def test_anthropic_backend_selectable() -> None:
    s = _settings(enable_llm=True, llm_backend="anthropic", anthropic_api_key="sk-ant")
    note = LLMPlanner(s).availability_note().lower()
    # Anthropic SDK is not installed offline -> note explains that, truthfully.
    assert "anthropic" in note


def test_llm_planner_raises_when_disabled() -> None:
    planner = LLMPlanner(_settings(enable_llm=False))
    world = WorldModel()
    world.reset("default")
    with pytest.raises(LLMUnavailable):
        planner.plan("pick up the red block", world, few_shots=[])


@pytest.mark.asyncio
async def test_planning_service_with_memory_falls_back_and_stores() -> None:
    # No key -> LLM unavailable -> heuristic; valid plan still recorded to memory.
    settings = _settings(enable_llm=True, llm_backend="mistral", mistral_api_key=None)
    repo = MemoryRepository()
    service = PlanningService(settings, repository=repo)
    world = WorldModel()
    world.reset("default")

    outcome = await service.plan_with_memory(
        "pick up the red block and place it on the shelf", world, mode="llm", user_id="u1"
    )
    assert outcome.planner_used == "heuristic"
    assert outcome.validation.valid
    # Plan memory updated for this user.
    stored = await repo.search_plan_memory("u1", [0.0] * settings.embedding_dim, top_k=5)
    assert any(m.instruction.startswith("pick up the red block") for m in stored)


def test_few_shot_formatting_in_prompt() -> None:
    from app.domain.llm_planner import _build_user_prompt

    world = WorldModel()
    world.reset("default")
    few = [FewShotExample(instruction="pick up the red block", plan={"steps": [{"action": "pick"}]})]
    prompt = _build_user_prompt("pick up the blue block", world, few)
    assert "similar instructions" in prompt
    assert "pick up the red block" in prompt
