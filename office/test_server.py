import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server
from orgx import Org


class OfficeSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "test-organization.db"
        self.org = Org(db=str(self.db_path))
        self.agent_id = self.org.x(
            "INSERT INTO agents(name,role,specialty,status,created_at) VALUES(?,?,?,?,?)",
            ("موظف اختبار", "باحث", "اختبار الواجهة", "active", "2026-11-11T00:00:00"),
        )
        self.department_id = self.org.x(
            "INSERT INTO departments(name,description,status) VALUES(?,?,?)",
            ("قسم الاختبار", "بيانات مؤقتة للاختبار", "active"),
        )
        self.org.x(
            "INSERT INTO agent_departments(agent_id,department_id,status) VALUES(?,?,?)",
            (self.agent_id, self.department_id, "active"),
        )
        self.task_id = self.org.x(
            """INSERT INTO tasks(title,assigned_to,status,created_at,department_id,priority,updated_at)
               VALUES(?,?,?,?,?,?,?)""",
            ("مهمة اختبار", self.agent_id, "assigned", "2026-11-11T00:00:00",
             self.department_id, "normal", "2026-11-11T00:00:00"),
        )
        self.org.x(
            "INSERT INTO approvals(ts,kind,payload,status) VALUES(?,?,?,?)",
            ("2026-11-11T00:00:00", "test", "private-payload-must-not-leak", "pending"),
        )
        self.org.x(
            "INSERT INTO runs(task_id,agent_id,status,steps,created,updated) VALUES(?,?,?,?,?,?)",
            (self.task_id, self.agent_id, "running", 2, "2026-11-11T00:00:00", "2026-11-11T00:00:00"),
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_snapshot_returns_expected_entities_without_private_payloads(self):
        with patch.object(server, "DB_PATH", self.db_path):
            data = server.snapshot()
        self.assertEqual(data["counts"]["agents"], 1)
        self.assertEqual(data["counts"]["open_tasks"], 1)
        self.assertEqual(data["counts"]["pending_approvals"], 1)
        self.assertEqual(data["counts"]["active_runs"], 1)
        self.assertEqual(data["agents"][0]["name"], "موظف اختبار")
        self.assertEqual(data["tasks"][0]["title"], "مهمة اختبار")
        self.assertNotIn("payload", data["approvals"][0])
        self.assertNotIn("private-payload-must-not-leak", repr(data))

    def test_database_connection_is_read_only(self):
        with patch.object(server, "DB_PATH", self.db_path):
            with server.db_read() as con:
                with self.assertRaises(Exception):
                    con.execute("UPDATE agents SET name='changed' WHERE id=?", (self.agent_id,))
            check = self.org.q("SELECT name FROM agents WHERE id=?", (self.agent_id,))
        self.assertEqual(check[0][0], "موظف اختبار")

    def test_snapshot_rejects_incomplete_database(self):
        empty_db = Path(self.temp.name) / "empty.db"
        import sqlite3
        sqlite3.connect(empty_db).close()
        with patch.object(server, "DB_PATH", empty_db):
            with self.assertRaisesRegex(RuntimeError, "الجداول المطلوبة"):
                server.snapshot()


if __name__ == "__main__":
    unittest.main()
