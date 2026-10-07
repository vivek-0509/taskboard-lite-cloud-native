"""TaskBoard Lite - a small Flask task board used as the capstone workload.

The application is intentionally tiny so that the surrounding DevOps tooling
(containers, Kubernetes, Helm, CI/CD, security scanning, monitoring, GitOps)
stays the focus of the project.

Configuration is read from environment variables:

  APP_ENV        logical environment name              (default: dev)
  LOG_LEVEL      python logging level                  (default: INFO)
  PORT           port used by the built-in dev server  (default: 8000)
  DATA_DIR       directory that holds tasks.db         (default: ./data)
                 use the literal value ":memory:" for an in-memory database
  DB_PASSWORD    only used to prove that secret injection works;
                 it is never logged and never returned by the API
  APP_VERSION    version string surfaced on /api/config (default: 1.0.0)
  FEATURE_FLAGS  comma separated list of enabled flags  (default: empty)

Run locally:      python app.py
Run with gunicorn: gunicorn -b 0.0.0.0:8000 -w 2 app:app
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    redirect,
    render_template_string,
    request,
    url_for,
)
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest
from werkzeug.exceptions import HTTPException

APP_NAME = "taskboard-lite"
DB_FILENAME = "tasks.db"
VALID_LOG_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

# ---------------------------------------------------------------------------
# Prometheus metrics (module level so they are registered exactly once)
# ---------------------------------------------------------------------------
REQUESTS_TOTAL = Counter(
    "taskboard_requests_total",
    "Total HTTP requests handled by TaskBoard Lite.",
    ["endpoint", "method", "status"],
)
TASKS_CREATED_TOTAL = Counter(
    "taskboard_tasks_created_total",
    "Total number of tasks created since the process started.",
)
TASKS_OPEN = Gauge(
    "taskboard_tasks_open",
    "Number of tasks that are not marked as done.",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT    NOT NULL,
    done       INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL,
    updated_at TEXT    NOT NULL
);
"""

INDEX_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TaskBoard Lite</title>
  <style>
    :root { --bg: #f7f7f5; --fg: #1f2933; --muted: #6b7280; --card: #ffffff; --line: #e5e7eb; --accent: #2563eb; }
    body.dark { --bg: #111827; --fg: #f3f4f6; --muted: #9ca3af; --card: #1f2937; --line: #374151; --accent: #60a5fa; }
    body { font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--fg);
           max-width: 640px; margin: 2rem auto; padding: 0 1rem; }
    h1 { margin-bottom: 0.25rem; }
    .meta, .links { color: var(--muted); font-size: 0.9rem; }
    form { display: flex; gap: 0.5rem; margin: 1rem 0; }
    input { flex: 1; padding: 0.5rem; border: 1px solid var(--line); border-radius: 4px; background: var(--card); color: var(--fg); }
    button { padding: 0.45rem 0.8rem; border: 1px solid var(--line); border-radius: 4px; background: var(--card); color: var(--fg); cursor: pointer; }
    button.primary { background: var(--accent); color: #fff; border-color: var(--accent); }
    ul { list-style: none; padding: 0; }
    li { display: flex; align-items: center; gap: 0.5rem; padding: 0.5rem 0.75rem; border: 1px solid var(--line);
         border-radius: 4px; background: var(--card); margin-bottom: 0.5rem; }
    li span { flex: 1; }
    li.done span { text-decoration: line-through; color: var(--muted); }
    .links a { color: var(--accent); }
  </style>
</head>
<body class="{{ 'dark' if 'dark-mode' in cfg.FEATURE_FLAGS else '' }}">
  <h1>TaskBoard Lite</h1>
  <p class="meta">env: {{ cfg.APP_ENV }} &middot; version: {{ cfg.APP_VERSION }}
     &middot; open: {{ stats.open }} / total: {{ stats.total }}</p>

  <form method="post" action="{{ url_for('tasks_collection') }}">
    <input name="title" placeholder="What needs to be done?" required maxlength="200" autocomplete="off">
    <button class="primary" type="submit">Add task</button>
  </form>

  <ul>
  {% for task in tasks %}
    <li class="{{ 'done' if task.done else '' }}">
      <span>#{{ task.id }} {{ task.title }}</span>
      <button class="toggle" data-id="{{ task.id }}" data-done="{{ 'false' if task.done else 'true' }}">
        {{ 'Reopen' if task.done else 'Done' }}
      </button>
      <button class="delete" data-id="{{ task.id }}">Delete</button>
    </li>
  {% else %}
    <li><span class="meta">No tasks yet. Add one above.</span></li>
  {% endfor %}
  </ul>

  <p class="links">
    <a href="/api/tasks">/api/tasks</a> &middot;
    <a href="/api/tasks/stats">/api/tasks/stats</a> &middot;
    <a href="/api/config">/api/config</a> &middot;
    <a href="/metrics">/metrics</a> &middot;
    <a href="/health">/health</a> &middot;
    <a href="/ready">/ready</a>
  </p>

  <script>
    document.querySelectorAll("button.toggle").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        await fetch("/api/tasks/" + btn.dataset.id, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ done: btn.dataset.done === "true" })
        });
        location.reload();
      });
    });
    document.querySelectorAll("button.delete").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        await fetch("/api/tasks/" + btn.dataset.id, { method: "DELETE" });
        location.reload();
      });
    });
  </script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Configuration and logging
