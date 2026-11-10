#!/usr/bin/env python3
"""orgx.py - نواة المؤسسة: تفويض، رسائل داخلية، ذاكرة، موافقات، تقارير.
بدون شبكة وبدون LLM. تعمل فوق organization.db الموجودة (تضيف ولا تحذف).
usage: python orgx.py setup | tree | report"""
import os, re, json, time, sqlite3
from contextlib import closing
from datetime import datetime, timezone

HOME = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("ORG_DB", os.path.join(HOME, "organization.db"))

BASE_DEPARTMENTS = [
    ("التخطيط والاستراتيجية", "تحديد الأهداف وترتيب الأولويات"),
    ("التقنية والأنظمة", "البرمجة والبنية التقنية"),
    ("البحث والتطوير", "البحث عن الحلول والأفكار الجديدة"),
    ("العمليات وإدارة المشاريع", "تنظيم التنفيذ ومتابعة المهام"),
    ("الجودة والتدقيق", "مراجعة النتائج واكتشاف الأخطاء"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, role TEXT NOT NULL,
  specialty TEXT NOT NULL, manager_id INTEGER, status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT DEFAULT '',
  assigned_to INTEGER, status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT NOT NULL, action TEXT NOT NULL,
  details TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS departments(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
  description TEXT DEFAULT '', parent_department_id INTEGER, manager_agent_id INTEGER, status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS agent_departments(id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id INTEGER NOT NULL,
  department_id INTEGER NOT NULL, role TEXT NOT NULL DEFAULT 'member', status TEXT NOT NULL DEFAULT 'active',
  assigned_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(agent_id, department_id));
CREATE TABLE IF NOT EXISTS reporting_lines(id INTEGER PRIMARY KEY AUTOINCREMENT, manager_agent_id INTEGER NOT NULL,
  subordinate_agent_id INTEGER NOT NULL, department_id INTEGER, relation TEXT DEFAULT 'reports_to',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(manager_agent_id, subordinate_agent_id));
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, sender INTEGER, recipient INTEGER,
  task_id INTEGER, kind TEXT DEFAULT 'msg', body TEXT, is_read INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS memories(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, scope TEXT, agent_id INTEGER,
  topic TEXT DEFAULT '', text TEXT, weight REAL DEFAULT 1);
CREATE TABLE IF NOT EXISTS lessons(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, agent_id INTEGER, task_id INTEGER, text TEXT);
CREATE TABLE IF NOT EXISTS reviews(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, task_id INTEGER, reviewer TEXT,
  verdict TEXT, score REAL, notes TEXT);
CREATE TABLE IF NOT EXISTS approvals(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, payload TEXT,
  status TEXT DEFAULT 'pending', decided_at TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS usage(day TEXT PRIMARY KEY, calls INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER, agent_id INTEGER, status TEXT DEFAULT 'running',
  history TEXT DEFAULT '[]', steps INTEGER DEFAULT 0, pending TEXT DEFAULT '', created TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS steps(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, task_id INTEGER, agent_id INTEGER, n INTEGER,
  thought TEXT, action TEXT, args TEXT, observation TEXT);
"""
TASK_COLS = {"department_id": "INTEGER", "parent_id": "INTEGER", "result": "TEXT", "score": "REAL",
             "priority": "TEXT DEFAULT 'normal'", "updated_at": "TEXT", "dept_hint": "TEXT"}
STATUS_AR = {"pending": "بانتظار مسؤول", "assigned": "مسندة", "submitted": "بانتظار المراجعة", "blocked": "متوقفة بانتظارك", "done": "منجزة", "rejected": "مرفوضة"}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def norm(s):
    s = re.sub(r"[\u064B-\u065F\u0640]", "", s or "")
    s = s.translate(str.maketrans("أإآىة", "ااايه")).lower()
    return s


def toks(s):
    out = []
    for t in re.findall(r"\w+", norm(s)):
        if t.startswith("ال") and len(t) > 4:
            t = t[2:]
        if len(t) >= 3:
            out.append(t)
    return out


class OrgError(ValueError):
    pass


class Org:
    def __init__(self, db=DB):
        self.db = str(db)
        with closing(self._c()) as c:
            c.executescript(SCHEMA)
            have = {r[1] for r in c.execute("PRAGMA table_info(tasks)")}
            for col, typ in TASK_COLS.items():
                if col not in have:
                    c.execute("ALTER TABLE tasks ADD COLUMN %s %s" % (col, typ))
            c.commit()

    def _c(self):
        return sqlite3.connect(self.db, timeout=30)

    def q(self, sql, a=()):
        with closing(self._c()) as c:
            return c.execute(sql, a).fetchall()

    def x(self, sql, a=()):
        with closing(self._c()) as c:
            cur = c.execute(sql, a)
            c.commit()
            return cur.lastrowid

    def log(self, actor, action, details):
        self.x("INSERT INTO audit(actor,action,details,created_at) VALUES(?,?,?,?)", (str(actor), action, str(details)[:500], now()))

    def kget(self, k, d=None):
        r = self.q("SELECT v FROM kv WHERE k=?", (k,))
        return r[0][0] if r else d

    def kset(self, k, v):
        self.x("INSERT OR REPLACE INTO kv VALUES(?,?)", (k, str(v)))

    # ---------- الأشخاص والأقسام ----------
    def ceo_id(self):
        r = self.q("SELECT id FROM agents WHERE role='CEO' ORDER BY id LIMIT 1")
        if r:
            return r[0][0]
        i = self.x("INSERT INTO agents(name,role,specialty,created_at) VALUES(?,?,?,?)",
                   ("الرئيس التنفيذي", "CEO", "إدارة المؤسسة والتخطيط والتفويض", now()))
        self.log("system", "ceo_created", i)
        return i

    def agent(self, aid):
        r = self.q("SELECT id,name,role,specialty,manager_id,status FROM agents WHERE id=?", (aid,))
        return r[0] if r else None

    def ensure_departments(self, items=BASE_DEPARTMENTS):
        for name, desc in items:
            if not self.q("SELECT 1 FROM departments WHERE name=?", (name,)):
                self.x("INSERT INTO departments(name,description) VALUES(?,?)", (name, desc))
                self.log("system", "department_created", name)

    def departments(self):
        return self.q("SELECT d.id,d.name,d.description,d.manager_agent_id,a.name FROM departments d "
                      "LEFT JOIN agents a ON a.id=d.manager_agent_id AND a.status='active' WHERE d.status='active' ORDER BY d.id")

    def find_dept(self, name):
        if not name:
            return None
        deps = self.departments()
        for d in deps:
            if norm(d[1]) == norm(name):
                return d[0]
        t = set(toks(name))
        best, bs = None, 0
        for d in deps:
            s = len(t & set(toks(d[1])))
            if s > bs:
                best, bs = d[0], s
        return best

    def dept_manager(self, did):
        r = self.q("SELECT a.id FROM departments d JOIN agents a ON a.id=d.manager_agent_id "
                   "WHERE d.id=? AND a.status='active'", (did,))
        return r[0][0] if r else None

    def link_existing_managers(self):
        """يربط المديرين الموجودين (مثل مدير العمليات) بأقسامهم حسب تشابه الأسماء"""
        done = []
        for did, dname, _, mgr, _ in self.departments():
            if mgr:
                continue
            for aid, aname, role, spec, _, st in self.q("SELECT id,name,role,specialty,manager_id,status FROM agents WHERE role!='CEO' AND status='active'"):
                if "مدير" in aname and len(set(toks(dname)) & set(toks(aname + " " + spec))) >= 1 and not self.q(
                        "SELECT 1 FROM departments WHERE manager_agent_id=?", (aid,)):
                    self._attach(aid, did, manager=True)
                    done.append((aname, dname))
                    break
        return done

    def _attach(self, aid, did, manager=False):
        self.x("INSERT OR IGNORE INTO agent_departments(agent_id,department_id,role) VALUES(?,?,?)", (aid, did, "manager" if manager else "member"))
        if manager:
            self.x("UPDATE departments SET manager_agent_id=? WHERE id=?", (aid, did))
        ag = self.agent(aid)
        if ag and ag[4]:
            self.x("INSERT OR IGNORE INTO reporting_lines(manager_agent_id,subordinate_agent_id,department_id) VALUES(?,?,?)", (ag[4], aid, did))

    def tree(self):
        L = ["🏢 المؤسسة", "👑 الرئيس التنفيذي (#%d)" % self.ceo_id()]
        for did, name, _, mid, mname in self.departments():
            L.append("├ 📁 %s — %s" % (name, ("مدير: %s (#%d)" % (mname, mid)) if mid else "بدون مدير بعد"))
            for aid, an, spec in self.q("SELECT a.id,a.name,a.specialty FROM agents a JOIN agent_departments ad ON ad.agent_id=a.id "
                                         "WHERE ad.department_id=? AND a.status='active' AND a.id!=COALESCE(?,0)", (did, mid)):
                L.append("│   └ 🤖 %s (#%d)" % (an, aid))
        n = self.q("SELECT count(*) FROM agents WHERE status='active' AND role!='CEO'")[0][0]
        L.append("إجمالي الوكلاء والمديرين: %d" % n)
        return "\n".join(L)

    # ---------- الرسائل الداخلية ----------
    def send(self, sender, recipient, body, task_id=None, kind="msg"):
        return self.x("INSERT INTO messages(ts,sender,recipient,task_id,kind,body) VALUES(?,?,?,?,?,?)",
                      (now(), sender, recipient, task_id, kind, body[:2000]))

    def inbox(self, aid, unread_only=True, mark=True, limit=20):
        w = " AND is_read=0" if unread_only else ""
        rows = self.q("SELECT id,ts,sender,task_id,kind,body FROM messages WHERE recipient=?%s ORDER BY id DESC LIMIT ?" % w, (aid, limit))
        if mark and rows:
            self.x("UPDATE messages SET is_read=1 WHERE recipient=? AND id<=?", (aid, max(r[0] for r in rows)))
        return rows

    # ---------- المهام ----------
    def create_task(self, title, description="", department_id=None, assigned_to=None, priority="normal", parent_id=None, by=None, dept_hint=""):
        st = "assigned" if assigned_to else "pending"
        tid = self.x("INSERT INTO tasks(title,description,assigned_to,status,created_at,department_id,parent_id,priority,updated_at,dept_hint) VALUES(?,?,?,?,?,?,?,?,?,?)",
                     (title[:200], description[:2000], assigned_to, st, now(), department_id, parent_id, priority, now(), dept_hint[:80]))
        self.log(by or "CEO", "task_created", "id=%d %s" % (tid, title[:80]))
        if assigned_to:
            self.send(by or self.ceo_id(), assigned_to, "مهمة جديدة #%d: %s\n%s" % (tid, title, description), tid, "task")
        return tid

    def assign(self, tid, aid, by=None):
        t = self.task(tid)
        a = self.agent(aid)
        if not t:
            raise OrgError("المهمة #%s غير موجودة" % tid)
        if not a or a[5] != "active":
            raise OrgError("الوكيل #%s غير موجود أو غير نشط" % aid)
        if t[3] in ("done", "rejected"):
            raise OrgError("المهمة #%d مقفلة (%s)" % (tid, STATUS_AR[t[3]]))
        self.x("UPDATE tasks SET assigned_to=?,status='assigned',updated_at=? WHERE id=?", (aid, now(), tid))
        self.send(by or self.ceo_id(), aid, "أُسندت إليك المهمة #%d: %s\n%s" % (tid, t[1], t[2]), tid, "task")
        self.log(by or "CEO", "task_assigned", "task=%d agent=%d" % (tid, aid))

    def task(self, tid):
        r = self.q("SELECT id,title,description,status,assigned_to,department_id,result,score,priority FROM tasks WHERE id=?", (tid,))
        return r[0] if r else None

    def submit(self, tid, aid, result):
        t = self.task(tid)
        if not t:
            raise OrgError("المهمة #%s غير موجودة" % tid)
        if t[4] != aid:
            raise OrgError("المهمة ليست مسندة للوكيل #%s" % aid)
        if t[3] not in ("assigned",):
            raise OrgError("حالة المهمة الحالية (%s) لا تسمح بالتسليم" % STATUS_AR.get(t[3], t[3]))
        self.x("UPDATE tasks SET status='submitted',result=?,updated_at=? WHERE id=?", (result[:6000], now(), tid))
        ag = self.agent(aid)
        to = (ag[4] if ag and ag[4] else self.ceo_id())
        self.send(aid, to, "سلّمت المهمة #%d للمراجعة" % tid, tid, "report")
        self.log("agent%d" % aid, "task_submitted", tid)

    def review(self, tid, reviewer, verdict, score=None, notes=""):
        t = self.task(tid)
        if not t:
            raise OrgError("المهمة #%s غير موجودة" % tid)
        if t[3] != "submitted":
            raise OrgError("المهمة #%d ليست بانتظار المراجعة (حالتها: %s)" % (tid, STATUS_AR.get(t[3], t[3])))
        if verdict not in ("ok", "revise", "reject"):
            raise OrgError("القرار لازم يكون ok أو revise أو reject")
        self.x("INSERT INTO reviews(ts,task_id,reviewer,verdict,score,notes) VALUES(?,?,?,?,?,?)", (now(), tid, str(reviewer), verdict, score, notes[:1000]))
        new = {"ok": "done", "revise": "assigned", "reject": "rejected"}[verdict]
        self.x("UPDATE tasks SET status=?,score=COALESCE(?,score),updated_at=? WHERE id=?", (new, score, now(), tid))
        aid = t[4]
        if aid and verdict != "ok" and notes:
            self.x("INSERT INTO lessons(ts,agent_id,task_id,text) VALUES(?,?,?,?)", (now(), aid, tid, notes[:500]))
        if aid and verdict == "ok" and score is not None and score <= 2 and notes:
            self.x("INSERT INTO lessons(ts,agent_id,task_id,text) VALUES(?,?,?,?)", (now(), aid, tid, notes[:500]))
        if aid:
            msg = {"ok": "قُبلت مهمتك #%d" % tid, "revise": "مطلوب تعديل على المهمة #%d: %s" % (tid, notes), "reject": "رُفضت المهمة #%d: %s" % (tid, notes)}[verdict]
            self.send(None, aid, msg, tid, "review")
        try:
            import exper
            exper.record(self, tid, verdict, score, notes)
        except Exception:
            pass
        self.log(reviewer, "task_reviewed", "task=%d %s score=%s" % (tid, verdict, score))

    def open_tasks(self, limit=30):
        return self.q("SELECT t.id,t.title,t.status,d.name,a.name FROM tasks t LEFT JOIN departments d ON d.id=t.department_id "
                      "LEFT JOIN agents a ON a.id=t.assigned_to WHERE t.status NOT IN ('done','rejected') ORDER BY t.id DESC LIMIT ?", (limit,))

    # ---------- الذاكرة والدروس ----------
    def remember(self, text, topic="", agent_id=None, weight=1.0):
        return self.x("INSERT INTO memories(ts,scope,agent_id,topic,text,weight) VALUES(?,?,?,?,?,?)",
                      (now(), "agent" if agent_id else "shared", agent_id, topic, text[:1500], weight))

    def recall(self, query, agent_id=None, k=5):
        qt = set(toks(query))
        rows = self.q("SELECT id,scope,agent_id,topic,text,weight,ts FROM memories WHERE scope='shared' OR agent_id=? ORDER BY id DESC LIMIT 400", (agent_id,))
        sc = []
        for i, (mid, scope, aid, topic, text, w, ts) in enumerate(rows):
            ov = len(qt & set(toks(topic + " " + text)))
            if ov:
                sc.append((ov * 2 + w - i * 0.005, scope, text))
        sc.sort(reverse=True)
        return [(s, t) for _, s, t in sc[:k]]

    def lessons_for(self, aid, k=5):
        return [r[0] for r in self.q("SELECT text FROM lessons WHERE agent_id=? ORDER BY id DESC LIMIT ?", (aid, k))]

    # ---------- الموافقات (كل إنشاء وكيل/قسم يمر عليك) ----------
    def propose(self, kind, payload, by="CEO"):
        pj = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        r = self.q("SELECT id FROM approvals WHERE kind=? AND payload=? AND status='pending'", (kind, pj))
        if r:
            return r[0][0]
        i = self.x("INSERT INTO approvals(ts,kind,payload) VALUES(?,?,?)", (now(), kind, pj))
        self.log(by, "approval_requested", "id=%d %s" % (i, kind))
        return i

    def approval(self, aid):
        r = self.q("SELECT id,kind,payload,status FROM approvals WHERE id=?", (aid,))
        if not r:
            return None
        return r[0][0], r[0][1], json.loads(r[0][2]), r[0][3]

    def pending_approvals(self):
        return [(i, k, json.loads(p)) for i, k, p in self.q("SELECT id,kind,payload FROM approvals WHERE status='pending' ORDER BY id")]

    @staticmethod
    def describe(kind, p):
        if kind == "create_department":
            return "إنشاء إدارة جديدة: %s\n%s" % (p.get("name"), p.get("description", ""))
        if kind == "create_manager":
            return "تعيين مدير جديد لإدارة «%s»:\n%s — %s" % (p.get("department"), p.get("name"), p.get("specialty", ""))
        if kind == "create_agent":
            return "إنشاء وكيل تنفيذي تحت المدير #%s:\n%s — %s" % (p.get("manager_id"), p.get("name"), p.get("specialty", ""))
        if kind == "tool_call":
            args = p.get("args", {}) or {}
            if p.get("tool") == "post_bluesky":
                a = "📣 نشر على Bluesky الآن:\n«%s»\n\n(هذا ينشر علناً على حسابك. اقرأه قبل ما توافق.)" % str(args.get("text", ""))[:300]
            elif p.get("tool") == "run_shell":
                a = "💻 أمر شل على السحابة:\n" + str(args.get("command", ""))[:1500] + "\n\n(اقرأ الأمر. إذا ما فهمته أو بدا غريباً ارفض.)"
            elif p.get("tool") == "send_email":
                a = "✉️ إيميل من حسابك إلى: %s\nالعنوان: %s\n\n%s\n\n(يُرسل فعلاً باسمك.)" % (args.get("to"), args.get("subject"), str(args.get("body", ""))[:1000])
            elif p.get("tool") == "telegram_channel":
                a = "📢 نشر في قناتك:\n«%s»\n\n(ينشر علناً.)" % str(args.get("text", ""))[:1000]
            elif p.get("tool") == "http_request":
                a = "🌐 %s %s\nالرؤوس: %s\nالمحتوى: %s" % (args.get("method", "GET"), args.get("url"), json.dumps(args.get("headers") or {}, ensure_ascii=False)[:300], json.dumps(args.get("json", args.get("body")), ensure_ascii=False)[:800])
            elif p.get("tool") == "github":
                a = "🐙 GitHub: %s\n%s\n\n(يغيّر في حسابك.)" % (args.get("action"), json.dumps({k: v for k, v in args.items() if k != "action"}, ensure_ascii=False)[:900])
            elif p.get("tool") == "run_python":
                a = "الكود:\n" + str(args.get("code", ""))[:1500] + "\n\n(اقرأ الكود. إذا ما فهمته أو بدا غريباً ارفض.)"
            else:
                a = json.dumps(args, ensure_ascii=False)[:1200]
            return "⚠️ وكيل #%s (تشغيل #%s) يطلب تنفيذ أداة: %s\n%s" % (p.get("agent_id"), p.get("run_id"), p.get("tool"), a)
        if kind == "tool":
            a = json.dumps(p.get("args"), ensure_ascii=False)
            return "⚙️ الوكيل #%s يطلب تشغيل أداة «%s» للمهمة #%s:\n%s" % (p.get("agent_id"), p.get("tool"), p.get("task_id"), a[:1500])
        return "%s %s" % (kind, p)

    def decide(self, aid, yes, note=""):
        a = self.approval(aid)
        if not a:
            raise OrgError("الطلب #%s غير موجود" % aid)
        _, kind, p, st = a
        if st != "pending":
            raise OrgError("الطلب #%d سبق البت فيه (%s)" % (aid, st))
        if not yes:
            self.x("UPDATE approvals SET status='rejected',decided_at=?,note=? WHERE id=?", (now(), note, aid))
            self.log("owner", "approval_rejected", aid)
            return "❌ رُفض الطلب #%d" % aid
        out = self._execute(kind, p)
        self.x("UPDATE approvals SET status='approved',decided_at=?,note=? WHERE id=?", (now(), note, aid))
        self.log("owner", "approval_approved", "%d %s" % (aid, kind))
        return "✅ تمت الموافقة على #%d\n%s" % (aid, out)

    def _execute(self, kind, p):
        ceo = self.ceo_id()
        if kind == "create_department":
            self.ensure_departments([(p["name"], p.get("description", ""))])
            did = self.find_dept(p["name"])
            extra = ""
            if did:
                n = 0
                for tid, hint in self.q("SELECT id,dept_hint FROM tasks WHERE department_id IS NULL AND status='pending' AND dept_hint!=''"):
                    if self.find_dept(hint) == did:
                        self.x("UPDATE tasks SET department_id=? WHERE id=?", (did, tid))
                        n += 1
                if n and not self.dept_manager(did):
                    pid = self.propose("create_manager", {"department": p["name"], "name": "مدير " + p["name"], "specialty": p.get("description", "")})
                    extra = "\nوصلت إليها %d مهمة معلّقة. جهّزت طلب تعيين مدير #%d" % (n, pid)
            return "أُنشئت الإدارة «%s»%s" % (p["name"], extra)
        if kind == "create_manager":
            did = self.find_dept(p["department"])
            if not did:
                raise OrgError("الإدارة «%s» غير موجودة، أنشئها أول" % p["department"])
            if self.dept_manager(did):
                raise OrgError("الإدارة لها مدير فعلاً")
            aid = self.x("INSERT INTO agents(name,role,specialty,manager_id,created_at) VALUES(?,?,?,?,?)",
                         (p["name"], "مدير إدارة", p.get("specialty", ""), ceo, now()))
            self._attach(aid, did, manager=True)
            moved = 0
            for (tid,) in self.q("SELECT id FROM tasks WHERE department_id=? AND status='pending' AND assigned_to IS NULL", (did,)):
                self.assign(tid, aid, by=ceo)
                moved += 1
            self.log("system", "agent_created", "id=%d %s" % (aid, p["name"]))
            return "عُيّن %s (#%d)، وأُسندت إليه %d مهمة معلّقة" % (p["name"], aid, moved)
        if kind == "create_agent":
            mgr = self.agent(int(p["manager_id"]))
            if not mgr or mgr[5] != "active":
                raise OrgError("المدير غير موجود أو غير نشط")
            aid = self.x("INSERT INTO agents(name,role,specialty,manager_id,created_at) VALUES(?,?,?,?,?)",
                         (p["name"], "وكيل تنفيذي", p.get("specialty", ""), mgr[0], now()))
            r = self.q("SELECT department_id FROM agent_departments WHERE agent_id=? LIMIT 1", (mgr[0],))
            if r:
                self._attach(aid, r[0][0])
            self.log("system", "agent_created", "id=%d %s" % (aid, p["name"]))
            return "أُنشئ الوكيل %s (#%d)" % (p["name"], aid)
        if kind == "tool":
            return "سُمح بتنفيذ الأداة"
        if kind == "tool_call":
            return "سأكمل التنفيذ"
        raise OrgError("نوع طلب غير معروف: " + kind)

    # ---------- خطوات التنفيذ ----------
    def add_step(self, task_id, agent_id, n, thought, action, args, observation):
        return self.x("INSERT INTO steps(ts,task_id,agent_id,n,thought,action,args,observation) VALUES(?,?,?,?,?,?,?,?)",
                      (now(), task_id, agent_id, n, str(thought)[:500], str(action)[:60],
                       json.dumps(args, ensure_ascii=False)[:2000], str(observation)[:4000]))

    def steps(self, task_id, last=None):
        rows = self.q("SELECT n,thought,action,args,observation FROM steps WHERE task_id=? ORDER BY id", (task_id,))
        return rows[-last:] if last else rows

    def set_status(self, tid, st):
        self.x("UPDATE tasks SET status=?,updated_at=? WHERE id=?", (st, now(), tid))

    def approval_status(self, aid):
        r = self.q("SELECT status FROM approvals WHERE id=?", (aid,))
        return r[0][0] if r else None

    # ---------- حدّ الاستخدام وتقرير ----------
    def llm_calls_today(self):
        r = self.q("SELECT calls FROM usage WHERE day=?", (time.strftime("%Y-%m-%d"),))
        return r[0][0] if r else 0

    def bump_llm(self):
        d = time.strftime("%Y-%m-%d")
        self.x("INSERT OR IGNORE INTO usage(day,calls) VALUES(?,0)", (d,))
        self.x("UPDATE usage SET calls=calls+1 WHERE day=?", (d,))

    def report(self):
        L = ["📋 تقرير المؤسسة"]
        st = dict(self.q("SELECT status,count(*) FROM tasks GROUP BY status"))
        L.append("المهام: " + (" | ".join("%s %d" % (STATUS_AR.get(k, k), v) for k, v in st.items()) or "لا يوجد"))
        pa = len(self.pending_approvals())
        L.append("طلبات بانتظار موافقتك: %d" % pa)
        rows = self.q("SELECT a.id,a.name,count(t.id),avg(t.score) FROM tasks t JOIN agents a ON a.id=t.assigned_to WHERE t.status='done' GROUP BY a.id ORDER BY 3 DESC LIMIT 8")
        if rows:
            L.append("المنجِزون:")
            for i, n, c, s in rows:
                L.append("  #%d %s: %d مهمة%s" % (i, n, c, (" | متوسط التقييم %.1f" % s) if s else ""))
        ln = self.q("SELECT count(*) FROM lessons")[0][0]
        mm = self.q("SELECT count(*) FROM memories")[0][0]
        L.append("الذاكرة: %d معلومة | الدروس المستفادة: %d" % (mm, ln))
        L.append("استدعاءات النموذج اليوم: %d" % self.llm_calls_today())
        return "\n".join(L)


if __name__ == "__main__":
    import sys
    o = Org()
    a = sys.argv[1] if len(sys.argv) > 1 else ""
    if a == "setup":
        o.ceo_id()
        o.ensure_departments()
        for n, d in o.link_existing_managers():
            print("ربطت المدير الموجود «%s» بإدارة «%s»" % (n, d))
        print(o.tree())
    elif a == "tree":
        print(o.tree())
    elif a == "report":
        print(o.report())
    else:
        print(__doc__)
