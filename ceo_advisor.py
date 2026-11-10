#!/usr/bin/env python3
"""محادثة الرئيس التنفيذي، سجل الملاحظات، والتدقيق الاستشاري.
هذه طبقة ذاكرة/تغذية راجعة وليست خوارزمية تعلم معزز بحد ذاتها.
"""
import json
import orgx
import ceo_brain


def ensure(org):
    org.x("""CREATE TABLE IF NOT EXISTS ceo_chat (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
        role TEXT NOT NULL, content TEXT NOT NULL)""")
    org.x("""CREATE TABLE IF NOT EXISTS ceo_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
        category TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'normal',
        source TEXT NOT NULL DEFAULT 'owner', status TEXT NOT NULL DEFAULT 'open',
        title TEXT NOT NULL, details TEXT NOT NULL, recommendation TEXT DEFAULT '',
        related_department TEXT DEFAULT '', related_task_id INTEGER)""")
    org.x("""CREATE TABLE IF NOT EXISTS ceo_feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
        source TEXT NOT NULL, item TEXT NOT NULL, feedback TEXT NOT NULL,
        outcome TEXT DEFAULT '')""")


def _add_chat(org, role, content):
    org.x("INSERT INTO ceo_chat(ts,role,content) VALUES(?,?,?)", (orgx.now(), role, content[:6000]))


def _snapshot(org):
    deps = org.departments()
    dept_text = "\n".join("- %s: %s | المدير: %s" % (d[1], d[2], d[4] or "غير معيّن") for d in deps) or "لا توجد إدارات مسجلة"
    agents = org.q("SELECT id,name,role,specialty,status FROM agents ORDER BY id")
    agent_text = "\n".join("- #%s %s (%s) — %s — %s" % (a[0], a[1], a[2], a[3], a[4]) for a in agents[:35]) or "لا يوجد وكلاء"
    tasks = org.q("SELECT t.id,t.title,t.status,d.name,a.name,t.score FROM tasks t LEFT JOIN departments d ON d.id=t.department_id LEFT JOIN agents a ON a.id=t.assigned_to ORDER BY t.id DESC LIMIT 18")
    task_text = "\n".join("- #%s %s | %s | %s | المسؤول: %s | التقييم: %s" % (t[0], t[1], orgx.STATUS_AR.get(t[2], t[2]), t[3] or "بلا إدارة", t[4] or "غير معيّن", t[5]) for t in tasks) or "لا توجد مهام"
    reviews = org.q("SELECT task_id,reviewer,verdict,score,notes FROM reviews ORDER BY id DESC LIMIT 12")
    review_text = "\n".join("- المهمة #%s | %s | %s | %s | %s" % (r[0], r[1], r[2], r[3], r[4]) for r in reviews) or "لا توجد مراجعات"
    lessons = org.q("SELECT text FROM lessons ORDER BY id DESC LIMIT 10")
    lesson_text = "\n".join("- " + x[0] for x in lessons) or "لا توجد دروس مسجلة"
    notes = org.q("SELECT id,category,priority,status,title,details FROM ceo_notes ORDER BY id DESC LIMIT 12")
    note_text = "\n".join("- #%s [%s/%s/%s] %s: %s" % (n[0], n[1], n[2], n[3], n[4], n[5]) for n in notes) or "لا توجد ملاحظات مسجلة"
    feedback = org.q("SELECT source,item,feedback,outcome FROM ceo_feedback ORDER BY id DESC LIMIT 8")
    feedback_text = "\n".join("- %s | %s | %s | %s" % f for f in feedback) or "لا توجد تغذية راجعة مسجلة"
    return ("حالة المؤسسة الفعلية (قد تكون البيانات ناقصة):\nالإدارات:\n%s\nالوكلاء:\n%s\nالمهام الحديثة:\n%s\nالمراجعات:\n%s\nالدروس المستفادة:\n%s\nسجل الملاحظات:\n%s\nتغذية المالك الراجعة:\n%s\n\nتقرير مختصر:\n%s" % (dept_text, agent_text, task_text, review_text, lesson_text, note_text, feedback_text, org.report()))


CEO_SYSTEM = """أنت الرئيس التنفيذي لمؤسسة وكلاء ذكاء اصطناعي، وتتحدث مباشرة مع مالك المؤسسة.
أنت صاحب مسؤولية إدارية متكاملة: استشاري، مدقق، منسق، ومبادر إلى التحسين.
استخدم فقط البيانات والسياق المرفقين. لا تختلق أرقاماً أو إدارات أو إنجازات أو صلاحيات.
ميّز بوضوح بين: حقيقة موجودة في السجلات، استنتاج، ومقترح يحتاج تحققاً.
في الأسئلة الاستشارية أجب مباشرة وبوضوح، ولا تنشئ مهاماً ولا تدّع تنفيذ أي إجراء.
يمكنك اقتراح توزيع مهام أو تعديل إجراءات، لكن لا تنفذ أوامر خارج هذه المحادثة؛ تحويل الاقتراح إلى تنفيذ يتم بأمر صريح من المالك عبر نظام المهام.
لا تطلب موافقة على كل خطوة تشغيلية اعتيادية، لكن التغييرات الجوهرية والمالية والخارجية وحذف البيانات وتغيير الصلاحيات تحتاج موافقة المالك.
إذا كانت البيانات غير كافية فقل ذلك وحدد ما يلزم فحصه. لا تدّع أنك راقبت المؤسسة بين الرسائل أو عملت في الخلفية.
اكتب بالعربية الواضحة، وقدم توصيات عملية مرتبة حسب الأولوية."""


