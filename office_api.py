#!/usr/bin/env python3
"""Read-only local API bridge for the virtual office UI.

This service exposes the existing organization.db without importing orgx.Org,
running migrations, starting agents, or writing to the database.

Run:
  OFFICE_API_TOKEN='a-long-random-secret' python office_api.py

Optional:
  ORG_DB=/absolute/path/to/organization.db
  OFFICE_API_HOST=127.0.0.1
  OFFICE_API_PORT=8765
"""
import hmac
import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlparse, parse_qs

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("ORG_DB", str(ROOT / "organization.db"))).expanduser()
HOST = os.environ.get("OFFICE_API_HOST", "127.0.0.1")
PORT = int(os.environ.get("OFFICE_API_PORT", "8765"))
TOKEN = os.environ.get("OFFICE_API_TOKEN", "")

# Only known tables and fixed SQL are exposed. No client-supplied SQL is accepted.
TABLES = {
    "agents": "SELECT id,name,role,specialty,manager_id,status,created_at FROM agents ORDER BY id",
    "departments": "SELECT id,name,description,parent_department_id,manager_agent_id,status,created_at FROM departments ORDER BY id",
    "agent_departments": "SELECT id,agent_id,department_id,role,status,assigned_at FROM agent_departments ORDER BY id",
    "reporting_lines": "SELECT id,manager_agent_id,subordinate_agent_id,department_id,relation,created_at FROM reporting_lines ORDER BY id",
    "tasks": "SELECT id,title,description,assigned_to,status,created_at,department_id,parent_id,result,score,priority,updated_at,dept_hint FROM tasks ORDER BY id DESC LIMIT ?",
    "runs": "SELECT id,task_id,agent_id,status,steps,pending,created,updated FROM runs ORDER BY id DESC LIMIT ?",
    "approvals": "SELECT id,ts,kind,payload,status,decided_at,note FROM approvals ORDER BY id DESC LIMIT ?",
    "messages": "SELECT id,ts,sender,recipient,task_id,kind,body,is_read FROM messages ORDER BY id DESC LIMIT ?",
    "memories": "SELECT id,ts,scope,agent_id,topic,text,weight FROM memories ORDER BY id DESC LIMIT ?",
    "lessons": "SELECT id,ts,agent_id,task_id,text FROM lessons ORDER BY id DESC LIMIT ?",
    "reviews": "SELECT id,ts,task_id,reviewer,verdict,score,notes FROM reviews ORDER BY id DESC LIMIT ?",
    "steps": "SELECT id,ts,task_id,agent_id,n,thought,action,args,observation FROM steps ORDER BY id DESC LIMIT ?",
    "audit": "SELECT id,actor,action,details,created_at FROM audit ORDER BY id DESC LIMIT ?",
}


def connect_readonly():
    if not DB_PATH.is_file():
        raise FileNotFoundError("Database file not found: " + str(DB_PATH))
    uri = "file:" + quote(str(DB_PATH.resolve()), safe="/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def table_exists(conn, name):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def rows(conn, table, limit):
    if not table_exists(conn, table):
        return []
    sql = TABLES[table]
    if "LIMIT ?" in sql:
        found = conn.execute(sql, (limit,)).fetchall()
    else:
        found = conn.execute(sql).fetchall()
    result = []
    for row in found:
        item = dict(row)
        if table == "approvals":
            try:
                item["payload"] = json.loads(item.get("payload") or "{}")
            except (TypeError, ValueError):
                item["payload"] = {"raw": item.get("payload")}
        if table == "steps":
            for key in ("args",):
                try:
                    item[key] = json.loads(item.get(key) or "{}")
                except (TypeError, ValueError):
                    pass
        result.append(item)
    return result


def snapshot(limit=100):
    with connect_readonly() as conn:
        data = {name: rows(conn, name, limit) for name in TABLES}
        counts = {}
        for name in TABLES:
            if table_exists(conn, name):
                counts[name] = conn.execute(
                    'SELECT COUNT(*) FROM "' + name + '"'
                ).fetchone()[0]
            else:
                counts[name] = 0
        return {
            "ok": True,
            "mode": "read_only",
            "database": DB_PATH.name,
            "counts": counts,
            "data": data,
        }


class Handler(BaseHTTPRequestHandler):
    server_version = "OfficeReadOnlyBridge/0.1"

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        supplied = self.headers.get("Authorization", "")
        expected = "Bearer " + TOKEN
        if not TOKEN or not hmac.compare_digest(supplied, expected):
            self.send_json(401, {"ok": False, "error": "unauthorized"})
            return

        path = urlparse(self.path)
        if path.path == "/health":
            self.send_json(200, {"ok": True, "mode": "read_only"})
            return
        if path.path != "/api/office":
            self.send_json(404, {"ok": False, "error": "not_found"})
            return

        try:
            query = parse_qs(path.query)
            limit = int(query.get("limit", ["100"])[0])
            limit = max(1, min(limit, 250))
            self.send_json(200, snapshot(limit))
        except FileNotFoundError as exc:
            self.send_json(503, {"ok": False, "error": "database_unavailable", "detail": str(exc)})
        except sqlite3.Error:
            self.send_json(500, {"ok": False, "error": "database_read_failed"})
        except Exception:
            self.send_json(500, {"ok": False, "error": "internal_error"})

    def do_POST(self):
        self.send_json(405, {"ok": False, "error": "read_only_api"})

    def do_PUT(self):
        self.send_json(405, {"ok": False, "error": "read_only_api"})

    def do_DELETE(self):
        self.send_json(405, {"ok": False, "error": "read_only_api"})

    def log_message(self, fmt, *args):
        print("[office-api] " + (fmt % args))


def main():
    if not TOKEN or len(TOKEN) < 24:
        raise SystemExit("Set OFFICE_API_TOKEN to a secret of at least 24 characters.")
    if HOST not in ("127.0.0.1", "localhost"):
        raise SystemExit("For safety, this first version only binds to localhost.")
    # Validate the database before opening the listening socket.
    with connect_readonly() as conn:
        conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print("Read-only office API: http://%s:%d/api/office" % (HOST, PORT))
    print("Database: %s" % DB_PATH)
    print("No database writes or agent execution are enabled.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping office API...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
