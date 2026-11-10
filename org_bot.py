#!/usr/bin/env python3
"""org_bot.py - واجهة تلقرام للمؤسسة (أنت <-> الرئيس التنفيذي).
usage: python org_bot.py run     (يعمل باستمرار)
       python org_bot.py once    (يعالج الرسائل المعلقة ويطلع - مناسب للسحابة لاحقاً)
       python org_bot.py pair    (أول مرة فقط إذا ما فيه owner.json)
يستخدم نفس البوت المربوط عندك (.env.tg + owner.json). لا تشغّل tg_bot.py معه."""
import os, re, sys, json, time, random, socket, shutil, tempfile, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import orgx, ceo_brain, agent_run, tools, ext, ceo_advisor

# الجوال أحياناً ما يحلّ api.telegram.org: نسأل DoH ثم عنوان ثابت
_orig_gai = socket.getaddrinfo
_cache = {}


def _doh(host):
    for url in ("https://1.1.1.1/dns-query?name=%s&type=A", "https://8.8.8.8/resolve?name=%s&type=A"):
        try:
            req = urllib.request.Request(url % host, headers={"accept": "application/dns-json"})
            with urllib.request.urlopen(req, timeout=8) as r:
                ips = [a["data"] for a in json.loads(r.read().decode()).get("Answer", []) if a.get("type") == 1]
            if ips:
                return ips
        except Exception:
            pass
    return []


def _gai(host, *a, **k):
    try:
        return _orig_gai(host, *a, **k)
    except socket.gaierror:
        if host != "api.telegram.org":
            raise
        ips = _cache.get(host) or _doh(host) or ["149.154.167.220"]
        _cache[host] = ips
        return _orig_gai(ips[0], *a, **k)


socket.getaddrinfo = _gai

API = os.environ.get("TG_API_BASE", "https://api.telegram.org")
HOME = os.path.expanduser("~/rl-agent")
OWNER_F = os.environ.get("OWNER_FILE", os.path.join(HOME, "owner.json"))


def load_token():
    t = os.environ.get("TG_TOKEN")
    if t:
        return t.strip()
    for d in (HOME, HERE):
        try:
            for l in open(os.path.join(d, ".env.tg")):
                if l.startswith("TG_TOKEN="):
                    return l.split("=", 1)[1].strip()
        except OSError:
            pass
    sys.exit("ما لقيت التوكن (.env.tg)")


TOKEN = load_token()


def log(*a):
    print(time.strftime("%H:%M:%S"), " ".join(str(x) for x in a).replace(TOKEN, "***"), flush=True)


def tg(method, _wait=0, **p):
    if _wait:
        p["timeout"] = _wait
    req = urllib.request.Request("%s/bot%s/%s" % (API, TOKEN, method), json.dumps(p).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=_wait + 20) as r:
            return json.loads(r.read().decode())
    except Exception:
        _cache.clear()
        raise


_FILEWORD = re.compile(r"(\w)\.(md|py|sh|pl|rs|zip|mov)\b", re.I)


def defang(text):
    """تلغرام يحوّل report.md لرابط موقع، فنكتبها report (md) حتى ما تتحول."""
    return _FILEWORD.sub(r"\1 (\2)", text)


def send(chat, text, buttons=None):
    text = defang(text)
    chunks = [text[i:i + 3800] for i in range(0, len(text), 3800)] or ["(فاضي)"]
    r = None
    for i, c in enumerate(chunks):
        p = {"chat_id": chat, "text": c}
        if buttons and i == len(chunks) - 1:
            p["reply_markup"] = {"inline_keyboard": buttons}
        try:
            r = tg("sendMessage", **p)
        except Exception as e:
            log("send failed:", e)
    return r


