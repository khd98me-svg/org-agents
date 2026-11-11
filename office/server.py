#!/usr/bin/env python3
"""Read-only local API for the Org Agents virtual office.

Run with:
  OFFICE_DB=/path/to/organization.db OFFICE_TOKEN='long-random-token' python office/server.py

The server binds to loopback by default and never writes to the database.
"""
import hmac
import json
import os
import sqlite3
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlparse

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("OFFICE_DB", os.environ.get("ORG_DB", ROOT.parent / "organization.db"))).expanduser()
SNAPSHOT_PATH = Path(os.environ["OFFICE_SNAPSHOT"]).expanduser() if os.environ.get("OFFICE_SNAPSHOT") else None
TOKEN = os.environ.get("OFFICE_TOKEN", "")
HOST = "127.0.0.1"  # Loopback only; do not expose the API to the network by default
PORT = int(os.environ.get("OFFICE_PORT", "8765"))

STATUS_AR = {
    "pending": "بانتظار مسؤول", "assigned": "مسندة", "submitted": "بانتظار المراجعة",
    "blocked": "متوقفة بانتظارك", "done": "منجزة", "rejected": "مرفوضة",
}
RUN_AR = {
    "running": "يعمل", "waiting_approval": "ينتظر موافقتك", "waiting_owner": "ينتظر ردّك",
    "waiting_team": "ينتظر فريقه", "paused": "متوقف مؤقتاً", "done": "سلّم",
    "failed": "فشل", "stopped": "أُوقف",
}


def db_read():
    path = DB_PATH.resolve()
    uri = "file:" + quote(path.as_posix(), safe="/:") + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


def rows(con, sql, args=()):
    return [dict(r) for r in con.execute(sql, args).fetchall()]


def sanitize_snapshot(data):
    """Return only explicitly approved dashboard fields; never trust snapshot JSON."""
    fields = {
        "agents": ("id", "name", "role", "specialty", "manager_id", "status", "department_id", "department"),
        "departments": ("id", "name", "description", "parent_department_id", "manager_agent_id", "manager_name", "status"),
        "tasks": ("id", "title", "status", "assigned_to", "assignee", "department_id", "department",
                  "parent_id", "priority", "created_at", "updated_at", "status_label"),
        "approvals": ("id", "kind", "status", "ts"),
        "runs": ("id", "task_id", "agent_id", "status", "steps", "created", "updated", "task_title",
                 "agent_name", "status_label"),
    }
    if not isinstance(data, dict) or data.get("read_only") is not True:
        raise RuntimeError("لقطة المكتب غير صالحة أو ليست للقراءة فقط")
    clean = {"source": "private_snapshot", "read_only": True}
    for key, allowed in fields.items():
        values = data.get(key)
        if not isinstance(values, list):
            raise RuntimeError("لقطة المكتب ناقصة أو غير صالحة: " + key)
        if len(values) > (100 if key in ("agents", "departments") else 100):
            raise RuntimeError("لقطة المكتب تتجاوز الحد المسموح: " + key)
        clean[key] = []
        for item in values:
            if not isinstance(item, dict):
                raise RuntimeError("عنصر غير صالح في لقطة المكتب: " + key)
            row = {}
            for name in allowed:
                value = item.get(name)
                if value is None or isinstance(value, (str, int, float, bool)):
                    if isinstance(value, str):
                        value = value[:2000]
                    row[name] = value
            clean[key].append(row)
    counts = data.get("counts")
    count_keys = ("agents", "active_agents", "open_tasks", "pending_approvals", "active_runs")
    if not isinstance(counts, dict) or any(
        not isinstance(counts.get(k), int) or counts[k] < 0 for k in count_keys
    ):
        raise RuntimeError("عدادات لقطة المكتب غير صالحة")
    clean["counts"] = {k: counts[k] for k in count_keys}
    return clean


