# أدوات التنفيذ الإضافية: طلبات API، شل، GitHub، إيميل، قناة تلقرام، جدولة/مراقبة، متصفح.
# كل أداة تغيّر شيئاً في العالم الخارجي تمر على موافقة المالك (risk = "ask").
import os, re, json, time, subprocess, smtplib, ssl, mimetypes, urllib.request, urllib.parse, urllib.error
from email.message import EmailMessage
import tools, ext
from tools import ToolError

_SECRET_WORDS = re.compile(r"TOKEN|KEY|PASS|SECRET|PAT|PWD|CREDENTIAL|^API_|^GH_|^SMTP_|STATE|BSKY|GROQ|GEMINI|MODELS_JSON", re.I)


def _env(name, default=None):
    v = os.environ.get(name)
    return v.strip() if v and v.strip() else default


def _clean_env():
    """بيئة نظيفة للشل: بدون أي سر."""
    return {k: v for k, v in os.environ.items() if not _SECRET_WORDS.search(k)}


def _http(method, url, headers=None, body=None, timeout=30):
    req = urllib.request.Request(url, body, headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        raise ToolError("فشل الاتصال: %s" % str(e)[:150])


# ---------- 1) طلب API عام ----------
def _subst(v):
    """{{API_1}} -> قيمة السر من البيئة (فقط الأسماء التي تبدأ بـ API_)"""
    def rep(m):
        n = m.group(1)
        if not n.startswith("API_"):
            raise ToolError("الأسرار المسموحة في الطلب تبدأ بـ API_ فقط (مثل {{API_1}})")
        val = _env(n)
        if val is None:
            raise ToolError("السر %s غير مضبوط" % n)
        return val
    return re.sub(r"\{\{([A-Za-z0-9_]+)\}\}", rep, v) if isinstance(v, str) else v


def t_http_request(ctx, a):
    method = str(a.get("method", "GET")).upper()
    if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        raise ToolError("method غير مدعوم")
    url = _subst(str(a.get("url", "")))
    tools._check_url(url)
    headers = {str(k): _subst(str(v)) for k, v in (a.get("headers") or {}).items()}
    body = a.get("json", a.get("body"))
    data = None
    if body is not None:
        if isinstance(body, (dict, list)):
            data = json.dumps(body, ensure_ascii=False).encode()
            headers.setdefault("Content-Type", "application/json")
        else:
            data = _subst(str(body)).encode()
    headers.setdefault("User-Agent", "org-agents/1.0")
    st, txt = _http(method, url, headers, data)
    return "HTTP %d\n%s" % (st, txt[:3000])


# ---------- 2) شل ----------
def t_run_shell(ctx, a):
    if os.environ.get("ORG_SHELL") != "1":
        raise ToolError("الشل مفعّل فقط على التشغيل السحابي (GitHub Actions). على الجوال استخدم run_python.")
    cmd = str(a.get("command", "")).strip()
    if not cmd:
        raise ToolError("command فاضي")
    if re.search(r"organization\.db|\.env|owner\.json|rl-agent|/proc/|\.\./|\bgit\s+config\b|\benv\b|\bprintenv\b|/home/runner/work/[^/]+/[^/]+/(?!workspace)", cmd, re.I):
        raise ToolError("الأمر يلمس ملفات النظام/الأسرار. اشتغل داخل مساحة عملك فقط.")
    t = min(int(a.get("timeout", 120) or 120), 240)
    try:
        r = subprocess.run(["bash", "-c", cmd], cwd=ctx["dir"], env=_clean_env(), capture_output=True, text=True, timeout=t)
    except subprocess.TimeoutExpired:
        raise ToolError("انتهت المهلة (%d ثانية)" % t)
    out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
    return "exit=%d\n%s" % (r.returncode, out[-3000:])


# ---------- 3) GitHub ----------
def _gh(method, path, body=None):
    tok = _env("GH_PAT") or _env("GITHUB_TOKEN")
    if not tok:
        raise ToolError("ما فيه توكن GitHub (GH_PAT)")
    base = _env("GITHUB_API", "https://api.github.com")
    h = {"Authorization": "Bearer " + tok, "Accept": "application/vnd.github+json", "User-Agent": "org-agents", "X-GitHub-Api-Version": "2022-11-28"}
    data = json.dumps(body).encode() if body is not None else None
    if data:
        h["Content-Type"] = "application/json"
    st, txt = _http(method, base + path, h, data)
    try:
        js = json.loads(txt) if txt else {}
    except ValueError:
        js = {"raw": txt[:300]}
    if st >= 300:
        raise ToolError("GitHub %d: %s" % (st, str(js.get("message", js))[:200]))
    return js


def _repo(a):
    r = str(a.get("repo", "")).strip()
    if "/" not in r:
        u = _env("GH_USER")
        if not u or not r:
            raise ToolError('repo بصيغة "صاحب/اسم"')
        r = u + "/" + r
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", r):
        raise ToolError("اسم المستودع غير صالح")
    return r


def t_github(ctx, a):
    act = str(a.get("action", "")).strip()
    if act == "create_repo":
        n = str(a.get("name", "")).strip()
        if not re.fullmatch(r"[\w.-]{1,80}", n):
            raise ToolError("اسم المستودع غير صالح")
        r = _gh("POST", "/user/repos", {"name": n, "description": str(a.get("description", ""))[:200], "private": bool(a.get("private", False)), "auto_init": True})
        return "أُنشئ: " + r.get("html_url", n)
    if act == "list_repos":
        r = _gh("GET", "/user/repos?per_page=30&sort=updated")
        return "\n".join("%s%s" % (x["full_name"], " (خاص)" if x.get("private") else "") for x in r) or "لا مستودعات"
    repo = _repo(a)
    if act == "put_file":
        rel = str(a.get("from_file", "")).strip()
        path = str(a.get("path", rel)).strip().lstrip("/")
        if not rel or not path or ".." in path:
            raise ToolError("from_file (ملف من مساحة عملك) و path (مساره في المستودع) مطلوبان")
        p = tools.safe_path(ctx, rel)
        content = open(p, "rb").read()
        import base64
        branch = str(a.get("branch", "") or "")
        q = ("?ref=" + urllib.parse.quote(branch)) if branch else ""
        sha = None
        try:
            sha = _gh("GET", "/repos/%s/contents/%s%s" % (repo, urllib.parse.quote(path), q)).get("sha")
        except ToolError:
            pass
        body = {"message": str(a.get("message", "update " + path))[:200], "content": base64.b64encode(content).decode()}
        if sha:
            body["sha"] = sha
        if branch:
            body["branch"] = branch
        r = _gh("PUT", "/repos/%s/contents/%s" % (repo, urllib.parse.quote(path)), body)
        return "رُفع %s إلى %s (%s)" % (path, repo, (r.get("commit") or {}).get("html_url", ""))
    if act == "read_file":
        import base64
        path = str(a.get("path", "")).lstrip("/")
        r = _gh("GET", "/repos/%s/contents/%s" % (repo, urllib.parse.quote(path)))
        return base64.b64decode(r.get("content", "")).decode("utf-8", "replace")[:3000]
    if act == "create_issue":
        r = _gh("POST", "/repos/%s/issues" % repo, {"title": str(a.get("title", ""))[:200], "body": str(a.get("body", ""))[:5000]})
        return "أُنشئت: " + r.get("html_url", "")
    if act == "comment":
        r = _gh("POST", "/repos/%s/issues/%d/comments" % (repo, int(a.get("number", 0))), {"body": str(a.get("body", ""))[:5000]})
        return "عُلّق: " + r.get("html_url", "")
    if act == "dispatch":
        _gh("POST", "/repos/%s/actions/workflows/%s/dispatches" % (repo, urllib.parse.quote(str(a.get("workflow", "")))), {"ref": str(a.get("ref", "main"))})
        return "أُرسل تشغيل workflow"
    raise ToolError("action غير معروف. المتاح: create_repo, list_repos, put_file, read_file, create_issue, comment, dispatch")


# ---------- 4) قناة تلقرام ----------
def t_telegram_channel(ctx, a):
    text = str(a.get("text", "")).strip()
    if not text:
        raise ToolError("text فاضي")
    tok, ch = _env("TG_TOKEN"), _env("TG_CHANNEL")
    if not tok or not ch:
        raise ToolError("TG_CHANNEL غير مضبوط (اسم القناة مثل @mychannel والبوت مشرف فيها)")
    api = _env("TG_API", "https://api.telegram.org")
    st, txt = _http("POST", "%s/bot%s/sendMessage" % (api, tok), {"Content-Type": "application/json"},
                    json.dumps({"chat_id": ch, "text": text[:4000]}).encode())
    js = json.loads(txt) if txt.startswith("{") else {}
    if not js.get("ok"):
        raise ToolError("تلقرام رفض: %s" % str(js.get("description", txt))[:150])
    return "نُشر في القناة %s (رسالة %s)" % (ch, js["result"]["message_id"])


# ---------- 5) إيميل ----------
def t_send_email(ctx, a):
    to = str(a.get("to", "")).strip()
    if not re.fullmatch(r"[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+", to):
        raise ToolError("عنوان to غير صالح (عنوان واحد)")
    user, pw = _env("SMTP_USER"), _env("SMTP_PASS")
    if not user or not pw:
        raise ToolError("بيانات الإيميل غير مضبوطة (SMTP_USER و SMTP_PASS)")
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = user, to, str(a.get("subject", "(بدون عنوان)"))[:200]
    m.set_content(str(a.get("body", ""))[:20000])
    for rel in (a.get("attach") or [])[:3]:
        p = tools.safe_path(ctx, str(rel))
        ct = mimetypes.guess_type(p)[0] or "application/octet-stream"
        m.add_attachment(open(p, "rb").read(), maintype=ct.split("/")[0], subtype=ct.split("/")[1], filename=os.path.basename(p))
    host, port = _env("SMTP_HOST", "smtp.gmail.com"), int(_env("SMTP_PORT", "465"))
    try:
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=30) as s:
            s.login(user, pw)
            s.send_message(m)
    except Exception as e:
        raise ToolError("فشل الإرسال: %s" % str(e)[:150])
    return "أُرسل إيميل إلى " + to


