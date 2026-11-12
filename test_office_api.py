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
            CREATE TABLE audit (id INTEGER PRIMARY KEY, actor TEXT, action TEXT, details TEXT, created_at TEXT);
            CREATE TABLE agents (id INTEGER, name TEXT, role TEXT, specialty TEXT,
                manager_id INTEGER, status TEXT, created_at TEXT);
            INSERT INTO agents VALUES (1, 'CEO', 'chief', 'management', NULL, 'active', 'now');
            INSERT INTO agents VALUES (2, 'Manager', 'manager', 'operations', 1, 'active', 'now');
            INSERT INTO agents VALUES (3, 'Worker', 'worker', 'support', 2, 'active', 'now');
            CREATE TABLE departments (id INTEGER, name TEXT, description TEXT, parent_department_id INTEGER,
                manager_agent_id INTEGER, status TEXT, created_at TEXT);
            INSERT INTO departments VALUES (1, 'Strategy', 'Planning', NULL, 1, 'active', 'now');
            INSERT INTO departments VALUES (2, 'Operations', 'Delivery', NULL, NULL, 'active', 'now');
            CREATE TABLE agent_departments (id INTEGER PRIMARY KEY, agent_id INTEGER, department_id INTEGER, role TEXT,
                status TEXT, assigned_at TEXT, UNIQUE(agent_id, department_id));
            CREATE TABLE reporting_lines (id INTEGER PRIMARY KEY, manager_agent_id INTEGER NOT NULL,
                subordinate_agent_id INTEGER NOT NULL, department_id INTEGER, relation TEXT, created_at TEXT,
                UNIQUE(manager_agent_id, subordinate_agent_id));
            INSERT INTO agent_departments VALUES (1, 1, 1, 'manager', 'active', 'now');
            INSERT INTO agent_departments VALUES (2, 2, 1, 'manager', 'active', 'now');
            INSERT INTO reporting_lines VALUES (1, 1, 2, 1, 'reports_to', 'now');
            INSERT INTO reporting_lines VALUES (2, 2, 3, 1, 'reports_to', 'now');
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

    def test_bridge_launcher_is_valid_python(self):
        launcher = Path(__file__).parent / "run_office_api.py"
        ast.parse(launcher.read_text(encoding="utf-8"), filename=str(launcher))

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
        self.assertIn("التعديل محصور في الأسماء والأوصاف", source)

    def test_agent_profiles_are_read_only_and_linked_to_org_records(self):
        root = Path(__file__).parent
        route = (root / "ui-bridge" / "office-route.ts").read_text(encoding="utf-8")
        dashboard = (root / "ui-bridge" / "organization-page.tsx").read_text(encoding="utf-8")
        self.assertIn("const enrichedAgents = agents.map", route)
        self.assertIn("reportsTo, directReports", route)
        self.assertIn("ownTasks", route)
        self.assertIn("ownRuns", route)
        self.assertIn("ownReviews", route)
        self.assertIn("const agentKey = /^agent(\\d+)$/i.exec(reviewer)", route)
        self.assertIn("(agentKey !== null && agentKey[1] === id)", route)
        self.assertIn("['agents', 'الوكلاء', agents.length]", dashboard)
        self.assertIn("تعديل بيانات الوكيل", dashboard)
        self.assertIn("تعديل الإدارة", dashboard)
        self.assertIn("سجل التدقيق", dashboard)
        self.assertIn("activityLog.map", dashboard)
        self.assertIn("لا يتيح تعديل الأحداث أو حذفها", dashboard)
        self.assertIn("confirm: true", dashboard)
        self.assertIn("/api/office/manage", dashboard)
        self.assertNotIn("/api/office/agents", dashboard)
        self.assertNotIn("method: 'POST'", route)
        manage = (root / "ui-bridge" / "manage-route.ts").read_text(encoding="utf-8")
        self.assertIn("same_origin_required", manage)
        self.assertIn("explicit_confirmation_required", manage)
        installer = (root / "ui-bridge" / "apply_ui_patch.py").read_text(encoding="utf-8")
        self.assertIn("MANAGE_ROUTE", installer)


    def test_agent_and_department_directories_show_searchable_hierarchy_context(self):
        root = Path(__file__).parent
        route = (root / "ui-bridge" / "office-route.ts").read_text(encoding="utf-8")
        dashboard = (root / "ui-bridge" / "organization-page.tsx").read_text(encoding="utf-8")
        self.assertIn("const managerRecord = agent.manager_id == null ? null", route)
        self.assertIn("managerRecord, departments: memberships", route)
        self.assertIn("parent: dept.parent_department_id == null ? null", route)
        self.assertIn("departmentQuery", dashboard)
        self.assertIn("agentQuery", dashboard)
        self.assertIn("filteredDepartments.map", dashboard)
        self.assertIn("filteredAgents.map", dashboard)
        self.assertIn("الإدارة الأعلى:", dashboard)
        self.assertIn("المدير المسجل في ملف الوكيل:", dashboard)
        self.assertIn("دور العضوية:", dashboard)
        self.assertIn("لا تعرض مصفوفة صلاحيات تقنية مستقلة", dashboard)
        self.assertNotIn("manager_agent_id: payload", route)
        self.assertNotIn("method: 'POST'", route)

    def test_audit_log_is_enriched_and_filterable_without_write_controls(self):
        root = Path(__file__).parent
        route = (root / "ui-bridge" / "office-route.ts").read_text(encoding="utf-8")
        dashboard = (root / "ui-bridge" / "organization-page.tsx").read_text(encoding="utf-8")
        self.assertIn("id: String(item.id ?? '')", route)
        self.assertIn("action: String(item.action || 'unknown')", route)
        self.assertIn("details: String(item.details || '')", route)
        self.assertIn("agentNames.get(actorId[1])", route)
        for marker in (
            "auditQuery", "auditActionFilter", "auditActorFilter",
            "auditFrom", "auditTo", "auditSort", "filteredAuditLog",
            "مسح عوامل التصفية", "التفاصيل:", "يعرض ",
        ):
            self.assertIn(marker, dashboard)
        audit_section = dashboard.split("{tab === 'audit' &&", 1)[1].split("{tab === 'reviews' &&", 1)[0]
        self.assertNotIn("method: 'POST'", audit_section)
        self.assertNotIn("fetch(", audit_section)
        self.assertIn("activityLog", dashboard)

    def test_owner_confirmed_profile_updates_are_allowlisted_and_audited(self):
        result = office_api.update_profile({
            "operation": "agent_profile", "id": 1,
            "name": "Updated CEO", "specialty": "Updated specialty",
        })
        self.assertEqual(result["updated_fields"], ["name", "specialty"])
        with office_api.connect_readonly() as conn:
            row = conn.execute("SELECT name,specialty,role,status FROM agents WHERE id=1").fetchone()
            self.assertEqual(tuple(row), ("Updated CEO", "Updated specialty", "chief", "active"))
            audit = conn.execute("SELECT actor,action,details FROM audit").fetchone()
            self.assertEqual(audit["actor"], "owner")
            self.assertEqual(audit["action"], "agent_profile_updated")
            self.assertIn("name,specialty", audit["details"])

    def test_department_profile_update_and_duplicate_name_rejection(self):
        result = office_api.update_profile({
            "operation": "department_profile", "id": 1,
            "name": "New Strategy", "description": "Updated description",
        })
        self.assertEqual(result["operation"], "department_profile")
        with office_api.connect_readonly() as conn:
            row = conn.execute("SELECT name,description,manager_agent_id FROM departments WHERE id=1").fetchone()
            self.assertEqual(tuple(row), ("New Strategy", "Updated description", 1))
        with self.assertRaises(ValueError):
            office_api.update_profile({"operation": "department_profile", "id": 1, "manager_agent_id": 99})
        with self.assertRaises(ValueError):
            office_api.update_profile({"operation": "department_profile", "id": 1, "name": "Operations"})

    def test_profile_updates_reject_unknown_fields_and_missing_entities(self):
        with self.assertRaises(ValueError):
            office_api.update_profile({"operation": "agent_profile", "id": 1, "name": "New name", "role": "CEO"})
        with self.assertRaises(LookupError):
            office_api.update_profile({"operation": "agent_profile", "id": 999, "name": "Missing"})

    def test_database_connection_is_read_only(self):
        with office_api.connect_readonly() as conn:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("UPDATE agents SET name='changed' WHERE id=1")

    def test_limit_is_applied_to_limited_tables(self):
        result = office_api.snapshot(1)
        self.assertLessEqual(len(result["data"]["ceo_chat"]), 1)


    def test_owner_confirmed_agent_hierarchy_update_syncs_memberships_and_reporting_lines(self):
        result = office_api.update_profile({
            "operation": "agent_hierarchy", "id": 3,
            "manager_id": 1, "department_ids": [1, 2],
        })
        self.assertEqual(result["operation"], "agent_hierarchy")
        with office_api.connect_readonly() as conn:
            agent = conn.execute("SELECT manager_id FROM agents WHERE id=3").fetchone()
            self.assertEqual(agent["manager_id"], 1)
            memberships = conn.execute(
                "SELECT department_id,status FROM agent_departments WHERE agent_id=3 ORDER BY department_id"
            ).fetchall()
            self.assertEqual([(r["department_id"], r["status"]) for r in memberships], [(1, "active"), (2, "active")])
            lines = conn.execute(
                "SELECT manager_agent_id,department_id FROM reporting_lines WHERE subordinate_agent_id=3 ORDER BY department_id"
            ).fetchall()
            self.assertEqual([(r["manager_agent_id"], r["department_id"]) for r in lines], [(1, 1), (1, 2)])
            audit = conn.execute("SELECT action,details FROM audit ORDER BY id DESC LIMIT 1").fetchone()
            self.assertEqual(audit["action"], "agent_hierarchy_updated")
            self.assertIn("agent=3", audit["details"])

    def test_agent_hierarchy_rejects_self_and_cycles(self):
        with self.assertRaisesRegex(ValueError, "agent_cannot_manage_itself"):
            office_api.update_profile({"operation": "agent_hierarchy", "id": 2, "manager_id": 2})
        with self.assertRaisesRegex(ValueError, "agent_reporting_cycle"):
            office_api.update_profile({"operation": "agent_hierarchy", "id": 1, "manager_id": 3})
        with office_api.connect_readonly() as conn:
            self.assertIsNone(conn.execute("SELECT manager_id FROM agents WHERE id=1").fetchone()["manager_id"])

    def test_agent_membership_rejects_removing_department_manager(self):
        with office_api.connect_writable() as conn:
            conn.execute("UPDATE departments SET manager_agent_id=2 WHERE id=1")
            conn.commit()
        with self.assertRaisesRegex(ValueError, "cannot_remove_department_manager"):
            office_api.update_profile({"operation": "agent_hierarchy", "id": 2, "department_ids": []})

    def test_agent_hierarchy_rejects_unknown_departments_and_unknown_fields(self):
        with self.assertRaisesRegex(ValueError, "department_not_found_or_inactive"):
            office_api.update_profile({"operation": "agent_hierarchy", "id": 3, "department_ids": [999]})
        with self.assertRaisesRegex(ValueError, "unsupported_fields"):
            office_api.update_profile({"operation": "agent_hierarchy", "id": 3, "role": "admin"})

    def test_department_parent_update_rejects_self_and_cycles_and_is_audited(self):
        result = office_api.update_profile({
            "operation": "department_hierarchy", "id": 2, "parent_department_id": 1,
        })
        self.assertEqual(result["operation"], "department_hierarchy")
        with office_api.connect_readonly() as conn:
            self.assertEqual(conn.execute(
                "SELECT parent_department_id FROM departments WHERE id=2"
            ).fetchone()["parent_department_id"], 1)
            audit = conn.execute("SELECT action FROM audit ORDER BY id DESC LIMIT 1").fetchone()
            self.assertEqual(audit["action"], "department_hierarchy_updated")
        with self.assertRaisesRegex(ValueError, "department_hierarchy_cycle"):
            office_api.update_profile({"operation": "department_hierarchy", "id": 1, "parent_department_id": 2})
        with self.assertRaisesRegex(ValueError, "department_cannot_parent_itself"):
            office_api.update_profile({"operation": "department_hierarchy", "id": 1, "parent_department_id": 1})


if __name__ == "__main__":
    unittest.main()