def snapshot():
    if SNAPSHOT_PATH is not None:
        try:
            data = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("تعذر قراءة لقطة المكتب المحلية") from exc
        if not isinstance(data, dict) or data.get("read_only") is not True:
            raise RuntimeError("لقطة المكتب غير صالحة أو ليست للقراءة فقط")
        return sanitize_snapshot(data)
    with closing(db_read()) as con:
        tables = {r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {"agents", "departments", "tasks", "approvals", "runs"}
        missing = sorted(required - tables)
        if missing:
            raise RuntimeError("قاعدة البيانات لا تحتوي الجداول المطلوبة: " + ", ".join(missing))

        agents = rows(con, """
            SELECT a.id,a.name,a.role,a.specialty,a.manager_id,a.status,
                   d.id AS department_id,d.name AS department
            FROM agents a
            LEFT JOIN agent_departments ad ON ad.agent_id=a.id AND ad.status='active'
            LEFT JOIN departments d ON d.id=ad.department_id AND d.status='active'
            ORDER BY a.id
        """)
        departments = rows(con, """
            SELECT d.id,d.name,d.description,d.parent_department_id,d.manager_agent_id,
                   a.name AS manager_name,d.status
            FROM departments d LEFT JOIN agents a ON a.id=d.manager_agent_id
            WHERE d.status='active' ORDER BY d.id
        """)
        tasks = rows(con, """
            SELECT t.id,t.title,t.status,t.assigned_to,a.name AS assignee,
                   t.department_id,d.name AS department,t.parent_id,t.priority,
                   t.created_at,t.updated_at
            FROM tasks t
            LEFT JOIN agents a ON a.id=t.assigned_to
            LEFT JOIN departments d ON d.id=t.department_id
            ORDER BY t.id DESC LIMIT 100
        """)
        approvals = rows(con, """
            SELECT id,kind,status,ts FROM approvals
            WHERE status='pending' ORDER BY id DESC LIMIT 50
        """)
        runs = rows(con, """
            SELECT r.id,r.task_id,r.agent_id,r.status,r.steps,r.created,r.updated,
                   t.title AS task_title,a.name AS agent_name
            FROM runs r LEFT JOIN tasks t ON t.id=r.task_id
            LEFT JOIN agents a ON a.id=r.agent_id
            ORDER BY r.id DESC LIMIT 50
        """)
        for item in tasks:
            item["status_label"] = STATUS_AR.get(item["status"], item["status"])
        for item in runs:
            item["status_label"] = RUN_AR.get(item["status"], item["status"])
        return {
            "source": "organization.db",
            "read_only": True,
            "agents": agents,
            "departments": departments,
            "tasks": tasks,
            "approvals": approvals,
            "runs": runs,
            "counts": {
                "agents": len(agents),
                "active_agents": sum(1 for a in agents if a["status"] == "active"),
                "open_tasks": sum(1 for t in tasks if t["status"] not in ("done", "rejected")),
                "pending_approvals": len(approvals),
                "active_runs": sum(1 for r in runs if r["status"] in ("running", "waiting_approval", "waiting_owner", "waiting_team")),
            },
        }


class Handler(BaseHTTPRequestHandler):
    server_version = "OrgOfficeReadOnly/1.0"

    def send_bytes(self, code, body, content_type):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        supplied = self.headers.get("Authorization", "")
        expected = "Bearer " + TOKEN
        return bool(TOKEN) and hmac.compare_digest(supplied, expected)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            try:
                self.send_bytes(200, (ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")
            except OSError:
                self.send_bytes(404, "لم يُعثر على واجهة المكتب", "text/plain; charset=utf-8")
            return
        if path.startswith("/api/"):
            if not self.authorized():
                self.send_bytes(401, '{"error":"unauthorized"}', "application/json; charset=utf-8")
                return
            if path == "/api/health":
                self.send_bytes(200, json.dumps({"ok": True, "read_only": True}, ensure_ascii=False), "application/json; charset=utf-8")
                return
            if path == "/api/snapshot":
                try:
                    data = snapshot()
                    self.send_bytes(200, json.dumps(data, ensure_ascii=False), "application/json; charset=utf-8")
                except Exception as exc:
                    self.send_bytes(503, json.dumps({"error": str(exc)}, ensure_ascii=False), "application/json; charset=utf-8")
                return
            self.send_bytes(404, '{"error":"not_found"}', "application/json; charset=utf-8")
            return
        self.send_bytes(404, "غير موجود", "text/plain; charset=utf-8")

    def do_POST(self):
        self.send_bytes(405, '{"error":"read_only"}', "application/json; charset=utf-8")

    def do_PUT(self):
        self.send_bytes(405, '{"error":"read_only"}', "application/json; charset=utf-8")

    def do_DELETE(self):
        self.send_bytes(405, '{"error":"read_only"}', "application/json; charset=utf-8")

    def log_message(self, fmt, *args):
        print("[office-api] " + fmt % args)


if __name__ == "__main__":
    if len(TOKEN) < 32:
        raise SystemExit("اضبط OFFICE_TOKEN عشوائيًا بطول 32 حرفًا على الأقل؛ لن يبدأ الخادم بدونه.")
    if SNAPSHOT_PATH is None and not DB_PATH.is_file():
        raise SystemExit("قاعدة البيانات غير موجودة: " + str(DB_PATH))
    if SNAPSHOT_PATH is not None and not SNAPSHOT_PATH.is_file():
        raise SystemExit("لقطة المكتب غير موجودة: " + str(SNAPSHOT_PATH))
    print("Office API read-only: http://%s:%d" % (HOST, PORT))
    print("Database: " + str(DB_PATH))
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
