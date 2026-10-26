"""Task CRUD, filtering, pagination, and ownership tests."""

from __future__ import annotations

from datetime import date, timedelta


def create_task(client, headers, **overrides):
    payload = {
        "title": "Submit tax report",
        "description": "Quarterly filing",
        "category": "finance",
        "due_date": (date.today() + timedelta(days=2)).isoformat(),
        "effort_minutes": 90,
    }
    payload.update(overrides)
    return client.post("/api/tasks", json=payload, headers=headers)


def test_create_task_defaults_and_shape(client, auth_headers):
    response = create_task(client, auth_headers())
    assert response.status_code == 201
    task = response.get_json()["task"]
    assert task["title"] == "Submit tax report"
    assert task["status"] == "pending"
    assert task["priority"] == "MEDIUM"
    assert task["priority_source"] == "auto"
    assert task["effort_minutes"] == 90
    assert task["days_until_due"] == 2
    assert task["is_overdue"] is False


def test_create_task_requires_authentication(client):
    response = client.post("/api/tasks", json={"title": "Nope"})
    assert response.status_code == 401


def test_create_task_validates_fields(client, auth_headers):
    headers = auth_headers()
    cases = [
        ({"title": "   "}, "Title"),
        ({"category": "space"}, "category"),
        ({"due_date": "31-12-2026"}, "YYYY-MM-DD"),
        ({"effort_minutes": 2}, "Effort"),
        ({"effort_minutes": "a lot"}, "Effort"),
    ]
    for override, expected in cases:
        response = create_task(client, headers, **override)
        assert response.status_code == 400, override
        assert expected.lower() in response.get_json()["error"].lower()


def test_list_views_and_counts(client, auth_headers):
    headers = auth_headers()
    today = date.today()
    create_task(client, headers, title="Today", due_date=today.isoformat())
    create_task(
        client, headers, title="Tomorrow", due_date=(today + timedelta(days=1)).isoformat()
    )
    create_task(
        client, headers, title="Overdue", due_date=(today - timedelta(days=2)).isoformat()
    )
    completed = create_task(client, headers, title="Done", due_date=today.isoformat())
    task_id = completed.get_json()["task"]["id"]
    client.patch(f"/api/tasks/{task_id}/complete", json={"completed": True}, headers=headers)

    counts = client.get("/api/tasks").get_json()["counts"]
    assert counts == {
        "total": 4,
        "completed": 1,
        "pending": 3,
        "today": 1,
        "upcoming": 1,
        "overdue": 1,
        "at_risk": 0,
    }

    today_titles = [t["title"] for t in client.get("/api/tasks?view=today").get_json()["tasks"]]
    assert today_titles == ["Today"]
    upcoming_titles = [
        t["title"] for t in client.get("/api/tasks?view=upcoming").get_json()["tasks"]
    ]
    assert upcoming_titles == ["Tomorrow"]
    overdue_titles = [
        t["title"] for t in client.get("/api/tasks?view=overdue").get_json()["tasks"]
    ]
    assert overdue_titles == ["Overdue"]
    completed_titles = [
        t["title"] for t in client.get("/api/tasks?view=completed").get_json()["tasks"]
    ]
    assert completed_titles == ["Done"]


def test_list_filters_search_and_sort(client, auth_headers):
    headers = auth_headers()
    create_task(client, headers, title="Alpha report", category="work", priority="LOW")
    create_task(client, headers, title="Beta exam", category="study", priority="HIGH")
    create_task(client, headers, title="Gamma invoice", category="finance", priority="MEDIUM")

    high = client.get("/api/tasks?priority=HIGH").get_json()
    assert high["total"] == 1
    assert high["tasks"][0]["title"] == "Beta exam"

    study = client.get("/api/tasks?category=study").get_json()
    assert study["total"] == 1

    search = client.get("/api/tasks?search=invoice").get_json()
    assert search["total"] == 1
    assert search["tasks"][0]["title"] == "Gamma invoice"

    by_priority = client.get("/api/tasks?sort=priority").get_json()["tasks"]
    assert [task["priority"] for task in by_priority] == ["HIGH", "MEDIUM", "LOW"]


