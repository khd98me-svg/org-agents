#!/usr/bin/env python3
"""ext.py - أدوات العالم الخارجي: جدولة أهداف متكررة، مراقبة/فحص صفحات، ونشر على Bluesky (بموافقتك).
تعمل مع أي مشغّل (تريموكس أو GitHub Actions): كل شي محفوظ في قاعدة البيانات ويُفحص عند كل tick."""
import os, re, json, time, hashlib, difflib, urllib.request
import orgx, tools

SCHEMA = """
CREATE TABLE IF NOT EXISTS schedules(id INTEGER PRIMARY KEY AUTOINCREMENT, goal TEXT, every_s INTEGER, last_run REAL DEFAULT 0,
  active INTEGER DEFAULT 1, created TEXT);
CREATE TABLE IF NOT EXISTS watches(id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT, mode TEXT, keyword TEXT DEFAULT '',
  every_s INTEGER, last_check REAL DEFAULT 0, last_hash TEXT DEFAULT '', last_state TEXT DEFAULT '', last_text TEXT DEFAULT '',
  active INTEGER DEFAULT 1, created TEXT);
"""
MIN_SCHEDULE_S = 3600
MIN_WATCH_S = 300
MAX_SCHEDULES = 5
MAX_WATCHES = 12


def ensure(org):
    from contextlib import closing
    with closing(org._c()) as c:
        c.executescript(SCHEMA)
        c.commit()


def parse_interval(s):
    m = re.fullmatch(r"(\d+)\s*(m|h|d|د|س|ي)", str(s).strip().lower())
    if not m:
        return None
    n, u = int(m.group(1)), m.group(2)
    return n * {"m": 60, "د": 60, "h": 3600, "س": 3600, "d": 86400, "ي": 86400}[u]