# ---------- 6) جدولة ومراقبة يطلبها الوكيل ----------
def t_schedule_task(ctx, a):
    try:
        i = ext.add_schedule(ctx["org"], str(a.get("every", "")), str(a.get("goal", "")))
    except Exception as e:
        raise ToolError(str(e))
    return "جُدولت المهمة #%s كل %s" % (i, a.get("every"))


def t_watch_url(ctx, a):
    try:
        i = ext.add_watch(ctx["org"], str(a.get("url", "")), str(a.get("mode", "change")), str(a.get("every", "30m")))
    except Exception as e:
        raise ToolError(str(e))
    return "بدأت مراقبة #%s" % i


# ---------- 7) متصفح حقيقي ----------
def _ensure_playwright():
    try:
        import playwright.sync_api  # noqa
        return
    except ImportError:
        pass
    if os.environ.get("ORG_SHELL") != "1":
        raise ToolError("المتصفح غير مثبّت هنا (متاح على التشغيل السحابي)")
    for cmd in (["pip", "install", "-q", "--break-system-packages", "playwright"], ["python", "-m", "playwright", "install", "--with-deps", "chromium"]):
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode:
            raise ToolError("تثبيت المتصفح فشل: " + (r.stderr or r.stdout)[-200:])


def t_browse(ctx, a):
    url = str(a.get("url", ""))
    tools._check_url(url)
    _ensure_playwright()
    from playwright.sync_api import sync_playwright
    shot = str(a.get("screenshot", "") or "")
    with sync_playwright() as pw:
        b = pw.chromium.launch(args=["--no-sandbox"])
        pg = b.new_page(viewport={"width": 1280, "height": 900})

        def guard(route):
            try:
                u = urllib.parse.urlparse(route.request.url)
                if u.scheme in ("http", "https"):
                    tools._check_host(u.hostname)
                route.continue_()
            except Exception:
                route.abort()
        pg.route("**/*", guard)
        try:
            pg.goto(url, timeout=30000, wait_until="load")
            if a.get("wait_for"):
                pg.wait_for_selector(str(a["wait_for"]), timeout=10000)
            if a.get("click"):
                pg.click(str(a["click"]), timeout=8000)
                pg.wait_for_timeout(1000)
            title, txt = pg.title(), pg.inner_text("body")
            if shot:
                pg.screenshot(path=tools.safe_path(ctx, shot), full_page=False)
        except Exception as e:
            raise ToolError("المتصفح: %s" % str(e)[:200])
        finally:
            b.close()
    return ("العنوان: %s\n%s" % (title, txt))[:tools.OBS_MAX] + ("\n[حُفظت لقطة: %s]" % shot if shot else "")