def chat(org, message):
    ensure(org)
    history = org.q("SELECT role,content FROM ceo_chat ORDER BY id DESC LIMIT 12")
    history = list(reversed(history))
    # مرر سجل الحوار السابق ضمن prompt؛ ask يدعم رسالة واحدة مع system.
    transcript = "\n".join(("المالك: " if r == "user" else "الرئيس التنفيذي: ") + c for r, c in history)
    prompt = _snapshot(org) + "\n\nسياق المحادثة السابقة:\n" + (transcript or "محادثة جديدة") + "\n\nرسالة المالك الحالية:\n" + message
    _add_chat(org, "user", message)
    answer = ceo_brain.ask(org, CEO_SYSTEM, prompt, temperature=0.35, max_tokens=1800, agent_id=org.ceo_id())
    answer = str(answer).strip() or "لم أتمكن من صياغة رد واضح. أعد السؤال من فضلك."
    _add_chat(org, "assistant", answer)
    org.log("owner", "ceo_chat", message[:180])
    return answer


def add_note(org, text, category="ملاحظة", priority="normal", source="owner", title=None, recommendation=""):
    ensure(org)
    text = (text or "").strip()
    if not text:
        raise orgx.OrgError("اكتب نص الملاحظة أولاً")
    title = (title or text.splitlines()[0])[:180]
    nid = org.x("INSERT INTO ceo_notes(ts,category,priority,source,title,details,recommendation) VALUES(?,?,?,?,?,?,?)",
                (orgx.now(), category[:40], priority if priority in ("low", "normal", "high", "critical") else "normal", source[:40], title, text[:3000], recommendation[:2000]))
    if source == "owner":  # تقارير الرئيس التلقائية لا تدخل الذاكرة المشتركة حتى لا تلوّث تخطيط الأهداف
        org.remember("ملاحظة المالك #%d: %s" % (nid, text[:500]), topic="ملاحظة تطوير", weight=2.5)
    org.x("INSERT INTO ceo_feedback(ts,source,item,feedback) VALUES(?,?,?,?)", (orgx.now(), "owner_note", str(nid), text[:2000]))
    org.log("owner", "ceo_note_added", "note=%d %s" % (nid, title[:100]))
    return nid


def list_notes(org, limit=12):
    ensure(org)
    rows = org.q("SELECT id,category,priority,status,title,details FROM ceo_notes ORDER BY id DESC LIMIT ?", (limit,))
    if not rows:
        return "لا توجد ملاحظات مسجلة. أضف ملاحظة باستخدام /note نص الملاحظة"
    return "🗒 سجل ملاحظات الرئيس التنفيذي\n" + "\n\n".join("#%d [%s | %s | %s] %s\n%s" % (r[0], r[1], r[2], r[3], r[4], r[5][:450]) for r in rows)


def review_org(org):
    ensure(org)
    prompt = _snapshot(org) + "\n\nأجرِ تدقيقاً إدارياً للمؤسسة. أخرج تقريراً منظماً يتضمن: (1) ملخص الحالة، (2) نقاط القوة المثبتة، (3) المشكلات المثبتة مع أدلتها، (4) مخاطر أو فجوات لا يمكن الجزم بها، (5) أهم خمس توصيات مرتبة بالأولوية، (6) ما يحتاج موافقة المالك. لا تنشئ مهاماً ولا تزعم تنفيذ إصلاحات."
    result = ceo_brain.ask(org, CEO_SYSTEM, prompt, temperature=0.2, max_tokens=2200, agent_id=org.ceo_id())
    _add_chat(org, "assistant", "[تدقيق المؤسسة]\n" + str(result))
    nid = add_note(org, str(result), category="تدقيق", priority="normal", source="ceo_audit", title="تقرير تدقيق المؤسسة")
    return result, nid


def improvement_plan(org):
    ensure(org)
    prompt = _snapshot(org) + "\n\nبصفتك الرئيس التنفيذي، اقترح خطة تطوير للمؤسسة بناءً على بياناتها الحالية. حدد من 3 إلى 5 فرص تحسين فقط، ولكل واحدة: المشكلة أو الفرصة، الدليل المتاح، الإجراء المقترح، الإدارة المعنية، أولوية التنفيذ، ومؤشر قياس النجاح. لا تنشئ مهاماً ولا تفترض موارد أو قدرات غير مسجلة. اختم بأول خطوة عملية تحتاج اعتماد المالك."
    result = ceo_brain.ask(org, CEO_SYSTEM, prompt, temperature=0.25, max_tokens=2000, agent_id=org.ceo_id())
    _add_chat(org, "assistant", "[مقترحات تطوير]\n" + str(result))
    nid = add_note(org, str(result), category="فرصة تطوير", priority="normal", source="ceo_improve", title="مقترحات تطوير المؤسسة")
    return result, nid


def record_feedback(org, item, feedback, outcome=""):
    ensure(org)
    org.x("INSERT INTO ceo_feedback(ts,source,item,feedback,outcome) VALUES(?,?,?,?,?)",
          (orgx.now(), "owner_feedback", str(item)[:180], str(feedback)[:2000], str(outcome)[:1000]))
    org.log("owner", "ceo_feedback", str(item)[:150])


def close_note(org, note_id, outcome="عولجت"):
    ensure(org)
    row = org.q("SELECT title FROM ceo_notes WHERE id=?", (int(note_id),))
    if not row:
        raise orgx.OrgError("الملاحظة #%s غير موجودة" % note_id)
    org.x("UPDATE ceo_notes SET status='resolved' WHERE id=?", (int(note_id),))
    org.x("INSERT INTO ceo_feedback(ts,source,item,feedback,outcome) VALUES(?,?,?,?,?)",
          (orgx.now(), "note_resolution", str(note_id), "تحديث حالة الملاحظة", str(outcome)[:1000]))
    org.log("owner", "ceo_note_resolved", "note=%s %s" % (note_id, row[0][0][:100]))
    return row[0][0]
