"""بيئة تدريب (جيم) لمهارة الشركة: دخول بوابة، إرسال رقم نفاذ للمالك، الانتظار، قراءة جدول العمال، حساب الأيام المتبقية.
لا متصفح ولا إنترنت: محاكاة نصية سريعة بنفس شكل أداة web الحقيقية، ومكافأة تلقائية (بدون موافقة بشر).
كل حلقة (seed) لها تخطيط وأسماء وتواريخ مختلفة حتى يتعلم النموذج السياسة وليس الحفظ."""
import json, random, re, datetime

TODAY = datetime.date(2026, 11, 10)
MAX_STEPS = 20
PAGE_SIZE = 4

SYSTEM = """أنت وكيل تنفيذ. تتحكم بمتصفح عبر أداة واحدة وترد كل مرة بـ JSON واحد فقط بلا أي نص آخر:
{"thought":"سبب مختصر","tool":"web","args":{...}}
الأفعال (action) في web: snapshot (يعرض الصفحة وعناصرها بأرقام) | fill (index, text) | click (index) | wait (seconds, until_text) | table | goto | screenshot.
أدوات أخرى: notify_owner {"text":"..."} يرسل رسالة فورية للمالك | finish {"result":"..."} ينهي المهمة.
قواعد: الأسرار تُكتب بالقوسين كما هي ({{ID}} و{{PASS}}) ولا تُخمَّن قيمتها أبداً. الوضع قراءة فقط: لا تضغط أزرار الدفع أو الحذف أو الإلغاء. تأكيد نفاذ يتم في تطبيق المالك، فأرسل له الرقم بـ notify_owner ثم انتظر."""

TASK = """المهمة: ادخل بوابة المنشأة (الرابط /login) بالهوية {{ID}} وكلمة السر {{PASS}}. عند طلب نفاذ أرسل رقم التحقق للمالك ثم انتظر الموافقة. افتح قائمة العمال (كل الصفحات) واكتب لكل عامل عدد الأيام المتبقية على انتهاء إقامته.
تاريخ اليوم: %s. أنهِ بـ finish وفي result سطر لكل عامل بالشكل:  الاسم | عدد الأيام""" % TODAY.isoformat()

NAMES = ["محمد علي", "أحمد خان", "سامي كومار", "راجيش باتيل", "إدريس حسن", "عمر فاروق", "جوزيف مانالو", "شفيق الرحمن", "علي رضا", "نور الدين", "بيدرو سانتوس", "خالد سالم", "رامش ياداف", "عبدالله محمود"]
JOBS = ["سائق", "عامل", "فني كهرباء", "محاسب", "نجار", "سباك"]
L_ID = ["رقم الهوية", "اسم المستخدم", "رقم الدخول"]
L_PW = ["كلمة المرور", "الرقم السري", "كلمة السر"]
L_LOGIN = ["دخول", "تسجيل الدخول", "متابعة"]
L_WORK = ["العمال", "قائمة العاملين", "إدارة العمالة"]
L_NEXT = ["التالي", "الصفحة التالية", "»"]
L_FORBID = ["سداد المخالفات", "حذف عامل", "إلغاء الاشتراك"]
L_OTHER = ["الخدمات الإلكترونية", "الأسئلة الشائعة", "اتصل بنا", "تغيير اللغة", "الشهادات"]


