"""L1 API tests — the full 02 REST contract (TC-003..TC-020) plus the
abuse rows that belong to this app (TC-024..TC-027; no milestone exit
claims them, so M1 owns them) and a few extra coverage cases.

In-process TestClient over a fresh temp SQLite DB (WAL) per test.
"""

import asyncio
import json
import sqlite3
import uuid

import httpx
from fastapi.testclient import TestClient

from app import main
from conftest import VALID_NOTE, VALID_WORK_ORDER

ZERO_ID = "00000000-0000-0000-0000-000000000000"


def _post(client, payload=None):
    if payload is None:
        payload = VALID_WORK_ORDER
    return client.post("/api/v1/work-orders", json=payload)


def test_tc003_create_work_order_happy_path(client):
    response = _post(client)
    assert response.status_code == 201
    entity = response.json()
    # server-generated UUID id; always created open (02)
    uuid.UUID(entity["id"])
    assert entity["status"] == "open"
    assert entity["created_at"].endswith("Z")
    assert entity["updated_at"].endswith("Z")
    # request fields echoed back, citations round-tripped
    for field in ("title", "description", "equipment", "anomaly_ref",
                  "priority", "assigned_to"):
        assert entity[field] == VALID_WORK_ORDER[field]
    assert entity["citations"] == VALID_WORK_ORDER["citations"]


def test_tc004_list_work_orders_newest_first(client):
    first = _post(client).json()["id"]
    second = _post(client).json()["id"]
    assert first != second
    response = client.get("/api/v1/work-orders")
    assert response.status_code == 200
    assert [w["id"] for w in response.json()] == [second, first]


def test_tc005_get_work_order_by_id(client):
    created = _post(client).json()
    response = client.get(f"/api/v1/work-orders/{created['id']}")
    assert response.status_code == 200
    fetched = response.json()
    for field in ("id", "title", "description", "equipment",
                  "anomaly_ref", "priority", "assigned_to", "status",
                  "citations", "created_at", "updated_at"):
        assert fetched[field] == created[field]


def test_tc006_get_unknown_id_404(client):
    response = client.get(f"/api/v1/work-orders/{ZERO_ID}")
    assert response.status_code == 404
    assert "detail" in response.json()


def test_tc007_create_missing_required_field_422(client):
    payload = dict(VALID_WORK_ORDER)
    del payload["title"]
    response = client.post("/api/v1/work-orders", json=payload)
    assert response.status_code == 422
    assert "title" in json.dumps(response.json())  # names the field


def test_tc008_create_bad_enum_422(client):
    response = _post(client, dict(VALID_WORK_ORDER, priority="urgent"))
    assert response.status_code == 422