def send_document(chat, path, caption=""):
    bd = "----orgbot%d" % random.randint(10 ** 8, 10 ** 9)
    def part(name, val):
        return ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (bd, name, val)).encode()
    fn = os.path.basename(path)
    body = part("chat_id", chat) + part("caption", caption)
    body += ("--%s\r\nContent-Disposition: form-data; name=\"document\"; filename=\"%s\"\r\nContent-Type: application/octet-stream\r\n\r\n" % (bd, fn.replace('"', ""))).encode()
    body += open(path, "rb").read() + ("\r\n--%s--\r\n" % bd).encode()
    req = urllib.request.Request("%s/bot%s/sendDocument" % (API, TOKEN), body, {"Content-Type": "multipart/form-data; boundary=" + bd})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def send_deliverable(chat, p):
    """يرسل الملف نصاً داخل المحادثة (ما يحتاج فتح أي رابط) + نسخة مرفقة (.md تُرسل كـ .txt)."""
    name = os.path.basename(p)
    stem, ext = os.path.splitext(name)
    ext = ext.lower()
    if ext in (".md", ".txt", ".csv", ".json"):
        txt = open(p, encoding="utf-8", errors="replace").read()
        if len(txt) <= 12000:
            send(chat, "📄 %s\n\n%s" % (name, txt))
        else:
            send(chat, "📄 %s طويل (%d حرف) فأرسلته كمرفق بالأسفل." % (name, len(txt)))
    ap = p
    if ext == ".md":
        d = tempfile.mkdtemp()
        ap = os.path.join(d, stem + ".txt")
        shutil.copy(p, ap)
    send_document(chat, ap, defang("📎 " + os.path.basename(ap)))


class IO:
    """قناة الوكيل إليك: رسائل، تقدّم، ملفات، طلبات موافقة."""
    def __init__(self, org, chat):
        self.org, self.chat = org, chat

    def send(self, text, buttons=None):
        send(self.chat, text, buttons)

    def progress(self, text):
        if self.org.kget("verbose", "1") == "1":
            send(self.chat, text)

    def approvals(self):
        notify_new_approvals(self.org, self.chat)

    def send_file(self, path, caption=""):
        send_document(self.chat, path, caption)

    def finish(self, tid, res):
        send(self.chat, "✅ سلّم الوكيل المهمة #%d\n\n%s" % (tid, res[:3300]),
             [[{"text": "✅ قبول", "callback_data": "rv:%d:ok" % tid}, {"text": "🔁 تعديل", "callback_data": "rv:%d:rv" % tid},
               {"text": "❌ رفض", "callback_data": "rv:%d:no" % tid}]])
        try:
            for p in tools.deliverables(self.org, tid):
                send_deliverable(self.chat, p)
        except Exception as e:
            log("deliverables failed:", e)


def owner():
    if os.environ.get("OWNER_CHAT_ID", "").strip().lstrip("-").isdigit():
        return int(os.environ["OWNER_CHAT_ID"].strip())
    try:
        return json.load(open(OWNER_F))["chat_id"]
    except Exception:
        return None


def pair():
    code = "%06d" % random.randint(0, 999999)
    print("\nأرسل للبوت في تلقرام بالضبط:\n\n    /start %s\n\nأنتظر..." % code, flush=True)
    off = 0
    while True:
        try:
            r = tg("getUpdates", _wait=25, offset=off)
        except Exception as e:
            log("poll error:", e)
            time.sleep(3)
            continue
        for u in r.get("result", []):
            off = u["update_id"] + 1
            m = u.get("message") or {}
            if (m.get("text") or "").strip() == "/start " + code:
                with open(OWNER_F, "w") as f:
                    json.dump({"chat_id": m["chat"]["id"]}, f)
                os.chmod(OWNER_F, 0o600)
                send(m["chat"]["id"], "تم الربط ✅")
                print("paired OK")
                return


HELP = """👑 الرئيس التنفيذي جاهز. الأوامر:
/goal الهدف — الرئيس يحلله ويوزّع مهام على الإدارات (اكتب هدفاً ينفّذه نموذج لغوي فعلاً: بحث، تقرير، كود، ملفات)
/org — الهيكل الحالي
/tasks — المهام المفتوحة   /task رقم — تفاصيل مهمة
/approvals — طلبات بانتظار موافقتك
/approve رقم   /reject رقم
/assign رقم_مهمة رقم_وكيل — إسناد يدوي
/submit رقم_مهمة النتيجة — تسليم يدوي (للتجربة)
/review رقم ok|revise|reject [تقييم 1-5] [ملاحظة] — مراجعتك للنتيجة
/go — ينفّذ كل مهام آخر خطة بالترتيب (الأفضل)\n/run رقم_مهمة — ينفّذ مهمة وحدها
/runs — حالة التشغيلات   /stop   /resume
/steps رقم_مهمة — خطوات الوكيل   /files رقم_مهمة — ملفاته   /file رقم_مهمة اسم_ملف — يرسله لك
/every 6h هدف — يشغّل الهدف تلقائياً كل مدة   /schedules   /unschedule رقم
/watch رابط change|up|word:كلمة [30m] — مراقبة/فحص   /watches   /unwatch رقم
/verbose on|off — إظهار خطوات الوكيل أثناء العمل
/model — نموذج كل وكيل   /model رقم اسم_نموذج — تعيين
/audit on|off — مدقق مستقل يراجع مراجعات المدير
/parallel رقم — عدد الوكلاء المتزامنين (1-4)
/inbox رقم_وكيل — رسائل الوكيل الداخلية
/remember معلومة — ذاكرة مشتركة   /memory كلمة — بحث في الذاكرة
/ceo — دخول إلى المحادثة المباشرة مع الرئيس
/ceo_off — إنهاء وضع المحادثة المباشرة
/review_org — تدقيق المؤسسة
/improve — مقترحات تطوير
/note نص — تسجيل ملاحظة للمتابعة
/close 41 42 — إغلاق مهام قديمة أو تجريبية
/experience — سجل التجارب والدروس (ماذا تعلّم الوكلاء)
/notes — سجل الملاحظات
/report — تقرير   /help"""