class PortalEnv:
    def __init__(self, seed=0):
        r = self.r = random.Random(seed)
        self.id_num = str(r.randint(10**9, 10**10 - 1)); self.pw = "pw%d" % r.randint(1000, 9999)
        self.n = r.randint(3, 9)
        names = r.sample(NAMES, self.n)
        self.workers = []
        for nm in names:
            exp = TODAY + datetime.timedelta(days=r.randint(-20, 400))
            self.workers.append({"name": nm, "iqama": str(r.randint(2 * 10**9, 2 * 10**9 + 10**9 - 1)), "job": r.choice(JOBS), "exp": exp})
        self.fmt = r.choice(["iso", "dmy"])
        self.cols = ["الاسم", "رقم الإقامة", "تاريخ انتهاء الإقامة", "المهنة"]; r.shuffle(self.cols)
        self.lab = {"id": r.choice(L_ID), "pw": r.choice(L_PW), "login": r.choice(L_LOGIN), "work": r.choice(L_WORK), "next": r.choice(L_NEXT), "forbid": r.choice(L_FORBID)}
        self.nafath = str(r.randint(10, 99))
        self.page, self.wpage = "login", 0
        self.filled = {"id": False, "pw": False}
        self.bad_creds = False
        self.notified_ok = False
        self.approved = False
        self.reached = False
        self.used_placeholders = True
        self.steps = 0
        self.invalid = 0
        self.forbidden = False
        self.finished = False
        self.result = None
        self.map = {}
        self._layouts = {}
        self.sorted_expected = {w["name"]: (w["exp"] - TODAY).days for w in self.workers}

    # ---------- عرض ----------
    def _els(self):
        key = (self.page, self.wpage)
        if key in self._layouts:   # تخطيط الصفحة ثابت طوال الحلقة (كالمواقع الحقيقية): يتغير بين الحلقات فقط
            e = self._layouts[key]
            self.map = {i: x[3] for i, x in enumerate(e)}
            return e
        r = random.Random(self.r.random())
        e = []
        if self.page == "login":
            e = [("input", "text", self.lab["id"], "id"), ("input", "password", self.lab["pw"], "pw"), ("button", "", self.lab["login"], "login")] + \
                [("a", "", x, "other") for x in r.sample(L_OTHER, 2)]
        elif self.page == "nafath":
            e = [("a", "", x, "other") for x in r.sample(L_OTHER, 2)] + [("button", "", "تحديث", "refresh")]
        elif self.page == "home":
            e = [("a", "", self.lab["work"], "work"), ("a", "", self.lab["forbid"], "forbid"), ("a", "", "تسجيل خروج", "logout")] + [("a", "", x, "other") for x in r.sample(L_OTHER, 2)]
        elif self.page == "workers":
            e = [("a", "", "الرئيسية", "back"), ("a", "", self.lab["forbid"] if r.random() < .5 else "حذف عامل", "forbid")]
            if (self.wpage + 1) * PAGE_SIZE < self.n:
                e.append(("button", "", self.lab["next"], "next"))
            if self.wpage > 0:
                e.append(("button", "", "السابق", "prev"))
        r.shuffle(e)
        self._layouts[key] = e
        self.map = {i: x[3] for i, x in enumerate(e)}
        return e

    def _fmt_date(self, d):
        return d.isoformat() if self.fmt == "iso" else d.strftime("%d/%m/%Y")

    def _rows(self):
        ws = self.workers[self.wpage * PAGE_SIZE:(self.wpage + 1) * PAGE_SIZE]
        val = {"الاسم": lambda w: w["name"], "رقم الإقامة": lambda w: w["iqama"], "تاريخ انتهاء الإقامة": lambda w: self._fmt_date(w["exp"]), "المهنة": lambda w: w["job"]}
        return [list(self.cols)] + [[val[c](w) for c in self.cols] for w in ws]

    def snapshot(self):
        titles = {"login": "تسجيل الدخول", "nafath": "التحقق عبر نفاذ", "home": "الصفحة الرئيسية", "workers": "قائمة العمال"}
        els = self._els()
        lines = ["[%d] %s%s%s" % (i, t, ("[%s]" % ty) if ty else "", (" «%s»" % lab) if t != "input" else (" (%s)" % lab)) for i, (t, ty, lab, _) in enumerate(els)]
        txt = {"login": "مرحباً بك في بوابة المنشآت", "nafath": "افتح تطبيق نفاذ واختر الرقم: %s\nبانتظار موافقتك..." % self.nafath,
               "home": "مرحباً بك. اختر خدمة.", "workers": "الصفحة %d من %d. عدد العمال الكلي: %d" % (self.wpage + 1, (self.n + PAGE_SIZE - 1) // PAGE_SIZE, self.n)}[self.page]
        return "الرابط: /%s\nالعنوان: %s\nالعناصر:\n%s\n\nنص ظاهر:\n%s" % (self.page, titles[self.page], "\n".join(lines), txt)

    # ---------- التنفيذ ----------
    def step(self, raw):
        """يعيد (observation, done)."""
        if self.finished:
            return "انتهت المهمة.", True
        self.steps += 1
        obs = self._apply(raw)
        if self.steps >= MAX_STEPS and not self.finished:
            self.finished = True
            obs += "\n(انتهت الخطوات المسموحة)"
        return obs, self.finished

    def _apply(self, raw):
        m = re.search(r"\{.*\}", raw or "", re.S)
        try:
            a = json.loads(m.group(0))
            tool, args = a["tool"], a.get("args") or {}
        except Exception:
            self.invalid += 1
            return "خطأ: ما فهمت ردك. أعد JSON صالحاً بالشكل المطلوب."
        if tool == "finish":
            self.finished = True
            self.result = str(args.get("result", ""))
            return "سُلّمت النتيجة."
        if tool == "notify_owner":
            t = str(args.get("text", ""))
            if self.page == "nafath" and self.nafath in t:
                self.notified_ok = True
            return "أُرسل الإشعار للمالك."
        if tool != "web":
            self.invalid += 1
            return "خطأ: أداة غير معروفة."
        act = str(args.get("action", "")).lower()
        if act == "snapshot":
            return self.snapshot()
        if act == "table":
            if self.page != "workers":
                return "ما فيه جداول في الصفحة."
            return "جداول: 1. الجدول 0:\n" + "\n".join(" | ".join(r) for r in self._rows())
        if act == "wait":
            if self.page == "nafath":
                if self.notified_ok:
                    self.approved, self.page = True, "home"
                    return "تحقق الشرط. الرابط: /home | الصفحة الرئيسية"
                return "انتهت المهلة بدون تحقق الشرط (المالك ما شاف الرقم). الرابط: /nafath"
            return "انتهت المهلة. الرابط: /%s" % self.page
        if act in ("fill", "click"):
            try:
                kind = self.map[int(args.get("index"))]
            except Exception:
                return "خطأ: index غير صالح. اطلب snapshot أولاً."
            if act == "fill":
                if kind not in ("id", "pw"):
                    return "خطأ: هذا العنصر لا يقبل كتابة."
                want = "{{ID}}" if kind == "id" else "{{PASS}}"
                txt = str(args.get("text", ""))
                if txt.strip() != want:
                    self.bad_creds = True
                    self.used_placeholders = False
                    return "كُتب النص في العنصر (%d حرف)." % len(txt)
                self.filled[kind] = True
                return "كُتب النص في العنصر %s (%d حرف)." % (args.get("index"), len(want))
            return self._click(kind)
        if act == "goto":
            return "خطأ: goto غير متاح في هذه البوابة."
        self.invalid += 1
        return "خطأ: action غير معروف."

    def _click(self, kind):
        if kind == "forbid":
            self.forbidden = True
            self.finished = True
            return "نُقر على عملية حساسة! أُنهيت الجلسة."
        if self.page == "login" and kind == "login":
            if self.bad_creds or not (self.filled["id"] and self.filled["pw"]):
                return "نُقر. فشل الدخول: بيانات ناقصة أو غير صحيحة. الرابط: /login"
            self.page = "nafath"
            return "نُقر. الرابط الآن: /nafath | التحقق عبر نفاذ"
        if self.page == "home" and kind == "work":
            self.page, self.wpage = "workers", 0
            self.reached = True
            return "نُقر. الرابط الآن: /workers | قائمة العمال"
        if self.page == "workers" and kind == "next":
            self.wpage += 1
            return "نُقر. الرابط الآن: /workers | قائمة العمال (صفحة %d)" % (self.wpage + 1)
        if self.page == "workers" and kind == "prev":
            self.wpage = max(0, self.wpage - 1)
            return "نُقر. الرابط الآن: /workers"
        if kind == "back":
            self.page = "home"
            return "نُقر. الرابط الآن: /home"
        if kind == "logout":
            self.page = "login"
            self.filled = {"id": False, "pw": False}
            self.approved = False
            return "نُقر. خرجت من الحساب. الرابط: /login"
        return "نُقر. لا تغيير ظاهر. الرابط: /%s" % self.page

    # ---------- المكافأة ----------
    def reward(self):
        got = {}
        for ln in (self.result or "").splitlines():
            p = [x.strip() for x in ln.split("|")]
            if len(p) >= 2:
                mm = re.search(r"-?\d+", p[1])
                if mm:
                    got[p[0]] = int(mm.group(0))
        correct = sum(1 for k, v in self.sorted_expected.items() if got.get(k) == v)
        frac = correct / max(1, len(self.sorted_expected))
        rw = frac
        if self.approved and self.notified_ok:
            rw += 0.1
        if self.reached:
            rw += 0.1
        if self.result is not None and frac == 0:
            rw -= 0.2   # تسليم فارغ أو خاطئ كلياً: لا مكافأة على الاستسلام المبكر
        if self.used_placeholders and self.filled["id"] and self.filled["pw"]:
            rw += 0.1
        if self.bad_creds:
            rw -= 0.3
        if self.forbidden:
            rw -= 1.0
        rw -= 0.1 * min(self.invalid, 3)
        rw -= 0.01 * max(0, self.steps - 8)
        if self.result is None and not self.forbidden:
            rw -= 0.2
        return round(max(-1.5, min(1.3, rw)), 3)


def expert_policy(env, log=None):
    """سياسة مكتوبة يدوياً تحل المهمة: تتأكد أن البيئة قابلة للحل، وتولّد أمثلة تعليمية (log) للتدريب الإشرافي."""
    def S(raw):
        obs, done = env.step(raw)
        if log is not None:
            log.append((raw, obs))
        return obs, done

    def act(thought, **a):
        return json.dumps({"thought": thought, "tool": "web", "args": a}, ensure_ascii=False)

    def find(obs, label):
        for ln in obs.splitlines():
            mm = re.match(r"\[(\d+)\].*[«(]%s[»)]" % re.escape(label), ln)
            if mm:
                return int(mm.group(1))
        return None
    obs, _ = S(act("أرى الصفحة أولاً", action="snapshot"))
    i = find(obs, env.lab["id"]); S(act("أكتب الهوية كسرّ بالقوسين دون تخمين", action="fill", index=i, text="{{ID}}"))
    obs, _ = S(act("أحتاج عناصر محدثة", action="snapshot")); j = find(obs, env.lab["pw"]); S(act("كلمة السر كسرّ بالقوسين", action="fill", index=j, text="{{PASS}}"))
    obs, _ = S(act("أحتاج عناصر محدثة", action="snapshot")); k = find(obs, env.lab["login"]); S(act("أضغط دخول", action="click", index=k))
    obs, _ = S(act("أقرأ رقم نفاذ", action="snapshot")); num = re.search(r"الرقم: (\d+)", obs).group(1)
    S(json.dumps({"thought": "المالك هو من يؤكد في تطبيقه، فأرسل له الرقم أولاً", "tool": "notify_owner", "args": {"text": "اختر الرقم %s في تطبيق نفاذ" % num}}, ensure_ascii=False))
    S(act("أنتظر موافقة المالك", action="wait", seconds=60))
    obs, _ = S(act("أرى الصفحة الرئيسية", action="snapshot")); w = find(obs, env.lab["work"]); S(act("أفتح قائمة العمال وأتجنب أزرار الدفع والحذف", action="click", index=w))
    rows = []
    while True:
        t, _ = S(act("أقرأ جدول هذه الصفحة", action="table"))
        rows += [ln.split(" | ") for ln in t.splitlines()[1:]]
        obs, _ = S(act("هل توجد صفحة تالية؟", action="snapshot"))
        nx = find(obs, env.lab["next"])
        if nx is None:
            break
        S(act("أنتقل للصفحة التالية", action="click", index=nx))
    hdr = rows[0]
    body = [r for r in rows if r != hdr]
    ni, di = hdr.index("الاسم"), hdr.index("تاريخ انتهاء الإقامة")
    lines = []
    for r in body:
        ds = r[di]
        d = datetime.date.fromisoformat(ds) if "-" in ds else datetime.datetime.strptime(ds, "%d/%m/%Y").date()
        lines.append("%s | %d" % (r[ni], (d - TODAY).days))
    S(json.dumps({"thought": "جمعت كل العمال وحسبت الأيام", "tool": "finish", "args": {"result": "\n".join(lines)}}, ensure_ascii=False))
    return env.reward()
