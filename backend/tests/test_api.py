"""API/integration tests using FastAPI's TestClient.

Auth is always enforced: the ``client`` fixture sends a valid Bearer token; the
``no_auth_client`` fixture sends none. The WebSocket test passes the token via
the ``?token=`` query parameter.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tests.conftest import make_token

# ---------------------------------------------------------------------------
# Public endpoints (no auth)
# ---------------------------------------------------------------------------


def test_health_is_public(no_auth_client: TestClient) -> None:
    resp = no_auth_client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["llm_available"] is False  # no key in tests


def test_metrics_is_public(no_auth_client: TestClient) -> None:
    resp = no_auth_client.get("/metrics")
    # /metrics is exposed by the optional instrumentator; if present it must be
    # public (200). If the optional dep is absent it 404s — still no auth gate.
    assert resp.status_code in (200, 404)


# ---------------------------------------------------------------------------
# Auth enforcement
# ---------------------------------------------------------------------------


def test_protected_route_401_without_token(no_auth_client: TestClient) -> None:
    resp = no_auth_client.get("/api/v1/world")
    assert resp.status_code == 401
    assert resp.json()["error"]["type"] == "authentication_error"


def test_protected_route_401_with_bad_signature(no_auth_client: TestClient) -> None:
    bad = make_token(secret="wrong-secret")
    resp = no_auth_client.get("/api/v1/world", headers={"Authorization": f"Bearer {bad}"})
    assert resp.status_code == 401


def test_protected_route_200_with_valid_token(client: TestClient) -> None:
    resp = client.get("/api/v1/world")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Business endpoints (authenticated)
# ---------------------------------------------------------------------------


def test_get_world(client: TestClient) -> None:
    resp = client.get("/api/v1/world")
    assert resp.status_code == 200
    body = resp.json()
    assert body["scene_name"] == "default"
    assert any(o["id"] == "red_block" for o in body["objects"])


def test_plan_endpoint(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/plan",
        json={
            "instruction": "pick up the red block and place it on the shelf",
            "mode": "heuristic",
            "use_current_world": False,
            "scene": "default",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["validation"]["valid"] is True
    assert "session_id" in body
    assert [s["action"] for s in body["plan"]["steps"]] == [
        "move_to",
        "pick",
        "move_to",
        "place",
    ]


def test_plan_validation_rejects_bad_instruction(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/plan",
        json={"instruction": "frobnicate the quux", "mode": "heuristic"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["validation"]["valid"] is False


def test_execute_updates_world_gripper(client: TestClient) -> None:
    create = client.post("/api/v1/world/reset", json={"scene": "default"})
    session_id = None
    # Use a single session for reset + execute so they share a world.
    plan_resp = client.post(
        "/api/v1/plan",
        json={"instruction": "pick up the red block", "mode": "heuristic"},
    )
    session_id = plan_resp.json()["session_id"]
    assert create.status_code == 200
    resp = client.post(
        "/api/v1/execute",
        json={
            "instruction": "grasp",
            "session_id": session_id,
            "reset_scene": "default",
            "plan": [
                {"action": "move_to", "args": {"target": "red_block"}},
                {"action": "pick", "args": {"target": "red_block"}},
            ],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["final_state"]["robot"]["holding"] == "red_block"


def test_plan_and_run(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/plan-and-run",
        json={
            "instruction": "pick up the red block and place it on the shelf",
            "mode": "heuristic",
            "reset_scene": "default",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["execution"]["success"] is True
    assert "session_id" in body
    placed = next(
        o for o in body["execution"]["final_state"]["objects"] if o["id"] == "red_block"
    )
    assert placed["on_top_of"] == "shelf"


def test_benchmark_endpoint_returns_rate(client: TestClient) -> None:
    resp = client.get("/api/v1/benchmark?mode=heuristic")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 20
    assert 0.0 <= body["completion_rate"] <= 1.0
    assert body["passed"] >= 16


def test_capabilities(client: TestClient) -> None:
    resp = client.get("/api/v1/capabilities")
    assert resp.status_code == 200
    body = resp.json()
    names = {p["name"] for p in body["primitives"]}
    assert {"move_to", "pick", "place"} <= names
    assert len(body["benchmark_commands"]) == 20
    assert body["llm_available"] is False
    assert body["default_mode"] == "heuristic"
    assert body["llm_backend"] == "mistral"


def test_unknown_scene_404(client: TestClient) -> None:
    resp = client.post("/api/v1/world/reset", json={"scene": "does_not_exist"})
    assert resp.status_code == 404
    assert resp.json()["error"]["type"] == "not_found"


# ---------------------------------------------------------------------------
# Sessions & runs persistence
# ---------------------------------------------------------------------------


def test_sessions_and_runs_persist(client: TestClient) -> None:
    # A plan creates a session and a run record.
    plan = client.post(
        "/api/v1/plan",
        json={"instruction": "pick up the red block", "mode": "heuristic"},
    )
    session_id = plan.json()["session_id"]

    sessions = client.get("/api/v1/sessions").json()["sessions"]
    assert any(s["id"] == session_id for s in sessions)

    runs = client.get(f"/api/v1/sessions/{session_id}/runs").json()["runs"]
    assert any(r["kind"] == "plan" for r in runs)


def test_user_cannot_see_another_users_session(
    client: TestClient, no_auth_client: TestClient
) -> None:
    plan = client.post(
        "/api/v1/plan",
        json={"instruction": "pick up the red block", "mode": "heuristic"},
    )
    session_id = plan.json()["session_id"]

    other = make_token(sub="other-user")
    resp = no_auth_client.get(
        f"/api/v1/sessions/{session_id}/runs",
        headers={"Authorization": f"Bearer {other}"},
    )
    assert resp.status_code == 404  # not visible to a different user


# ---------------------------------------------------------------------------
# WebSocket (token via query param)
# ---------------------------------------------------------------------------


def test_execution_websocket_streams_events(client: TestClient) -> None:
    token = make_token()
    with client.websocket_connect(f"/ws/execution?token={token}") as ws:
        ws.send_json(
            {
                "instruction": "pick up the red block and place it on the shelf",
                "mode": "heuristic",
                "reset_scene": "default",
            }
        )
        types_seen = []
        result = None
        for _ in range(40):
            msg = ws.receive_json()
            types_seen.append(msg["type"])
            if msg["type"] == "result":
                result = msg
                break
        assert "plan" in types_seen
        assert "step" in types_seen
        assert result is not None
        assert result["success"] is True


def test_execution_websocket_rejects_without_token(no_auth_client: TestClient) -> None:
    with (
        pytest.raises(WebSocketDisconnect),
        no_auth_client.websocket_connect("/ws/execution") as ws,
    ):
        ws.receive_json()