# ---------------------------------------------------------------------------
def load_config() -> dict[str, Any]:
    """Build the runtime configuration from environment variables."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    if log_level not in VALID_LOG_LEVELS:
        log_level = "INFO"
    flags = [flag.strip() for flag in os.getenv("FEATURE_FLAGS", "").split(",") if flag.strip()]
    return {
        "APP_ENV": os.getenv("APP_ENV", "dev"),
        "LOG_LEVEL": log_level,
        "PORT": int(os.getenv("PORT", "8000")),
        "DATA_DIR": os.getenv("DATA_DIR", "./data"),
        "DB_PASSWORD": os.getenv("DB_PASSWORD", ""),
        "APP_VERSION": os.getenv("APP_VERSION", "1.0.0"),
        "FEATURE_FLAGS": flags,
    }


def configure_logging(level_name: str) -> None:
    logging.basicConfig(level=level_name, format=LOG_FORMAT)
    logging.getLogger().setLevel(level_name)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
class TaskStore:
    """SQLite-backed task store.

    A single connection is shared by all threads of the process and guarded
    by a lock. Each gunicorn worker process gets its own connection; SQLite
    serialises writers on the file itself. The schema is created lazily on
    first use so that importing the module has no side effects.
    """

    def __init__(self, data_dir: str) -> None:
        self.in_memory = data_dir == ":memory:"
        self.data_dir: Path | None = None if self.in_memory else Path(data_dir)
        self.db_path = ":memory:" if self.in_memory else str(Path(data_dir) / DB_FILENAME)
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            if self.data_dir is not None:
                self.data_dir.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=5)
            conn.row_factory = sqlite3.Row
            conn.executescript(SCHEMA)
            self._conn = conn
        return self._conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = self._get_connection()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "title": row["title"],
            "done": bool(row["done"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def ping(self) -> None:
        """Raise if the database cannot be opened or the schema is missing."""
        with self.connection() as conn:
            conn.execute("SELECT COUNT(*) FROM tasks").fetchone()

    def list_tasks(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM tasks ORDER BY id").fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def create_task(self, title: str, done: bool = False) -> dict[str, Any]:
        now = utc_now()
        with self.connection() as conn:
            cursor = conn.execute(
                "INSERT INTO tasks (title, done, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (title, int(done), now, now),
            )
            task_id = cursor.lastrowid
        task = self.get_task(task_id)
        if task is None:
            raise RuntimeError("task vanished after insert")
        return task

    def update_task(
        self, task_id: int, title: str | None = None, done: bool | None = None
    ) -> dict[str, Any] | None:
        current = self.get_task(task_id)
        if current is None:
            return None
        new_title = current["title"] if title is None else title
        new_done = current["done"] if done is None else done
        with self.connection() as conn:
            conn.execute(
                "UPDATE tasks SET title = ?, done = ?, updated_at = ? WHERE id = ?",
                (new_title, int(new_done), utc_now(), task_id),
            )
        return self.get_task(task_id)

    def delete_task(self, task_id: int) -> bool:
        with self.connection() as conn:
            cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return cursor.rowcount > 0

    def stats(self) -> dict[str, int]:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS total, COALESCE(SUM(done), 0) AS done FROM tasks"
            ).fetchone()
        total = int(row["total"])
        done = int(row["done"])
        return {"total": total, "open": total - done, "done": done}

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None


# ---------------------------------------------------------------------------
# Flask application factory
# ---------------------------------------------------------------------------
def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "on", "done"}


def _request_payload() -> dict[str, Any]:
    """Accept either a JSON object or an HTML form body."""
    if request.is_json:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            abort(400, description="JSON body must be an object")
        return data
    return request.form.to_dict()


def create_app(overrides: dict[str, Any] | None = None) -> Flask:
    cfg = load_config()
    if overrides:
        cfg.update(overrides)
    configure_logging(cfg["LOG_LEVEL"])

    app = Flask(APP_NAME)
    app.config.update(cfg)
    store = TaskStore(cfg["DATA_DIR"])
    app.extensions["task_store"] = store

    app.logger.info(
        "starting %s env=%s log_level=%s data_dir=%s version=%s db_password_set=%s flags=%s",
        APP_NAME,
        cfg["APP_ENV"],
        cfg["LOG_LEVEL"],
        cfg["DATA_DIR"],
        cfg["APP_VERSION"],
        bool(cfg["DB_PASSWORD"]),
        ",".join(cfg["FEATURE_FLAGS"]) or "-",
    )

    def refresh_open_gauge() -> None:
        try:
            TASKS_OPEN.set(store.stats()["open"])
        except Exception:  # pragma: no cover - only when the database is broken
            app.logger.warning("could not refresh taskboard_tasks_open gauge", exc_info=True)

    # -- cross cutting ------------------------------------------------------
    @app.after_request
    def record_request_metric(response: Response) -> Response:
        rule = request.url_rule.rule if request.url_rule is not None else "unmatched"
        REQUESTS_TOTAL.labels(endpoint=rule, method=request.method, status=response.status_code).inc()
        return response

    @app.errorhandler(HTTPException)
    def handle_http_exception(error: HTTPException):
        if request.path.startswith("/api/") or request.is_json:
            return jsonify(error=error.name, message=error.description), error.code
        return error.get_response()

    # -- pages and probes ---------------------------------------------------
    @app.get("/")
    def index():
        return render_template_string(
            INDEX_TEMPLATE, tasks=store.list_tasks(), stats=store.stats(), cfg=cfg
        )

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.get("/ready")
    def ready():
        try:
            store.ping()
        except Exception as exc:  # noqa: BLE001 - any failure means "not ready"
            app.logger.error("readiness check failed: %s", exc)
            return jsonify(status="not-ready", error=str(exc)), 503
        return jsonify(status="ready")

    @app.get("/metrics")
    def metrics():
        refresh_open_gauge()
        return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

    # -- API ----------------------------------------------------------------
    @app.get("/api/config")
    def api_config():
        return jsonify(
            app_env=cfg["APP_ENV"],
            log_level=cfg["LOG_LEVEL"],
            feature_flags=cfg["FEATURE_FLAGS"],
            version=cfg["APP_VERSION"],
            data_dir=cfg["DATA_DIR"],
            db_password_set=bool(cfg["DB_PASSWORD"]),
        )

    @app.get("/api/tasks/stats")
    def task_stats():
        return jsonify(store.stats())

    @app.route("/api/tasks", methods=["GET", "POST"])
    def tasks_collection():
        if request.method == "GET":
            return jsonify(store.list_tasks())

        payload = _request_payload()
        title = str(payload.get("title", "")).strip()
        if not title:
            abort(400, description="title is required")
        if len(title) > 200:
            abort(400, description="title must be 200 characters or fewer")

        task = store.create_task(title, done=_as_bool(payload.get("done", False)))
        TASKS_CREATED_TOTAL.inc()
        refresh_open_gauge()
        app.logger.info("task created id=%s", task["id"])

        if request.is_json:
            return jsonify(task), 201
        return redirect(url_for("index"), code=303)

    @app.get("/api/tasks/<int:task_id>")
    def get_task(task_id: int):
        task = store.get_task(task_id)
        if task is None:
            abort(404, description=f"task {task_id} not found")
        return jsonify(task)

    @app.put("/api/tasks/<int:task_id>")
    def update_task(task_id: int):
        payload = _request_payload()
        title = payload.get("title")
        done = payload.get("done")
        if title is not None:
            title = str(title).strip()
            if not title:
                abort(400, description="title cannot be empty")
        if done is not None:
            done = _as_bool(done)
        task = store.update_task(task_id, title=title, done=done)
        if task is None:
            abort(404, description=f"task {task_id} not found")
        refresh_open_gauge()
        app.logger.info("task updated id=%s done=%s", task_id, task["done"])
        return jsonify(task)

    @app.delete("/api/tasks/<int:task_id>")
    def delete_task(task_id: int):
        if not store.delete_task(task_id):
            abort(404, description=f"task {task_id} not found")
        refresh_open_gauge()
        app.logger.info("task deleted id=%s", task_id)
        return "", 204

    return app


# `app` is what gunicorn imports: gunicorn app:app
app = create_app()


if __name__ == "__main__":
    # Development server only. Containers use gunicorn (see docker/Dockerfile).
    # Binding to all interfaces is required inside a container.
    port = app.config["PORT"]
    app.run(host="0.0.0.0", port=port)  # nosec B104