TOOLS = {
    "http_request": ("ask", 'طلب HTTP لأي API (نشر/إرسال/استعلام). أسرارك تُكتب {{API_1}} ولا تعرف قيمتها. args: {"method": "POST", "url": "https://...", "headers": {"Authorization": "Bearer {{API_1}}"}, "json": {...}}', t_http_request),
    "run_shell": ("ask", 'تشغيل أمر شل (git, curl, ffmpeg, pip, python...) داخل مساحة عملك على السحابة، مع إنترنت. بدون أسرار. args: {"command": "...", "timeout": 120}', t_run_shell),
    "github": ("ask", 'عمليات GitHub بحسابك. args: {"action": "create_repo|list_repos|put_file|read_file|create_issue|comment|dispatch", "repo": "اسم أو صاحب/اسم", "name":"", "from_file":"ملف من مساحة عملك", "path":"مساره بالمستودع", "message":"", "title":"", "body":"", "number":1, "workflow":"x.yml", "ref":"main"}', t_github),
    "telegram_channel": ("ask", 'نشر رسالة في قناة تلقرام الخاصة بالمالك. args: {"text": "..."}', t_telegram_channel),
    "send_email": ("ask", 'إرسال إيميل من حساب المالك. args: {"to": "a@b.com", "subject": "...", "body": "...", "attach": ["ملف من مساحة عملك"]}', t_send_email),
    "schedule_task": ("ask", 'جدولة هدف يتكرر (كل ساعة فأكثر). args: {"every": "6h", "goal": "الهدف الكامل"}', t_schedule_task),
    "watch_url": ("ask", 'مراقبة صفحة وتنبيه المالك. args: {"url": "...", "mode": "change|up|word:كلمة", "every": "30m"}', t_watch_url),
    "browse": ("safe", 'فتح صفحة بمتصفح حقيقي (جافاسكربت) وقراءة نصها، مع نقر اختياري ولقطة شاشة. args: {"url": "...", "click": "css selector اختياري", "wait_for": "selector اختياري", "screenshot": "shot.png اختياري"}', t_browse),
}


tools.REG.update(TOOLS)