def fmt_interval(sec):
    return "%dd" % (sec // 86400) if sec % 86400 == 0 else ("%dh" % (sec // 3600) if sec % 3600 == 0 else "%dm" % (sec // 60))


# ---------- الجدولة ----------
def add_schedule(org, every, goal):
    ensure(org)
    sec = parse_interval(every)
    if not sec or sec < MIN_SCHEDULE_S:
        raise orgx.OrgError("المدة لازم تكون ساعة أو أكثر، مثال: 6h أو 1d (حماية لحدّك اليومي من النموذج)")
    if not goal.strip():
        raise orgx.OrgError("اكتب الهدف بعد المدة")
    if org.q("SELECT COUNT(*) FROM schedules WHERE active=1")[0][0] >= MAX_SCHEDULES:
        raise orgx.OrgError("الحد الأقصى %d جداول نشطة. احذف واحداً بـ /unschedule" % MAX_SCHEDULES)
    return org.x("INSERT INTO schedules(goal,every_s,last_run,created) VALUES(?,?,?,?)", (goal.strip()[:500], sec, time.time(), orgx.now()))


def list_schedules(org):
    ensure(org)
    rows = org.q("SELECT id,goal,every_s,last_run FROM schedules WHERE active=1 ORDER BY id")
    return "\n".join("#%d كل %s: %s (آخر تشغيل: %s)" % (i, fmt_interval(e), g[:60], time.strftime("%m-%d %H:%M", time.localtime(l)) if l else "—") for i, g, e, l in rows) or "ما فيه جداول."


def remove_schedule(org, sid):
    ensure(org)
    if not org.q("SELECT 1 FROM schedules WHERE id=? AND active=1", (sid,)):
        raise orgx.OrgError("الجدول #%d غير موجود" % sid)
    org.x("UPDATE schedules SET active=0 WHERE id=?", (sid,))


def tick_schedules(org, io):
    import ceo_brain, agent_run
    ensure(org)
    now = time.time()
    for sid, goal, every, last in org.q("SELECT id,goal,every_s,last_run FROM schedules WHERE active=1"):
        if now - last < every:
            continue
        if agent_run.active_root_run(org) or json.loads(org.kget("queue", "[]")):
            continue  # مشغول: نأجّل للدورة الجاية
        org.x("UPDATE schedules SET last_run=? WHERE id=?", (now, sid))
        try:
            r = ceo_brain.plan_goal(org, goal)
        except ceo_brain.BudgetExceeded as e:
            io.send("⛔ جدول #%d تأجّل: %s" % (sid, e))
            continue
        except Exception as e:
            io.send("⚠️ جدول #%d فشل تحليل الهدف: %s" % (sid, str(e)[:150]))
            continue
        io.send("⏰ تشغيل مجدول #%d: %s\n%s\nبدأ التنفيذ تلقائياً." % (sid, goal[:80], r["summary"][:200]))
        io.approvals()
        try:
            agent_run.go(org, io)
        except orgx.OrgError as e:
            io.send("⚠️ " + str(e))


# ---------- المراقبة والفحص ----------
def add_watch(org, url, mode, every):
    ensure(org)
    sec = parse_interval(every or "30m")
    if not sec or sec < MIN_WATCH_S:
        raise orgx.OrgError("المدة لازم تكون 5 دقائق أو أكثر، مثال: 30m أو 2h")
    mode = mode.strip()
    kw = ""
    if mode.lower().startswith("word:") or mode.startswith("كلمة:"):
        kw = mode.split(":", 1)[1].strip()
        mode = "keyword"
        if not kw:
            raise orgx.OrgError("اكتب الكلمة بعد word:")
    elif mode not in ("change", "up"):
        raise orgx.OrgError("النمط: change (تغيّر الصفحة) أو up (هل الموقع شغال) أو word:كلمة")
    tools._check_url(url)
    if org.q("SELECT COUNT(*) FROM watches WHERE active=1")[0][0] >= MAX_WATCHES:
        raise orgx.OrgError("الحد الأقصى %d مراقبات" % MAX_WATCHES)
    return org.x("INSERT INTO watches(url,mode,keyword,every_s,created) VALUES(?,?,?,?,?)", (url, mode, kw, sec, orgx.now()))


def list_watches(org):
    ensure(org)
    rows = org.q("SELECT id,url,mode,keyword,every_s,last_state FROM watches WHERE active=1 ORDER BY id")
    return "\n".join("#%d %s [%s%s] كل %s — %s" % (i, u[:50], m, (":" + k) if k else "", fmt_interval(e), s or "لم تُفحص بعد") for i, u, m, k, e, s in rows) or "ما فيه مراقبات."


def remove_watch(org, wid):
    ensure(org)
    if not org.q("SELECT 1 FROM watches WHERE id=? AND active=1", (wid,)):
        raise orgx.OrgError("المراقبة #%d غير موجودة" % wid)
    org.x("UPDATE watches SET active=0 WHERE id=?", (wid,))


def _fetch(url):
    t0 = time.time()
    body, ct = tools._http(url, timeout=25)
    return (tools.html_to_text(body) if "html" in ct else body), time.time() - t0


def check_watch(org, w):
    """يرجع رسالة تنبيه أو None، ويحدّث الحالة."""
    wid, url, mode, kw, every, last_hash, last_state, last_text = w
    try:
        text, dt = _fetch(url)
        ok = True
    except Exception as e:
        text, dt, ok = "", 0, False
        err = str(e)[:120]
    msg = None
    if mode == "up":
        st = "up" if ok else "down"
        if last_state and st != last_state:
            msg = ("🟢 رجع الموقع يشتغل: %s (%.1f ثانية)" % (url, dt)) if ok else ("🔴 الموقع توقف: %s\n%s" % (url, err))
        org.x("UPDATE watches SET last_check=?,last_state=? WHERE id=?", (time.time(), st, wid))
    elif not ok:
        org.x("UPDATE watches SET last_check=? WHERE id=?", (time.time(), wid))
        if last_state != "error":
            msg = "⚠️ تعذّر فحص %s: %s" % (url, err)
            org.x("UPDATE watches SET last_state='error' WHERE id=?", (wid,))
    elif mode == "keyword":
        st = "present" if kw.lower() in text.lower() else "absent"
        if last_state in ("present", "absent") and st != last_state:
            msg = ("🔔 ظهرت الكلمة «%s» في %s" if st == "present" else "🔔 اختفت الكلمة «%s» من %s") % (kw, url)
        org.x("UPDATE watches SET last_check=?,last_state=? WHERE id=?", (time.time(), st, wid))
    else:  # change
        norm = re.sub(r"\s+", " ", text).strip()
        h = hashlib.sha1(norm.encode()).hexdigest()
        if last_hash and h != last_hash:
            old = [l.strip() for l in last_text.split("\n") if l.strip()]
            new = [l.strip() for l in text.split("\n") if l.strip()]
            d = [l for l in difflib.unified_diff(old, new, lineterm="", n=0) if l[:1] in "+-" and l[:3] not in ("+++", "---")]
            msg = "🔔 تغيّرت الصفحة: %s\n%s" % (url, "\n".join(x[:160] for x in d[:8]) or "(تغيير بسيط)")
        org.x("UPDATE watches SET last_check=?,last_hash=?,last_state='ok',last_text=? WHERE id=?", (time.time(), h, text[:20000], wid))
    return msg


def tick_watches(org, io):
    ensure(org)
    now = time.time()
    for w in org.q("SELECT id,url,mode,keyword,every_s,last_hash,last_state,last_text,last_check FROM watches WHERE active=1"):
        if now - w[8] < w[4]:
            continue
        try:
            m = check_watch(org, w[:8])
        except Exception as e:
            org.log("system", "watch_error", "%s %s" % (w[0], str(e)[:100]))
            continue
        if m:
            io.send(m)


def tick(org, io):
    tick_watches(org, io)
    tick_schedules(org, io)


# ---------- النشر على Bluesky (تُستخدم كأداة بموافقتك) ----------
def _secret(name):
    if os.environ.get(name):
        return os.environ[name].strip()
    for f in (os.path.expanduser("~/rl-agent/.env.models"), os.path.expanduser("~/rl-agent/.env.tg")):
        try:
            for l in open(f):
                if l.startswith(name + "="):
                    return l.split("=", 1)[1].strip().strip('"')
        except OSError:
            pass
    return None


def _post_json(url, payload, token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, json.dumps(payload).encode(), h)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def t_post_bluesky(ctx, a):
    text = str(a.get("text", "")).strip()
    if not text:
        raise tools.ToolError("text فاضي")
    if len(text) > 300:
        raise tools.ToolError("منشور Bluesky حدّه 300 حرف (طوله %d)" % len(text))
    handle, pw = _secret("BSKY_HANDLE"), _secret("BSKY_APP_PASSWORD")
    if not handle or not pw:
        raise tools.ToolError("بيانات Bluesky غير مضبوطة (BSKY_HANDLE و BSKY_APP_PASSWORD)")
    pds = os.environ.get("BSKY_PDS", "https://bsky.social")
    try:
        s = _post_json(pds + "/xrpc/com.atproto.server.createSession", {"identifier": handle, "password": pw})
        r = _post_json(pds + "/xrpc/com.atproto.repo.createRecord", {
            "repo": s["did"], "collection": "app.bsky.feed.post",
            "record": {"$type": "app.bsky.feed.post", "text": text, "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())}}, s["accessJwt"])
    except Exception as e:
        raise tools.ToolError("فشل النشر: %s" % str(e)[:150])
    return "نُشر على Bluesky: " + str(r.get("uri", ""))