def fmt_task_line(t):
    tid, title, st, dept, ag = t
    return "#%d [%s] %s — %s → %s" % (tid, orgx.STATUS_AR.get(st, st), title, dept or "بدون إدارة", ag or "بدون مسؤول")


def notify_new_approvals(org, chat):
    last = int(org.kget("ap_notified", "0"))
    for aid, kind, p in org.pending_approvals():
        if aid > last:
            send(chat, "🔔 طلب موافقة #%d\n%s" % (aid, org.describe(kind, p)),
                 [[{"text": "✅ وافق", "callback_data": "ap:%d:1" % aid}, {"text": "❌ ارفض", "callback_data": "ap:%d:0" % aid}]])
            last = aid
    org.kset("ap_notified", last)


def cmd(org, chat, text):
    parts = text.split(None, 1)
    c = parts[0].split("@")[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    try:
        if c in ("/start", "/help"):
            return send(chat, HELP)
        if c == "/ceo":
            ceo_advisor.ensure(org)
            org.kset("ceo_chat_mode", "on")
            if arg:  # /ceo مع سؤال في نفس الرسالة: نفعّل الوضع ونجاوب فوراً
                send(chat, "👑 الرئيس التنفيذي يراجع سياق المؤسسة...")
                try:
                    return send(chat, ceo_advisor.chat(org, arg))
                except ceo_brain.BudgetExceeded as e:
                    return send(chat, "⛔ " + str(e))
                except Exception as e:
                    return send(chat, "تعذر إكمال الرد: %s: %s" % (type(e).__name__, str(e)[:180]))
            return send(chat, "👑 بدأت المحادثة المباشرة مع الرئيس التنفيذي. اكتب سؤالك أو ناقش أي موضوع مؤسسي. للخروج: /ceo_off")
        if c == "/ceo_off":
            org.kset("ceo_chat_mode", "off")
            return send(chat, "تم إنهاء وضع المحادثة المباشرة. أوامر المؤسسة ما زالت تعمل كالمعتاد.")
        if c in ("/experience", "/lessons"):
            import exper
            return send(chat, exper.summary(org))
        if c == "/close":
            ids = [int(x) for x in re.findall(r"\d+", arg)]
            if not ids:
                return send(chat, "الصيغة: /close 41 42 43  (أرقام المهام اللي تبي تقفلها)")
            done, skipped = [], []
            for i in ids[:20]:
                t = org.task(i)
                if not t or t[3] in ("done", "rejected"):
                    skipped.append(i)
                    continue
                org.x("UPDATE tasks SET status='rejected',updated_at=? WHERE id=?", (orgx.now(), i))
                org.log("owner", "task_closed", "task=%d" % i)
                done.append(i)
            return send(chat, ("🗂 أُغلقت: %s" % ", ".join("#%d" % i for i in done) if done else "ما أُغلقت أي مهمة.") + (("\nتخطّيت (غير موجودة أو مقفلة أصلاً): %s" % ", ".join("#%d" % i for i in skipped)) if skipped else ""))
        if c == "/note":
            nid = ceo_advisor.add_note(org, arg)
            return send(chat, "🗒 حُفظت الملاحظة #%d في سجل الرئيس التنفيذي، وأُضيفت إلى ذاكرة المؤسسة." % nid)
        if c == "/notes":
            return send(chat, ceo_advisor.list_notes(org))
        if c == "/note_done":
            title = ceo_advisor.close_note(org, int(arg))
            return send(chat, "✅ أُغلقت الملاحظة #%s: %s" % (arg, title))
        if c == "/ceo_feedback":
            w = arg.split(None, 1)
            if not w or not w[0].isdigit() or int(w[0]) not in range(1, 6):
                return send(chat, "الصيغة: /ceo_feedback 1-5 تعليقك أو سبب التصحيح")
            feedback = w[1] if len(w) > 1 else "تقييم المالك"
            ceo_advisor.record_feedback(org, "آخر إجابة للرئيس", "تقييم %s/5: %s" % (w[0], feedback))
            return send(chat, "🧠 سُجل تقييمك وتغذيتك الراجعة للرئيس التنفيذي.")
        if c == "/review_org":
            send(chat, "🔎 الرئيس التنفيذي يراجع بيانات المؤسسة المسجلة...")
            result, nid = ceo_advisor.review_org(org)
            return send(chat, "📋 تدقيق المؤسسة — سجل #%d\n\n%s" % (nid, result))
        if c == "/improve":
            send(chat, "💡 الرئيس التنفيذي يحلل فرص التطوير...")
            result, nid = ceo_advisor.improvement_plan(org)
            return send(chat, "🚀 مقترحات تطوير — سجل #%d\n\n%s" % (nid, result))
        if c == "/goal":
            if not arg:
                return send(chat, "اكتب الهدف بعد الأمر. مثال:\n/goal ابحث عن أفضل 5 أدوات مجانية لتحرير الفيديو على الجوال واكتب مقارنة في ملف")
            send(chat, "⏳ الرئيس التنفيذي يحلل الهدف...")
            r = ceo_brain.plan_goal(org, arg)
            L = ["👑 خطة الرئيس التنفيذي", r["summary"], ""]
            for tid, title, dept, ag, ok in r["tasks"]:
                L.append("#%d %s\n   📁 %s → %s" % (tid, title, dept, ("👤 " + ag) if ag else "⏸ بانتظار تعيين مدير/إدارة"))
            L.append("\nلتنفيذ الخطة كاملة بالترتيب: /go\n(أو مهمة وحدها: /run رقم_المهمة)")
            send(chat, "\n".join(L))
            notify_new_approvals(org, chat)
            return
        if c == "/run":
            rid = agent_run.start(org, int(arg))
            io = IO(org, chat)
            t = org.task(int(arg))
            send(chat, "▶️ بدأ التشغيل #%d للمهمة #%s: %s\n(الإيقاف: /stop)" % (rid, arg, t[1]))
            agent_run.launch(org, io, rid)
            return
        if c == "/go":
            ids = agent_run.go(org, IO(org, chat))
            return send(chat, "🚀 بدأت تنفيذ خطة الرئيس بالترتيب: " + " ← ".join("#%d" % i for i in ids) + "\nكل مهمة تستفيد من نتائج اللي قبلها. للإيقاف: /stop")
        if c == "/model":
            w = arg.split()
            if len(w) == 2:
                aid, prof = int(w[0]), w[1]
                if not org.agent(aid):
                    raise orgx.OrgError("الوكيل #%d غير موجود" % aid)
                if prof != "default" and prof not in ceo_brain.profile_names():
                    raise orgx.OrgError("النموذج «%s» غير معرّف في models.json. المعرّف: %s" % (prof, "، ".join(ceo_brain.profile_names()) or "لا شي"))
                org.kset("model_%d" % aid, prof)
                return send(chat, "✅ الوكيل #%d يستخدم الآن نموذج «%s»" % (aid, prof))
            L = ["النماذج المعرّفة (models.json): " + ("، ".join(ceo_brain.profile_names()) or "لا شي — الكل يستخدم نموذجك الافتراضي")]
            for aid, name, role in org.q("SELECT id,name,role FROM agents WHERE status='active'"):
                L.append("#%d %s → %s" % (aid, name, org.kget("model_%d" % aid, "default")))
            L.append("\nالتدقيق المستقل: " + ("مفعّل" if tools.audit_enabled(org) else "مغلق") + "\nلتعيين: /model رقم_الوكيل اسم_النموذج")
            return send(chat, "\n".join(L))
        if c == "/audit":
            org.kset("audit", "on" if arg.lower() in ("on", "1", "نعم") else "off")
            return send(chat, "التدقيق المستقل: " + ("مفعّل" if tools.audit_enabled(org) else "مغلق (إلا إذا عرّفت نموذج auditor)"))
        if c == "/parallel":
            org.kset("parallel", max(1, min(4, int(arg))))
            return send(chat, "التشغيل المتوازي: حتى %s وكلاء بنفس الوقت" % org.kget("parallel"))
        if c == "/every":
            w = arg.split(None, 1)
            if len(w) < 2:
                raise ValueError
            sid = ext.add_schedule(org, w[0], w[1])
            return send(chat, "⏰ جدول #%d: كل %s أنفّذ: %s\n(يعمل تلقائياً ويصلك الناتج. للحذف: /unschedule %d)" % (sid, w[0], w[1][:80], sid))
        if c == "/schedules":
            return send(chat, ext.list_schedules(org))
        if c == "/unschedule":
            ext.remove_schedule(org, int(arg))
            return send(chat, "🗑 حُذف الجدول #%s" % arg)
        if c == "/watch":
            w = arg.split()
            if len(w) < 2:
                raise orgx.OrgError("الصيغة: /watch الرابط النمط [المدة]\nالنمط: change أو up أو word:كلمة. مثال:\n/watch https://example.com change 1h")
            wid = ext.add_watch(org, w[0], w[1], w[2] if len(w) > 2 else "30m")
            return send(chat, "👁 بدأت مراقبة #%d. أنبّهك عند أي تغيّر. (للحذف: /unwatch %d)" % (wid, wid))
        if c == "/watches":
            return send(chat, ext.list_watches(org))
        if c == "/unwatch":
            ext.remove_watch(org, int(arg))
            return send(chat, "🗑 أوقفت المراقبة #%s" % arg)
        if c == "/runs":
            return send(chat, agent_run.runs_summary(org))
        if c == "/stop":
            rid = agent_run.stop(org, int(arg) if arg else None)
            return send(chat, "⏹ أوقفت التشغيل #%d" % rid)
        if c == "/resume":
            ids = agent_run.resume(org, IO(org, chat), int(arg) if arg else None)
            return send(chat, "▶️ استأنفت: " + " ".join("#%d" % i for i in ids))
        if c == "/verbose":
            org.kset("verbose", "0" if arg.lower() in ("off", "0", "لا") else "1")
            return send(chat, "تم. عرض الخطوات: %s" % ("مفعّل" if org.kget("verbose") == "1" else "مغلق"))
        if c == "/steps":
            rows = org.steps(int(arg), last=10)
            return send(chat, "\n\n".join("%s) %s\n%s\n→ %s" % (n, a, str(ar)[:150], str(o)[:250]) for n, th, a, ar, o in rows) if rows else "ما فيه خطوات لهذي المهمة.")
        if c == "/files":
            return send(chat, tools.t_list_files({"dir": tools.workdir_for(org, int(arg))[0]}, {}))
        if c == "/file":
            tid, rel = arg.split(None, 1)
            p = tools.safe_path({"dir": tools.workdir_for(org, int(tid))[0]}, rel.strip())
            if not os.path.isfile(p):
                return send(chat, "الملف غير موجود.")
            send_deliverable(chat, p)
            return
        if c == "/org":
            return send(chat, org.tree())
        if c == "/tasks":
            rows = org.open_tasks()
            return send(chat, "\n".join(fmt_task_line(t) for t in rows) if rows else "ما فيه مهام مفتوحة.")
        if c == "/task":
            t = org.task(int(arg))
            if not t:
                return send(chat, "المهمة غير موجودة.")
            ag = org.agent(t[4])
            return send(chat, "#%d %s\nالحالة: %s | المسؤول: %s | الأولوية: %s\n\n%s%s%s" % (
                t[0], t[1], orgx.STATUS_AR.get(t[3], t[3]), ag[1] if ag else "—", t[8], t[2],
                ("\n\n📄 النتيجة:\n" + t[6]) if t[6] else "", ("\n⭐ التقييم: %s" % t[7]) if t[7] is not None else ""))
        if c == "/approvals":
            pa = org.pending_approvals()
            if not pa:
                return send(chat, "ما فيه طلبات بانتظارك ✅")
            for aid, kind, p in pa:
                send(chat, "🔔 طلب #%d\n%s" % (aid, org.describe(kind, p)),
                     [[{"text": "✅ وافق", "callback_data": "ap:%d:1" % aid}, {"text": "❌ ارفض", "callback_data": "ap:%d:0" % aid}]])
            return
        if c in ("/approve", "/reject"):
            res = org.decide(int(arg), c == "/approve")
            send(chat, res)
            agent_run.on_decision(org, IO(org, chat), int(arg), c == "/approve")
            return notify_new_approvals(org, chat)
        if c == "/assign":
            t, a = arg.split()[:2]
            org.assign(int(t), int(a), by="owner")
            return send(chat, "✅ أُسندت المهمة #%s للوكيل #%s" % (t, a))
        if c == "/submit":
            t, res = arg.split(None, 1)
            task = org.task(int(t))
            if not task or not task[4]:
                return send(chat, "المهمة غير موجودة أو بدون مسؤول.")
            org.submit(int(t), task[4], res)
            return send(chat, "✅ سُلّمت المهمة #%s للمراجعة" % t)
        if c == "/review":
            w = arg.split(None, 3)
            tid, verdict = int(w[0]), w[1].lower()
            score, notes = None, ""
            rest = w[2:]
            if rest and re.fullmatch(r"[1-5](\.\d)?", rest[0]):
                score = float(rest[0])
                rest = rest[1:]
            notes = " ".join(rest)
            org.review(tid, "owner", verdict, score, notes)
            return send(chat, "✅ سُجّلت مراجعتك للمهمة #%d (%s)" % (tid, verdict))
        if c == "/inbox":
            rows = org.inbox(int(arg), unread_only=False, mark=False)
            return send(chat, "\n".join("%s %s" % (r[1][5:16], r[5][:150]) for r in rows) if rows else "الصندوق فاضي.")
        if c == "/remember":
            if not arg:
                return send(chat, "اكتب المعلومة بعد الأمر.")
            org.remember(arg, topic="owner", weight=2.0)
            return send(chat, "🧠 حفظتها في الذاكرة المشتركة.")
        if c == "/memory":
            rows = org.recall(arg, k=6)
            return send(chat, "\n".join("• " + t for _, t in rows) if rows else "ما لقيت شي مطابق.")
        if c == "/report":
            return send(chat, org.report())
        return send(chat, "ما فهمت. اكتب /help")
    except ceo_brain.BudgetExceeded as e:
        return send(chat, "⛔ " + str(e))
    except orgx.OrgError as e:
        return send(chat, "⚠️ %s" % e)
    except (ValueError, IndexError):
        return send(chat, "⚠️ صيغة الأمر غير صحيحة. اكتب /help")
    except Exception as e:
        log("command error:", type(e).__name__, e)
        return send(chat, "صار خطأ: %s: %s" % (type(e).__name__, str(e)[:200]))


def on_callback(org, cb, own):
    if cb["from"]["id"] != own:
        return
    d = cb.get("data", "")
    rv = re.match(r"rv:(\d+):(ok|rv|no)$", d)
    if rv:
        return on_review_cb(org, cb, own, int(rv.group(1)), rv.group(2))
    m = re.match(r"ap:(\d+):([01])$", d)
    if not m:
        return
    try:
        res = org.decide(int(m.group(1)), m.group(2) == "1")
        agent_run.on_decision(org, IO(org, own), int(m.group(1)), m.group(2) == "1")
    except orgx.OrgError as e:
        res = "⚠️ %s" % e
    tg("answerCallbackQuery", callback_query_id=cb["id"], text="تم")
    msg = cb.get("message")
    if msg:
        try:
            tg("editMessageReplyMarkup", chat_id=msg["chat"]["id"], message_id=msg["message_id"], reply_markup={"inline_keyboard": []})
        except Exception:
            pass
    send(own, res)
    notify_new_approvals(org, own)


def on_review_cb(org, cb, own, tid, what):
    tg("answerCallbackQuery", callback_query_id=cb["id"], text="تم")
    msg = cb.get("message")
    if msg:
        try:
            tg("editMessageReplyMarkup", chat_id=msg["chat"]["id"], message_id=msg["message_id"], reply_markup={"inline_keyboard": []})
        except Exception:
            pass
    try:
        if what == "ok":
            org.review(tid, "owner", "ok", None, "")
            send(own, "✅ قبلت المهمة #%d. (تقدر تعطي تقييماً: /review %d ok 5 ملاحظة)" % (tid, tid))
        elif what == "no":
            org.review(tid, "owner", "reject", None, "رفضها المالك")
            send(own, "❌ رفضت المهمة #%d" % tid)
        else:
            org.kset("await_note", tid)
            send(own, "🔁 اكتب الآن ملاحظاتك على المهمة #%d (رسالة نص عادية) وأعيد التشغيل بها." % tid)
    except orgx.OrgError as e:
        send(own, "⚠️ %s" % e)


def handle_text(org, own, t):
    aw = org.kget("await_note", "")
    if aw:
        org.kset("await_note", "")
        try:
            org.review(int(aw), "owner", "revise", None, t)
            rid = agent_run.start(org, int(aw))
            send(own, "🔁 سجّلت ملاحظتك وبدأ تشغيل جديد #%d للمهمة #%s" % (rid, aw))
            agent_run.launch(org, IO(org, own), rid)
        except orgx.OrgError as e:
            send(own, "⚠️ %s" % e)
        return
    if agent_run.owner_reply(org, IO(org, own), t):
        return send(own, "👍 وصل ردّك للوكيل، يكمل الشغل...")
    if org.kget("ceo_chat_mode", "off") == "on":
        send(own, "👑 الرئيس التنفيذي يراجع سياق المؤسسة...")
        try:
            return send(own, ceo_advisor.chat(org, t))
        except ceo_brain.BudgetExceeded as e:
            return send(own, "⛔ " + str(e))
        except Exception as e:
            log("CEO chat error:", type(e).__name__, e)
            return send(own, "تعذر إكمال الرد: %s: %s" % (type(e).__name__, str(e)[:180]))
    send(own, "للدردشة مع الرئيس اكتب /ceo، أو أرسل هدفاً باستخدام /goal.\nاكتب /help لعرض الأوامر.")


def handle(org, u, own):
    if "callback_query" in u:
        return on_callback(org, u["callback_query"], own)
    m = u.get("message")
    if not m:
        return
    if m["chat"]["id"] != own:
        log("ignored stranger", m["chat"]["id"])
        return
    t = (m.get("text") or "").strip()
    if t.startswith("/"):
        cmd(org, own, t)
    elif t:
        handle_text(org, own, t)


def poll(org, own, wait):
    off = int(org.kget("tg_offset", "0"))
    r = tg("getUpdates", _wait=wait, offset=off, allowed_updates=["message", "callback_query"])
    for u in r.get("result", []):
        try:
            handle(org, u, own)
        except Exception as e:
            log("handler error:", e)
        org.kset("tg_offset", u["update_id"] + 1)
    return len(r.get("result", []))


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else ""
    if a == "pair":
        pair()
    elif a == "cloud":
        secs = int(sys.argv[2]) if len(sys.argv) > 2 else 270
        own = owner()
        if not own:
            sys.exit("ما فيه OWNER_CHAT_ID")
        org = orgx.Org()
        org.ceo_id(); org.ensure_departments(); org.link_existing_managers(); ext.ensure(org); ceo_advisor.ensure(org)
        io = IO(org, own)
        deadline = time.time() + secs
        log("cloud run for %ds" % secs)
        agent_run.resume_orphans(org, io)
        while time.time() < deadline - 2:
            try:
                poll(org, own, max(1, min(25, int(deadline - time.time()))))
                agent_run.tick(org, io)
                ext.tick(org, io)
            except Exception as e:
                log("cloud loop error:", e)
                time.sleep(3)
        for _ in range(60):  # نمهل الخطوات الجارية لتنتهي
            if not agent_run.LIVE:
                break
            time.sleep(1)
        log("cloud run done; live runs left:", len(agent_run.LIVE))
    elif a in ("run", "once"):
        own = owner()
        if not own:
            sys.exit("ما فيه owner.json: شغّل  python org_bot.py pair")
        org = orgx.Org()
        org.ceo_id()
        org.ensure_departments()
        org.link_existing_managers()
        ext.ensure(org)
        ceo_advisor.ensure(org)
        if a == "once":
            n = poll(org, own, 0)
            print("processed", n)
        else:
            log("org bot running")
            agent_run.resume_orphans(org, IO(org, own))
            while True:
                try:
                    poll(org, own, 25)
                    agent_run.tick(org, IO(org, own))
                    ext.tick(org, IO(org, own))
                except Exception as e:
                    log("poll error:", e)
                    time.sleep(5)
    else:
        print(__doc__)
