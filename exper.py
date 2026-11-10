# سجل التجارب: كل محاولة (نجحت/تعديل/رُفضت/فشلت) مع الأدوات والأخطاء، ويُعرض للوكلاء في المهام المشابهة.
# هذا تعلّم من التجربة عبر الذاكرة والتعليمات، وليس تدريب نموذج (لا يغيّر أوزان Gemini).
import json, collections
import orgx

OUT_AR = {"ok": "نجحت", "revise": "طُلب تعديل", "reject": "رُفضت", "failed": "فشلت/انقطعت"}


def ensure(org):
    org.x("""CREATE TABLE IF NOT EXISTS experience(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, task_id INTEGER, agent_id INTEGER, specialty TEXT,
        title TEXT, outcome TEXT, score REAL, steps INTEGER, tools TEXT, errors TEXT, note TEXT)""")


def record(org, task_id, outcome, score=None, note=""):
    try:
        ensure(org)
        t = org.task(task_id)
        if not t:
            return
        ag = org.agent(t[4]) if t[4] else None
        st = org.steps(task_id)
        tools = collections.Counter(a for _, _, a, _, _ in st if a and a not in ("finish", "ask_owner"))
        errs = [str(o)[:120] for _, _, a, _, o in st if str(o).startswith("خطأ")][:3]
        org.x("INSERT INTO experience(ts,task_id,agent_id,specialty,title,outcome,score,steps,tools,errors,note) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
              (orgx.now(), task_id, t[4], (ag[3] if ag else "")[:120], t[1][:160], outcome, score, len(st),
               ",".join("%s×%d" % kv for kv in tools.most_common(6)), " | ".join(errs), str(note)[:400]))
    except Exception:
        pass  # التسجيل لا يجوز أن يكسر العمل


def relevant(org, text, agent_id=None, k=3):
    try:
        ensure(org)
        qt = set(orgx.toks(text))
        rows = org.q("SELECT title,specialty,outcome,score,steps,tools,errors,note,agent_id FROM experience ORDER BY id DESC LIMIT 300")
    except Exception:
        return ""
    sc = []
    for i, (title, spec, out, score, steps, tools, errs, note, aid) in enumerate(rows):
        ov = len(qt & set(orgx.toks(title + " " + (spec or ""))))
        if ov < 2:
            continue
        s = ov * 2 + (1.5 if aid == agent_id else 0) + (1.0 if out != "ok" else 0) - i * 0.01
        sc.append((s, title, out, score, steps, tools, errs, note))
    sc.sort(reverse=True)
    lines = []
    for _, title, out, score, steps, tools, errs, note in sc[:k]:
        l = "- «%s» → %s%s" % (title, OUT_AR.get(out, out), (" (%s/5)" % score) if score else "")
        if note:
            l += " | ملاحظة: " + note[:160]
        if errs:
            l += " | أخطاء حدثت: " + errs[:160]
        if tools:
            l += " | أدوات: " + tools
        lines.append(l)
    return "\n".join(lines)


def summary(org, n=8):
    ensure(org)
    c = dict(org.q("SELECT outcome,COUNT(*) FROM experience GROUP BY outcome"))
    total = sum(c.values())
    head = "🧪 سجل التجارب: %d محاولة مسجلة" % total
    if total:
        head += " — " + "، ".join("%s %d" % (OUT_AR.get(k, k), v) for k, v in c.items())
    rows = org.q("SELECT task_id,agent_id,title,outcome,score,note FROM experience ORDER BY id DESC LIMIT ?", (n,))
    body = "\n".join("#%s (وكيل %s) «%s» → %s%s%s" % (t, a, ti[:50], OUT_AR.get(o, o), (" %s/5" % s) if s else "", (" | " + nt[:80]) if nt else "") for t, a, ti, o, s, nt in rows)
    les = org.q("SELECT agent_id,task_id,text FROM lessons ORDER BY id DESC LIMIT 6")
    lt = "\n".join("وكيل %s (مهمة %s): %s" % (a, t, x[:120]) for a, t, x in les)
    return head + ("\n\nآخر المحاولات:\n" + body if body else "") + ("\n\n📚 دروس محفوظة (تُعرض للوكيل في مهامه):\n" + lt if lt else "\n\n📚 لا دروس محفوظة بعد.") + \
        "\n\nملاحظة: هذا تعلّم عبر الذاكرة (يُعرض للوكيل في المهام المشابهة)، وليس تدريب النموذج."