def test_list_pagination(client, auth_headers):
    headers = auth_headers()
    for index in range(7):
        create_task(client, headers, title=f"Task {index}")

    first = client.get("/api/tasks?page_size=5&page=1").get_json()
    second = client.get("/api/tasks?page_size=5&page=2").get_json()
    assert first["total"] == 7
    assert first["pages"] == 2
    assert len(first["tasks"]) == 5
    assert len(second["tasks"]) == 2
    assert {t["id"] for t in first["tasks"]}.isdisjoint({t["id"] for t in second["tasks"]})


def test_list_rejects_bad_view_sort_and_pagination(client, auth_headers):
    headers = auth_headers()
    create_task(client, headers)
    assert client.get("/api/tasks?view=nowhere").status_code == 400
    assert client.get("/api/tasks?sort=random").status_code == 400
    assert client.get("/api/tasks?page=abc").status_code == 400


def test_update_task_and_manual_priority(client, auth_headers):
    headers = auth_headers()
    task_id = create_task(client, headers).get_json()["task"]["id"]

    response = client.patch(
        f"/api/tasks/{task_id}",
        json={"title": "Submit VAT report", "priority": "HIGH", "effort_minutes": 45},
        headers=headers,
    )
    assert response.status_code == 200
    task = response.get_json()["task"]
    assert task["title"] == "Submit VAT report"
    assert task["priority"] == "HIGH"
    assert task["priority_source"] == "manual"
    assert task["effort_minutes"] == 45

    assert client.patch(f"/api/tasks/{task_id}", json={}, headers=headers).status_code == 400


def test_complete_and_reopen_task(client, auth_headers):
    headers = auth_headers()
    task_id = create_task(client, headers).get_json()["task"]["id"]

    completed = client.patch(
        f"/api/tasks/{task_id}/complete", json={"completed": True}, headers=headers
    )
    assert completed.get_json()["task"]["status"] == "completed"
    assert completed.get_json()["task"]["completed_at"] is not None

    reopened = client.patch(
        f"/api/tasks/{task_id}/complete", json={"completed": False}, headers=headers
    )
    assert reopened.get_json()["task"]["status"] == "pending"
    assert reopened.get_json()["task"]["completed_at"] is None

    toggled = client.patch(f"/api/tasks/{task_id}/complete", headers=headers)
    assert toggled.get_json()["task"]["status"] == "completed"


def test_delete_task(client, auth_headers):
    headers = auth_headers()
    task_id = create_task(client, headers).get_json()["task"]["id"]
    assert client.delete(f"/api/tasks/{task_id}", headers=headers).status_code == 200
    assert client.get(f"/api/tasks/{task_id}").status_code == 404


def test_tasks_are_isolated_per_user(client, auth_headers):
    headers = auth_headers()
    task_id = create_task(client, headers, title="Private").get_json()["task"]["id"]

    other_client = client.application.test_client()
    registration = other_client.post(
        "/api/auth/register",
        json={
            "email": "grace@example.com",
            "password": "correct-horse",
            "display_name": "Grace Hopper",
        },
    )
    assert registration.status_code == 201
    other_headers = {"X-CSRF-Token": registration.get_json()["csrf_token"]}

    listing = other_client.get("/api/tasks").get_json()
    assert listing["total"] == 0
    assert other_client.get(f"/api/tasks/{task_id}").status_code == 404
    assert (
        other_client.patch(
            f"/api/tasks/{task_id}", json={"title": "Hijacked"}, headers=other_headers
        ).status_code
        == 404
    )
    assert other_client.delete(f"/api/tasks/{task_id}", headers=other_headers).status_code == 404
    assert client.get(f"/api/tasks/{task_id}").status_code == 200
