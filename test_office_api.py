"""Focused regression tests for the read-only office API snapshot."""
import ast
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import office_api


class OfficeApiSnapshotTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        self.db_path = Path(handle.name)
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE agents (id INTEGER, name TEXT, role TEXT, specialty TEXT,
                manager_id INTEGER, status TEXT, created_at TEXT);
            INSERT INTO agents VALUES (1, 'CEO', 'chief', 'management', NULL, 'active', 'now');
            CREATE TABLE departments (id INTEGER, name TEXT, description TEXT, parent_department_id INTEGER,
                manager_agent_id INTEGER, status TEXT, created_at TEXT);
            INSERT INTO departments VALUES (1, 'Strategy', 'Planning', NULL, 1, 'active', 'now');
            CREATE TABLE agent_departments (id INTEGER, agent_id INTEGER, department_id INTEGER, role TEXT,
                status TEXT, assigned_at TEXT);
            INSERT INTO agent_departments VALUES (1, 1, 1, 'manager', 'active', 'now');
            CREATE TABLE tasks (id INTEGER, title TEXT, description TEXT, assigned_to INTEGER, status TEXT,
                created_at TEXT, department_id INTEGER, parent_id INTEGER, result TEXT, score REAL,
                priority TEXT, updated_at TEXT, dept_hint TEXT);
            INSERT INTO tasks VALUES (7, 'Test task', 'Task description', 1, 'assigned', 'now',
                1, NULL, '', NULL, 'high', 'now', '');
            CREATE TABLE approvals (id INTEGER, ts TEXT, kind TEXT, payload TEXT,
                status TEXT DEFAULT 'pending', decided_at TEXT, note TEXT);
            INSERT INTO approvals VALUES (1, '2026-11-12T00:00:00', 'create_agent',
                '{"name":"Test Agent","specialty":"QA"}', 'pending', NULL, NULL);
            CREATE TABLE runs (id INTEGER, task_id INTEGER, agent_id INTEGER, status TEXT,
                history TEXT, steps TEXT, pending TEXT, created TEXT, updated TEXT);
            INSERT INTO runs VALUES (1, 7, 1, 'done', '[{"event":"finished"}]', '[]', '{}', 'a', 'b');
            CREATE TABLE ceo_chat (id INTEGER, ts TEXT, role TEXT, content TEXT);
            INSERT INTO ceo_chat VALUES (1, 'now', 'assistant', 'Read-only test');
            CREATE TABLE ceo_feedback (id INTEGER, ts TEXT, source TEXT, item TEXT,
                feedback TEXT, outcome TEXT);
            INSERT INTO ceo_feedback VALUES (1, 'now', 'test', 'item', 'good', 'saved');
            CREATE TABLE ceo_notes (id INTEGER, ts TEXT, category TEXT, priority TEXT,
                source TEXT, status TEXT, title TEXT, details TEXT, recommendation TEXT,
                related_department INTEGER, related_task_id INTEGER);
            INSERT INTO ceo_notes VALUES (1, 'now', 'ops', 'low', 'test', 'open',
                'Note', 'Details', 'Review', NULL, NULL);
            CREATE TABLE schedules (id INTEGER, goal TEXT, every_s INTEGER, last_run TEXT,
                active INTEGER, created TEXT);
            INSERT INTO schedules VALUES (1, 'Daily review', 3600, NULL, 1, 'now');
            CREATE TABLE usage (day TEXT, calls INTEGER);
            INSERT INTO usage VALUES ('2026-11-12', 3);
            CREATE TABLE watches (id INTEGER, url TEXT, mode TEXT, keyword TEXT,
                every_s INTEGER, last_check TEXT, last_hash TEXT, last_state TEXT,
                last_text TEXT, active INTEGER, created TEXT);
            INSERT INTO watches VALUES (1, 'https://example.com', 'keyword', 'release',
                600, NULL, NULL, 'new', 'text', 1, 'now');
        """)
        conn.commit()
        conn.close()
        self.patch_db = patch.object(office_api, "DB_PATH", self.db_path)
        self.patch_db.start()

    def tearDown(self):
        self.patch_db.stop()
        self.db_path.unlink(missing_ok=True)

    def test_snapshot_includes_operational_and_ceo_data(self):
        result = office_api.snapshot(10)
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "read_only")
        self.assertEqual(len(result["data"]["agents"]), 1)
        self.assertEqual(result["data"]["departments"][0]["name"], "Strategy")
        self.assertEqual(result["data"]["agent_departments"][0]["role"], "manager")
        self.assertEqual(result["data"]["tasks"][0]["title"], "Test task")
        self.assertEqual(result["data"]["runs"][0]["history"], [{"event": "finished"}])
        for table in ("ceo_chat", "ceo_feedback", "ceo_notes", "schedules", "usage", "watches"):
            self.assertEqual(len(result["data"][table]), 1, table)
        self.assertEqual(result["data"]["approvals"][0]["status"], "pending")
        self.assertEqual(result["data"]["approvals"][0]["payload"]["name"], "Test Agent")

    def test_installer_script_is_valid_python(self):
        installer = Path(__file__).parent / "ui-bridge" / "apply_ui_patch.py"
        ast.parse(installer.read_text(encoding="utf-8"), filename=str(installer))

    def test_dashboard_source_is_separate_and_read_only(self):
        root = Path(__file__).parent
        installer = (root / "ui-bridge" / "apply_ui_patch.py").read_text(encoding="utf-8")
        dashboard = root / "ui-bridge" / "organization-page.tsx"
        self.assertTrue(dashboard.is_file())
        self.assertIn('ORG_PAGE_SOURCE = (REPO_ROOT / "ui-bridge" / "organization-page.tsx")', installer)
        source = dashboard.read_text(encoding="utf-8")
        self.assertIn("filteredTasks", source)
        self.assertIn("relatedRuns", source)
        self.assertIn("relatedReviews", source)
        self.assertNotIn("/api/office/actions", source)
        self.assertIn("جميع البيانات للعرض فقط", source)

    def test_database_connection_is_read_only(self):
        with office_api.connect_readonly() as conn:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("UPDATE agents SET name='changed' WHERE id=1")

    def test_limit_is_applied_to_limited_tables(self):
        result = office_api.snapshot(1)
        self.assertLessEqual(len(result["data"]["ceo_chat"]), 1)


if __name__ == "__main__":
    unittest.main()
