"""L1 UI tests — the server-rendered views (TC-021..TC-023) plus extras.

02 UI surface: GET / (beat-4 reveal list), GET /work-orders/{id}
(detail + citations grouped by source_type), GET /notes, GET /notifications.
Jinja2 autoescape is ON (04); TC-023 pins the escaping behaviour.
"""

import re

from conftest import VALID_NOTE, VALID_WORK_ORDER

BADGE_RE = re.compile(r'id="unread-badge"[^>]*>(\d+)<')


def _badge(html: str) -> int:
    m = BADGE_RE.search(html)
    return int(m.group(1)) if m else -1


def _create(client):
    response = client.post("/api/v1/work-orders", json=VALID_WORK_ORDER)
    assert response.status_code == 201
    return response.json()


def test_tc021_list_view_reveal_surface(client):
    # baseline: the list is visibly empty
    baseline = client.get("/")
    assert baseline.status_code == 200
    assert baseline.headers["content-type"].startswith("text/html")
    assert "No work orders yet." in baseline.text
    assert _badge(baseline.text) == 0

    # after the agent's POST: the new work order appears at the top
    created = _create(client)
    page = client.get("/")
    assert page.status_code == 200
    assert "No work orders yet." not in page.text
    assert created["title"] in page.text
    # short id (first 8 chars of the UUID) is displayed; the full-id href
    # links to the detail view
    assert created["id"][:8] in page.text
    assert f'/work-orders/{created["id"]}' in page.text
    # unread-notification badge >= 1
    assert _badge(page.text) >= 1


def test_tc022_detail_page_citations_grouped_by_source(client):
    created = _create(client)
    page = client.get(f"/work-orders/{created['id']}")
    assert page.status_code == 200
    html = page.text
    # all fields rendered
    assert created["title"] in html
    assert created["description"] in html
    assert created["anomaly_ref"] in html
    # citation source_id and quote rendered, grouped by source_type:
    # the rag citation sits inside the rag group, the vss one inside vss
    rag_h = html.index('data-source="rag"')
    vss_h = html.index('data-source="vss"')
    assert rag_h < vss_h
    rag_quote = html.index("Bearing temperature above 75")
    vss_quote = html.index("heat signature on bearing housing")
    assert rag_h < rag_quote < vss_h
    assert vss_h < vss_quote
    assert "manual-01#p12" in html
    assert "clip-anomaly-01@00:42" in html


def test_tc023_xss_title_renders_escaped(client):
    payload = dict(VALID_WORK_ORDER, title="<script>alert(1)</script>")
    created = client.post("/api/v1/work-orders", json=payload)
    assert created.status_code == 201
    page = client.get(f"/work-orders/{created.json()['id']}")
    assert page.status_code == 200
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page.text
    # no raw script tag anywhere in the page
    assert "<script>" not in page.text
    # the list view is escaped too
    assert "<script>" not in client.get("/").text


def test_extra_notes_page(client):
    baseline = client.get("/notes")
    assert baseline.status_code == 200
    assert "No monitoring notes yet." in baseline.text
    response = client.post("/api/v1/notes", json=VALID_NOTE)
    assert response.status_code == 201
    page = client.get("/notes")
    assert page.status_code == 200
    assert VALID_NOTE["description"] in page.text
    assert VALID_NOTE["anomaly_ref"] in page.text


def test_extra_notifications_page(client):
    created = _create(client)
    page = client.get("/notifications")
    assert page.status_code == 200
    assert f"/work-orders/{created['id']}" in page.text  # work-order link
    assert "in_app" in page.text
    assert "unread" in page.text


def test_extra_detail_unknown_id_404(client):
    response = client.get("/work-orders/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_extra_baseline_badge_zero_and_counts(client):
    page = client.get("/")
    assert page.status_code == 200
    assert _badge(page.text) == 0
    assert "(0)" in page.text  # work-order count on the page


def test_extra_static_css_served_and_linked(client):
    # 03 tech table: one static CSS file (no inline <style> block)
    css = client.get("/static/style.css")
    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")
    page = client.get("/")
    assert '/static/style.css' in page.text
    assert "<style>" not in page.text


def test_extra_list_order_newest_first_with_multiple_rows(client):
    """The exit clause "a new work order appears at the top after POST"
    pinned with >= 2 rows: the UI list order must match the API's
    newest-first order (the M1 spec-fidelity finding for this round)."""
    first = _create(client)
    second = _create(client)
    api_order = [w["id"] for w in client.get("/api/v1/work-orders").json()]
    assert api_order[0] == second["id"]  # the API's own newest-first order
    page = client.get("/")
    # one href per row, full id in the href — positions must follow api_order
    positions = [
        page.text.index(f'/work-orders/{w_id}"') for w_id in api_order
    ]
    assert positions == sorted(positions)
    # and the newest row's position precedes the older row's
    assert page.text.index(f'/work-orders/{second["id"]}"') < page.text.index(
        f'/work-orders/{first["id"]}"'
    )
