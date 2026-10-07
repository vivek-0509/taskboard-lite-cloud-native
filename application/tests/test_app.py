"""Unit tests for TaskBoard Lite.

Every test gets a fresh application whose DATA_DIR points at a pytest
tmp_path, so tests never touch a shared database.
"""

import pytest

from app import create_app

SECRET_VALUE = "unit-test-password-value"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("FEATURE_FLAGS", "dark-mode,metrics")
    monkeypatch.setenv("DB_PASSWORD", SECRET_VALUE)
    monkeypatch.setenv("APP_VERSION", "test-build")
    application = create_app()
    application.config.update(TESTING=True)
    yield application
    application.extensions["task_store"].close()


@pytest.fixture
def client(app):
    return app.test_client()


def create_task(client, title="write tests", done=False):
    response = client.post("/api/tasks", json={"title": title, "done": done})
    assert response.status_code == 201
    return response.get_json()


# -- probes -----------------------------------------------------------------
def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_ready_returns_ready_when_database_works(client, tmp_path):
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ready"}
    assert (tmp_path / "data" / "tasks.db").exists()


def test_ready_returns_503_when_database_is_unavailable(tmp_path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    monkeypatch.setenv("DATA_DIR", str(blocker / "data"))
    application = create_app()
    response = application.test_client().get("/ready")
    assert response.status_code == 503
    assert response.get_json()["status"] == "not-ready"


# -- metrics ----------------------------------------------------------------
def test_metrics_exposes_request_counter(client):
    client.get("/health")
    response = client.get("/metrics")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "taskboard_requests_total" in body
    assert 'endpoint="/health"' in body
    assert "taskboard_tasks_created_total" in body
    assert "taskboard_tasks_open" in body


def test_metrics_open_tasks_gauge_tracks_state(client):
    create_task(client, "open one")
    create_task(client, "done one", done=True)
    body = client.get("/metrics").get_data(as_text=True)
    assert "taskboard_tasks_open 1.0" in body


# -- CRUD -------------------------------------------------------------------
def test_create_task(client):
    task = create_task(client, "ship the capstone")
    assert task["id"] == 1
    assert task["title"] == "ship the capstone"
    assert task["done"] is False
    assert task["created_at"] == task["updated_at"]


def test_create_task_requires_title(client):
    response = client.post("/api/tasks", json={"title": "   "})
    assert response.status_code == 400
    assert response.get_json()["message"] == "title is required"


def test_create_task_from_html_form_redirects_to_index(client):
    response = client.post("/api/tasks", data={"title": "from the form"})
    assert response.status_code == 303
    assert response.headers["Location"].endswith("/")
    assert client.get("/api/tasks").get_json()[0]["title"] == "from the form"


def test_list_tasks(client):
    assert client.get("/api/tasks").get_json() == []
    create_task(client, "first")
    create_task(client, "second")
    titles = [task["title"] for task in client.get("/api/tasks").get_json()]
    assert titles == ["first", "second"]


def test_get_single_task(client):
    created = create_task(client, "look me up")
    response = client.get(f"/api/tasks/{created['id']}")
    assert response.status_code == 200
    assert response.get_json() == created


def test_get_missing_task_returns_404_json(client):
    response = client.get("/api/tasks/999")
    assert response.status_code == 404
    assert response.get_json()["error"] == "Not Found"


def test_update_task(client):
    created = create_task(client, "draft")
    response = client.put(
        f"/api/tasks/{created['id']}", json={"title": "final", "done": True}
    )
    assert response.status_code == 200
    updated = response.get_json()
    assert updated["title"] == "final"
    assert updated["done"] is True
    assert client.get(f"/api/tasks/{created['id']}").get_json()["done"] is True


def test_delete_task(client):
    created = create_task(client, "temporary")
    response = client.delete(f"/api/tasks/{created['id']}")
    assert response.status_code == 204
    assert client.get(f"/api/tasks/{created['id']}").status_code == 404
    assert client.delete(f"/api/tasks/{created['id']}").status_code == 404


def test_stats(client):
    create_task(client, "a")
    create_task(client, "b", done=True)
    create_task(client, "c")
    assert client.get("/api/tasks/stats").get_json() == {"total": 3, "open": 2, "done": 1}


# -- config -----------------------------------------------------------------
def test_config_reports_settings_but_hides_password(client):
    response = client.get("/api/config")
    assert response.status_code == 200
    body = response.get_json()
    assert body["app_env"] == "test"
    assert body["log_level"] == "DEBUG"
    assert body["feature_flags"] == ["dark-mode", "metrics"]
    assert body["version"] == "test-build"
    assert body["db_password_set"] is True
    assert SECRET_VALUE not in response.get_data(as_text=True)


def test_config_reports_missing_password(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DB_PASSWORD", raising=False)
    application = create_app()
    assert application.test_client().get("/api/config").get_json()["db_password_set"] is False


def test_index_page_lists_tasks(client):
    create_task(client, "visible on the page")
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "TaskBoard Lite" in html
    assert "visible on the page" in html
    assert 'action="/api/tasks"' in html
