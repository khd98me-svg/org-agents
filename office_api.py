#!/usr/bin/env python3
"""Restricted local API bridge for the virtual office UI.

Reads organization.db without importing orgx.Org or running migrations. The only
write path edits approved profile text fields and records an audit entry.

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
from contextlib import closing
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
    "runs": "SELECT id,task_id,agent_id,status,history,steps,pending,created,updated FROM runs ORDER BY id DESC LIMIT ?",
    "approvals": "SELECT id,ts,kind,payload,status,decided_at,note FROM approvals ORDER BY id DESC LIMIT ?",
    "messages": "SELECT id,ts,sender,recipient,task_id,kind,body,is_read FROM messages ORDER BY id DESC LIMIT ?",
    "memories": "SELECT id,ts,scope,agent_id,topic,text,weight FROM memories ORDER BY id DESC LIMIT ?",
    "lessons": "SELECT id,ts,agent_id,task_id,text FROM lessons ORDER BY id DESC LIMIT ?",
    "reviews": "SELECT id,ts,task_id,reviewer,verdict,score,notes FROM reviews ORDER BY id DESC LIMIT ?",
    "steps": "SELECT id,ts,task_id,agent_id,n,thought,action,args,observation FROM steps ORDER BY id DESC LIMIT ?",
    "audit": "SELECT id,actor,action,details,created_at FROM audit ORDER BY id DESC LIMIT ?",
    "ceo_chat": "SELECT id,ts,role,content FROM ceo_chat ORDER BY id DESC LIMIT ?",
    "ceo_feedback": "SELECT id,ts,source,item,feedback,outcome FROM ceo_feedback ORDER BY id DESC LIMIT ?",
    "ceo_notes": "SELECT id,ts,category,priority,source,status,title,details,recommendation,related_department,related_task_id FROM ceo_notes ORDER BY id DESC LIMIT ?",
    "schedules": "SELECT id,goal,every_s,last_run,active,created FROM schedules ORDER BY id DESC LIMIT ?",
    "usage": "SELECT day,calls FROM usage ORDER BY day DESC LIMIT ?",
    "watches": "SELECT id,url,mode,keyword,every_s,last_check,last_hash,last_state,last_text,active,created FROM watches ORDER BY id DESC LIMIT ?",
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
        if table == "runs":
            for key in ("history", "steps", "pending"):
                try:
                    item[key] = json.loads(item.get(key) or "[]")
                except (TypeError, ValueError):
                    pass
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


def connect_writable():
    """Open the existing database for narrowly scoped, audited management writes."""
    if not DB_PATH.is_file():
        raise FileNotFoundError("Database file not found: " + str(DB_PATH))
    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _positive_id(value, field, nullable=False):
    if nullable and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("invalid_" + field)
    return value


def _agent_exists(conn, agent_id, field="agent"):
    row = conn.execute("SELECT status FROM agents WHERE id=?", (agent_id,)).fetchone()
    if not row:
        raise LookupError(field + "_not_found")
    if row["status"] != "active":
        raise ValueError(field + "_inactive")


def _would_create_agent_cycle(conn, agent_id, manager_id):
    if manager_id is None:
        return False
    row = conn.execute(
        """WITH RECURSIVE chain(id) AS (
             SELECT ?
             UNION
             SELECT a.manager_id FROM agents a JOIN chain c ON a.id=c.id
             WHERE a.manager_id IS NOT NULL
           )
           SELECT 1 FROM chain WHERE id=? LIMIT 1""",
        (manager_id, agent_id),
    ).fetchone()
    return row is not None


def _would_create_department_cycle(conn, department_id, parent_id):
    if parent_id is None:
        return False
    row = conn.execute(
        """WITH RECURSIVE chain(id) AS (
             SELECT ?
             UNION
             SELECT d.parent_department_id FROM departments d JOIN chain c ON d.id=c.id
             WHERE d.parent_department_id IS NOT NULL
           )
           SELECT 1 FROM chain WHERE id=? LIMIT 1""",
        (parent_id, department_id),
    ).fetchone()
    return row is not None


def manage_task(payload):
    """Create and assign tasks only; never starts an agent run."""
    operation = payload.get("operation")
    if operation == "task_create":
        allowed = {"operation", "confirm", "title", "description", "department_id", "priority"}
        if set(payload) - allowed:
            raise ValueError("unsupported_fields")
        title = payload.get("title")
        description = payload.get("description", "")
        priority = payload.get("priority", "normal")
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 200:
            raise ValueError("invalid_title")
        if not isinstance(description, str) or len(description) > 2000:
            raise ValueError("invalid_description")
        if priority not in ("low", "normal", "high", "urgent"):
            raise ValueError("invalid_priority")
        department_id = _positive_id(payload.get("department_id"), "department_id", nullable=True)
        with closing(connect_writable()) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            if not table_exists(conn, "tasks") or not table_exists(conn, "audit"):
                raise RuntimeError("task_tables_missing")
            if department_id is not None:
                dept = conn.execute("SELECT status FROM departments WHERE id=?", (department_id,)).fetchone()
                if not dept or dept["status"] != "active":
                    raise ValueError("department_not_found_or_inactive")
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")}
            required = {"title", "description", "assigned_to", "status", "created_at", "department_id", "parent_id", "priority", "updated_at", "dept_hint"}
            if not required.issubset(columns):
                raise RuntimeError("task_schema_incomplete")
            cur = conn.execute(
                """INSERT INTO tasks(title,description,assigned_to,status,created_at,department_id,parent_id,priority,updated_at,dept_hint)
                   VALUES(?,?,NULL,'pending',datetime('now'),?,NULL,?,datetime('now'),'')""",
                (title.strip(), description.strip(), department_id, priority),
            )
            task_id = cur.lastrowid
            conn.execute(
                "INSERT INTO audit(actor,action,details,created_at) VALUES('owner','task_created',?,datetime('now'))",
                ("id=%d %s" % (task_id, title.strip()[:80]),),
            )
            conn.commit()
        return {"ok": True, "operation": operation, "id": task_id, "status": "pending"}

    if operation == "task_assign":
        allowed = {"operation", "id", "assigned_to", "confirm"}
        if set(payload) - allowed:
            raise ValueError("unsupported_fields")
        task_id = _positive_id(payload.get("id"), "id")
        agent_id = _positive_id(payload.get("assigned_to"), "assigned_to", nullable=True)
        with closing(connect_writable()) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            if not table_exists(conn, "tasks") or not table_exists(conn, "audit"):
                raise RuntimeError("task_tables_missing")
            task = conn.execute("SELECT title,description,status,assigned_to FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not task:
                raise LookupError("task_not_found")
            if task["status"] not in ("pending", "assigned", "blocked"):
                raise ValueError("task_locked")
            if agent_id is not None:
                _agent_exists(conn, agent_id, "assignee")
            if task["assigned_to"] == agent_id:
                raise ValueError("no_changes")
            next_status = "assigned" if agent_id is not None else "pending"
            conn.execute(
                "UPDATE tasks SET assigned_to=?,status=?,updated_at=datetime('now') WHERE id=?",
                (agent_id, next_status, task_id),
            )
            if agent_id is not None:
                if not table_exists(conn, "messages"):
                    raise RuntimeError("messages_table_missing")
                body = "مهمة جديدة #%d: %s\\n%s" % (task_id, task["title"], task["description"] or "")
                conn.execute(
                    "INSERT INTO messages(ts,sender,recipient,task_id,kind,body,is_read) VALUES(datetime('now'),NULL,?,?,'task',?,0)",
                    (agent_id, task_id, body[:2000]),
                )
                action = "task_assigned"
                details = "task=%d agent=%d" % (task_id, agent_id)
            else:
                action = "task_unassigned"
                details = "task=%d previous_agent=%s" % (task_id, task["assigned_to"])
            conn.execute(
                "INSERT INTO audit(actor,action,details,created_at) VALUES('owner',?,?,datetime('now'))",
                (action, details),
            )
            conn.commit()
        return {"ok": True, "operation": operation, "id": task_id, "assigned_to": agent_id, "status": next_status}

    raise ValueError("unsupported_operation")


def update_profile(payload):
    """Apply narrowly allowlisted, owner-confirmed profile or hierarchy changes."""
    if not isinstance(payload, dict):
        raise ValueError("invalid_payload")
    operation = payload.get("operation")
    if operation in ("task_create", "task_assign"):
        return manage_task(payload)
    entity_id = _positive_id(payload.get("id"), "id")

    profile_limits = {
        "agent_profile": {"name": 80, "specialty": 200},
        "department_profile": {"name": 80, "description": 500},
    }
    hierarchy_allowed = {
        "agent_hierarchy": {"manager_id", "department_ids"},
        "department_hierarchy": {"parent_department_id"},
    }
    if operation not in profile_limits and operation not in hierarchy_allowed:
        raise ValueError("unsupported_operation")

    if operation in profile_limits:
        fields = profile_limits[operation]
        allowed = {"operation", "id", "confirm"} | set(fields)
        if set(payload) - allowed:
            raise ValueError("unsupported_fields")
        values = {}
        for key, maximum in fields.items():
            if key in payload:
                value = payload[key]
                if not isinstance(value, str):
                    raise ValueError("invalid_" + key)
                value = value.strip()
                if not value or len(value) > maximum:
                    raise ValueError("invalid_" + key)
                values[key] = value
        if not values:
            raise ValueError("no_changes")

        table = "agents" if operation == "agent_profile" else "departments"
        with closing(connect_writable()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            exists = conn.execute("SELECT 1 FROM " + table + " WHERE id=?", (entity_id,)).fetchone()
            if not exists:
                raise LookupError("not_found")
            if operation == "agent_profile":
                if "name" in values:
                    conn.execute("UPDATE agents SET name=? WHERE id=?", (values["name"], entity_id))
                if "specialty" in values:
                    conn.execute("UPDATE agents SET specialty=? WHERE id=?", (values["specialty"], entity_id))
            else:
                if "name" in values:
                    duplicate = conn.execute("SELECT 1 FROM departments WHERE name=? AND id<>?",
                                             (values["name"], entity_id)).fetchone()
                    if duplicate:
                        raise ValueError("department_name_exists")
                    conn.execute("UPDATE departments SET name=? WHERE id=?", (values["name"], entity_id))
                if "description" in values:
                    conn.execute("UPDATE departments SET description=? WHERE id=?", (values["description"], entity_id))
            if not table_exists(conn, "audit"):
                raise RuntimeError("audit_table_missing")
            conn.execute(
                "INSERT INTO audit(actor,action,details,created_at) VALUES(?,?,?,datetime('now'))",
                ("owner", operation + "_updated",
                 "id=%d fields=%s" % (entity_id, ",".join(sorted(values)))),
            )
            conn.commit()
        return {"ok": True, "operation": operation, "id": entity_id, "updated_fields": sorted(values)}

    allowed = {"operation", "id", "confirm"} | hierarchy_allowed[operation]
    if set(payload) - allowed:
        raise ValueError("unsupported_fields")

    with closing(connect_writable()) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN IMMEDIATE")
        if not table_exists(conn, "audit"):
            raise RuntimeError("audit_table_missing")

        if operation == "agent_hierarchy":
            if not table_exists(conn, "agent_departments") or not table_exists(conn, "reporting_lines"):
                raise RuntimeError("organization_relations_missing")
            if not conn.execute("SELECT 1 FROM agents WHERE id=?", (entity_id,)).fetchone():
                raise LookupError("agent_not_found")

            old_manager = conn.execute("SELECT manager_id FROM agents WHERE id=?", (entity_id,)).fetchone()["manager_id"]
            new_manager = old_manager
            if "manager_id" in payload:
                new_manager = _positive_id(payload["manager_id"], "manager_id", nullable=True)
                if new_manager is not None:
                    if new_manager == entity_id:
                        raise ValueError("agent_cannot_manage_itself")
                    _agent_exists(conn, new_manager, "manager")
                    if _would_create_agent_cycle(conn, entity_id, new_manager):
                        raise ValueError("agent_reporting_cycle")

            old_departments = [row["department_id"] for row in conn.execute(
                "SELECT department_id FROM agent_departments WHERE agent_id=? AND status='active' ORDER BY department_id",
                (entity_id,),
            ).fetchall()]
            new_departments = old_departments
            if "department_ids" in payload:
                raw_ids = payload["department_ids"]
                if not isinstance(raw_ids, list):
                    raise ValueError("invalid_department_ids")
                new_departments = []
                for value in raw_ids:
                    did = _positive_id(value, "department_id")
                    if did in new_departments:
                        raise ValueError("duplicate_department_id")
                    new_departments.append(did)
                new_departments.sort()
                if new_departments:
                    placeholders = ",".join("?" for _ in new_departments)
                    found = {row["id"] for row in conn.execute(
                        "SELECT id FROM departments WHERE status='active' AND id IN (" + placeholders + ")",
                        tuple(new_departments),
                    ).fetchall()}
                    if found != set(new_departments):
                        raise ValueError("department_not_found_or_inactive")
                removed = set(old_departments) - set(new_departments)
                for did in removed:
                    is_manager = conn.execute(
                        "SELECT 1 FROM departments WHERE id=? AND manager_agent_id=?",
                        (did, entity_id),
                    ).fetchone()
                    if is_manager:
                        raise ValueError("cannot_remove_department_manager")

            if "manager_id" in payload:
                conn.execute("UPDATE agents SET manager_id=? WHERE id=?", (new_manager, entity_id))

            if "department_ids" in payload:
                conn.execute(
                    "UPDATE agent_departments SET status='inactive' WHERE agent_id=? AND status='active'",
                    (entity_id,),
                )
                for did in new_departments:
                    conn.execute(
                        """INSERT INTO agent_departments(agent_id,department_id,role,status)
                           VALUES(?,?,'member','active')
                           ON CONFLICT(agent_id,department_id) DO UPDATE SET status='active'""",
                        (entity_id, did),
                    )

            if "manager_id" in payload or "department_ids" in payload:
                conn.execute("DELETE FROM reporting_lines WHERE subordinate_agent_id=?", (entity_id,))
                if new_manager is not None:
                    # reporting_lines has UNIQUE(manager_agent_id, subordinate_agent_id),
                    # so keep one representative department link for this manager pair.
                    reporting_department = new_departments[0] if new_departments else None
                    conn.execute(
                        """INSERT OR IGNORE INTO reporting_lines
                           (manager_agent_id,subordinate_agent_id,department_id,relation)
                           VALUES(?,?,?,'reports_to')""",
                        (new_manager, entity_id, reporting_department),
                    )

            changed = []
            if "manager_id" in payload and new_manager != old_manager:
                changed.append("manager_id:%s->%s" % (old_manager, new_manager))
            if "department_ids" in payload and new_departments != old_departments:
                changed.append("departments:%s->%s" % (
                    ",".join(map(str, old_departments)), ",".join(map(str, new_departments))
                ))
            if not changed:
                raise ValueError("no_changes")
            action = "agent_hierarchy_updated"
            details = "agent=%d %s" % (entity_id, " ".join(changed))

        else:
            if not table_exists(conn, "departments"):
                raise RuntimeError("departments_table_missing")
            row = conn.execute(
                "SELECT parent_department_id FROM departments WHERE id=?", (entity_id,)
            ).fetchone()
            if not row:
                raise LookupError("department_not_found")
            new_parent = _positive_id(payload.get("parent_department_id"), "parent_department_id", nullable=True)
            if new_parent is not None:
                if new_parent == entity_id:
                    raise ValueError("department_cannot_parent_itself")
                parent = conn.execute(
                    "SELECT status FROM departments WHERE id=?", (new_parent,)
                ).fetchone()
                if not parent or parent["status"] != "active":
                    raise ValueError("parent_department_not_found_or_inactive")
                if _would_create_department_cycle(conn, entity_id, new_parent):
                    raise ValueError("department_hierarchy_cycle")
            old_parent = row["parent_department_id"]
            if new_parent == old_parent:
                raise ValueError("no_changes")
            conn.execute(
                "UPDATE departments SET parent_department_id=? WHERE id=?",
                (new_parent, entity_id),
            )
            action = "department_hierarchy_updated"
            details = "department=%d parent:%s->%s" % (entity_id, old_parent, new_parent)

        conn.execute(
            "INSERT INTO audit(actor,action,details,created_at) VALUES('owner',?,?,datetime('now'))",
            (action, details[:500]),
        )
        conn.commit()

    return {"ok": True, "operation": operation, "id": entity_id, "details": details}


class Handler(BaseHTTPRequestHandler):
    server_version = "OfficeManagementBridge/0.2"

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
        supplied = self.headers.get("Authorization", "")
        expected = "Bearer " + TOKEN
        if not TOKEN or not hmac.compare_digest(supplied, expected):
            self.send_json(401, {"ok": False, "error": "unauthorized"})
            return
        if urlparse(self.path).path != "/api/office/manage":
            self.send_json(404, {"ok": False, "error": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 2 or length > 8192:
                self.send_json(413, {"ok": False, "error": "invalid_body_size"})
                return
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict) or payload.get("confirm") is not True:
                self.send_json(403, {"ok": False, "error": "explicit_confirmation_required"})
                return
            result = update_profile(payload)
            self.send_json(200, result)
        except LookupError:
            self.send_json(404, {"ok": False, "error": "not_found"})
        except ValueError as exc:
            self.send_json(400, {"ok": False, "error": str(exc)})
        except sqlite3.IntegrityError:
            self.send_json(409, {"ok": False, "error": "conflict"})
        except FileNotFoundError:
            self.send_json(503, {"ok": False, "error": "database_unavailable"})
        except Exception:
            self.send_json(500, {"ok": False, "error": "management_write_failed"})

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
    print("Local office API: http://%s:%d/api/office" % (HOST, PORT))
    print("Database: %s" % DB_PATH)
    print("Owner-confirmed agent/department profile edits and task creation/assignment are enabled; task execution and agent runs remain disabled.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping office API...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