def test_tc009_create_malformed_body_422_not_500(client):
    response = client.post(
        "/api/v1/work-orders",
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert response.status_code != 500


def test_tc010_create_oversized_body_413(client):
    # 300 KB body: the 256 KB request cap (413) fires before the
    # 8000-char description field cap (which would be a 422).
    payload = dict(VALID_WORK_ORDER, description="x" * 300_000)
    response = client.post("/api/v1/work-orders", json=payload)
    assert response.status_code == 413
    assert "detail" in response.json()


def test_tc011_status_update(client):
    created = _post(client).json()
    response = client.patch(
        f"/api/v1/work-orders/{created['id']}",
        json={"status": "in_progress"},
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["status"] == "in_progress"
    assert updated["updated_at"] >= updated["created_at"]


def test_tc012_patch_unknown_id_404(client):
    response = client.patch(
        f"/api/v1/work-orders/{ZERO_ID}", json={"status": "resolved"}
    )
    assert response.status_code == 404


def test_tc013_patch_bad_enum_422(client):
    created = _post(client).json()
    response = client.patch(
        f"/api/v1/work-orders/{created['id']}", json={"status": "yolo"}
    )
    assert response.status_code == 422


def test_tc014_monitoring_note_beat5(client):
    response = client.post("/api/v1/notes", json=VALID_NOTE)
    assert response.status_code == 201
    note = response.json()
    uuid.UUID(note["id"])
    assert note["equipment"] == VALID_NOTE["equipment"]
    assert note["anomaly_ref"] == VALID_NOTE["anomaly_ref"]
    listing = client.get("/api/v1/notes")
    assert listing.status_code == 200
    assert [n["id"] for n in listing.json()] == [note["id"]]


def test_tc015_notification_auto_creation(client):
    created = _post(client).json()
    response = client.get("/api/v1/notifications")
    assert response.status_code == 200
    notifications = response.json()
    assert len(notifications) == 1
    assert notifications[0]["work_order_id"] == created["id"]
    assert notifications[0]["channel"] == "in_app"
    assert len(notifications[0]["message"]) <= 500
    assert created["title"] in notifications[0]["message"]
    assert notifications[0]["read_at"] is None


def test_tc016_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    # 02 interface table + TC-016 (see main.py note on the 09/lab-prep
    # "Health == healthy" restatement).
    assert response.json() == {"status": "ok", "db": "ok"}


def test_tc017_list_filters(client):
    open_wo = _post(client).json()["id"]
    other = _post(client).json()["id"]
    client.patch(
        f"/api/v1/work-orders/{other}", json={"status": "in_progress"}
    )
    response = client.get(
        "/api/v1/work-orders", params={"status": "open"}
    )
    assert response.status_code == 200
    assert [w["id"] for w in response.json()] == [open_wo]
    bad = client.get("/api/v1/work-orders", params={"status": "bogus"})
    assert bad.status_code == 422


def test_tc018_post_is_not_idempotent(client):
    first = _post(client)
    second = _post(client)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    # retries duplicate — both are visible in the list (known behaviour)
    assert len(client.get("/api/v1/work-orders").json()) == 2


def test_tc019_persistence_across_restart(tmp_path):
    db_path = str(tmp_path / "restart.db")
    app_one = main.create_app(db_path)
    with TestClient(app_one) as client_one:
        created = _post(client_one).json()
    # "restart": a fresh app process on the SAME DB path
    app_two = main.create_app(db_path)
    with TestClient(app_two) as client_two:
        fetched = client_two.get(f"/api/v1/work-orders/{created['id']}")
        assert fetched.status_code == 200
        assert fetched.json()["id"] == created["id"]


def test_tc020_concurrency_ten_parallel_posts(app):
    async def ten_parallel_posts():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as async_client:
            async def one():
                return await async_client.post(
                    "/api/v1/work-orders", json=VALID_WORK_ORDER
                )

            return await asyncio.gather(*[one() for _ in range(10)])

    responses = asyncio.run(ten_parallel_posts())
    assert all(r.status_code == 201 for r in responses)
    assert len({r.json()["id"] for r in responses}) == 10
    with TestClient(app) as client:
        assert len(client.get("/api/v1/work-orders").json()) == 10


# ---------------------------------------------------------------------------
# TC-024..TC-027 — L1 abuse rows that test this app (no milestone exit
# claims them; M1 owns them so the closing-gate full run covers all rows).
# ---------------------------------------------------------------------------


def test_tc024_sql_injection_in_id_404_table_intact(client):
    response = client.get("/api/v1/work-orders/x'; DROP TABLE work_orders;--")
    assert response.status_code == 404
    # the table is intact: the list endpoint still serves
    assert client.get("/api/v1/work-orders").status_code == 200


def test_tc025_path_traversal_in_id_404(client):
    response = client.get("/api/v1/work-orders/../../etc/passwd")
    assert response.status_code == 404


def test_tc026_oversized_citation_array_422(client):
    citations = [
        {"source_type": "rag", "source_id": f"doc-{i}", "quote": "q"}
        for i in range(51)
    ]
    payload = dict(VALID_WORK_ORDER, citations=citations)
    response = client.post("/api/v1/work-orders", json=payload)
    assert response.status_code == 422


def test_tc027_empty_patch_422(client):
    created = _post(client).json()
    response = client.patch(f"/api/v1/work-orders/{created['id']}", json={})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Extra coverage (not TC rows): degenerate / error paths.
# ---------------------------------------------------------------------------


def test_extra_health_503_when_db_unreachable(client, monkeypatch):
    def boom(path):
        raise sqlite3.OperationalError("database unavailable")

    import app.db as app_db

    monkeypatch.setattr(app_db, "connect", boom)
    response = client.get("/health")
    assert response.status_code == 503


def test_extra_unread_filter(client):
    _post(client)
    ok = client.get("/api/v1/notifications", params={"unread": "true"})
    assert ok.status_code == 200
    assert len(ok.json()) == 1
    bad = client.get("/api/v1/notifications", params={"unread": "maybe"})
    assert bad.status_code == 422


def test_extra_equipment_filter(client):
    _post(client)
    payload = dict(VALID_WORK_ORDER, equipment="PUMP-9")
    other = _post(client, payload).json()["id"]
    response = client.get(
        "/api/v1/work-orders", params={"equipment": "PUMP-9"}
    )
    assert [w["id"] for w in response.json()] == [other]


def test_extra_patch_clears_assignment(client):
    created = _post(client).json()
    assert created["assigned_to"] == VALID_WORK_ORDER["assigned_to"]
    response = client.patch(
        f"/api/v1/work-orders/{created['id']}", json={"assigned_to": None}
    )
    assert response.status_code == 200
    assert response.json()["assigned_to"] is None


def test_extra_generated_fields_not_accepted_as_input(client):
    # 02: status/id/created_at/updated_at are generated server-side; a
    # client-supplied status is ignored (extra fields dropped by pydantic)
    # and the work order is still created open.
    payload = dict(VALID_WORK_ORDER, status="resolved", id=ZERO_ID)
    response = client.post("/api/v1/work-orders", json=payload)
    assert response.status_code == 201
    assert response.json()["status"] == "open"
    uuid.UUID(response.json()["id"])
    assert response.json()["id"] != ZERO_ID


def test_extra_patch_assigned_only(client):
    created = _post(client).json()
    response = client.patch(
        f"/api/v1/work-orders/{created['id']}",
        json={"assigned_to": "night-shift"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["assigned_to"] == "night-shift"
    assert body["status"] == "open"  # untouched


def test_extra_null_only_status_patch_422(client):
    # Decision 5: a patch with no effective field is an empty patch —
    # {"status": null} changes nothing, so it is rejected like {}.
    created = _post(client).json()
    response = client.patch(
        f"/api/v1/work-orders/{created['id']}", json={"status": None}
    )
    assert response.status_code == 422


def test_extra_empty_db_list_is_empty_array(client):
    response = client.get("/api/v1/work-orders")
    assert response.status_code == 200
    assert response.json() == []
    assert client.get("/api/v1/notifications").json() == []
    assert client.get("/api/v1/notes").json() == []
