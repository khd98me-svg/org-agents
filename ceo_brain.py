#!/usr/bin/env python3
"""ceo_brain.py - عقل الرئيس التنفيذي: يحوّل الهدف إلى مهام موزّعة على الإدارات، ويطلب موافقتك لأي تعيين.
يستخدم llm.LLMClient الموجود عندك، مع حدّ يومي لعدد الاستدعاءات (LLM_DAILY_LIMIT، الافتراضي 150)."""
import os, re, json, urllib.request, urllib.error
import orgx

HOME_DIR = os.path.expanduser("~/rl-agent")


class BudgetExceeded(Exception):
    pass


class FakeLLM:
    """للاختبار فقط (ORG_FAKE_LLM=1)"""
    def generate(self, prompt, system_prompt="", temperature=0.3, max_tokens=1000):
        return ("```json\n" + json.dumps({
            "summary": "خطة تجريبية", "tasks": [
                {"title": "تحليل السوق", "description": "جمع بيانات عن المنافسين", "department": "البحث والتطوير", "priority": "high"},
                {"title": "بناء النموذج الأولي", "description": "نموذج بسيط", "department": "التقنية والأنظمة"},
                {"title": "حملة تسويق", "description": "خطة إعلان", "department": "التسويق"}],
            "new_departments": [{"name": "التسويق", "description": "الإعلان والوصول للعملاء"}]},
            ensure_ascii=False) + "\n```")


class ScriptLLM:
    """للاختبار فقط (ORG_FAKE_LLM=script و ORG_SCRIPT=ملف json فيه قائمة ردود تُعاد بالترتيب)"""
    def generate(self, prompt, system_prompt="", temperature=0.3, max_tokens=1000):
        p = os.environ["ORG_SCRIPT"]
        i = int(open(p + ".idx").read()) if os.path.exists(p + ".idx") else 0
        items = json.load(open(p, encoding="utf-8"))
        open(p + ".idx", "w").write(str(i + 1))
        with open(p + ".prompts", "a", encoding="utf-8") as f:
            f.write("=== call %d ===\n%s\n" % (i, prompt))
        r = items[min(i, len(items) - 1)]
        return r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)


# ---------- نماذج متعددة: لكل وكيل نموذجه إذا حددته في models.json ----------
def _models_cfg():
    p = os.environ.get("ORG_MODELS", os.path.join(HOME_DIR, "models.json"))
    try:
        return json.load(open(p, encoding="utf-8")).get("profiles", {})
    except Exception:
        return {}


def _env_key(name):
    if not name:
        return None
    if os.environ.get(name):
        return os.environ[name].strip()
    for f in (os.path.join(HOME_DIR, ".env.models"), os.path.join(HOME_DIR, ".env")):
        try:
            for l in open(f):
                if l.startswith(name + "="):
                    return l.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            pass
    return None


class OpenAICompat:
    """أي مزوّد متوافق مع OpenAI Chat Completions (Groq, OpenRouter, Gemini-compat, ...).
    auto=True: إذا النموذج غير موجود/غير متاح لمفتاحك (404) نكتشف النماذج المتاحة ونجرّب الأحدث تلقائياً."""
    _chosen = {}

    def __init__(self, base_url, model, key, extra=None, auto=False):
        self.base, self.model, self.key, self.extra, self.auto = base_url.rstrip("/"), model, key, extra or {}, auto

    def _call(self, model, msgs, temperature, max_tokens):
        import time as _t
        for wait in (4, 12, None):
            try:
                return self._call_once(model, msgs, temperature, max_tokens)
            except RuntimeError as e:
                transient = getattr(e, "code", 0) in (500, 502, 503, 504) or (getattr(e, "code", 0) == 429 and not re.search(r"limit:\s*0", getattr(e, "detail", "")))
                if not transient or wait is None:
                    raise
            except (TimeoutError, urllib.error.URLError, OSError) as e:
                if wait is None:
                    raise RuntimeError("انقطاع/بطء الاتصال بالمزوّد (النموذج %s): %s" % (model, str(e)[:80]))
            _t.sleep(wait)

    def _call_once(self, model, msgs, temperature, max_tokens):
        body = json.dumps(dict({"model": model, "messages": msgs, "temperature": temperature, "max_tokens": max_tokens}, **self.extra)).encode()
        req = urllib.request.Request(self.base + "/chat/completions", body, {"Content-Type": "application/json", "Authorization": "Bearer " + self.key})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode())["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                detail = ""
            err = RuntimeError("HTTP %d من المزوّد (النموذج %s): %s" % (e.code, model, detail))
            err.code, err.detail = e.code, detail
            raise err

    @staticmethod
    def _retryable(e):
        c, d = getattr(e, "code", 0), getattr(e, "detail", "")
        return c in (404, 403) or (c == 429 and re.search(r"limit:\s*0", d)) or (c == 400 and re.search(r"no longer|not (found|supported|available)", d, re.I))

    def _candidates(self):
        req = urllib.request.Request(self.base + "/models", headers={"Authorization": "Bearer " + self.key})
        with urllib.request.urlopen(req, timeout=30) as r:
            ids = [m.get("id", "").replace("models/", "") for m in json.loads(r.read().decode()).get("data", [])]
        found = []
        for i in ids:
            m = re.fullmatch(r"gemini-(\d+(?:\.\d+)?)-flash(-lite)?", i)
            if m:
                found.append((0 if m.group(2) else 1, -float(m.group(1)), i))
        return [i for _, _, i in sorted(found)][:6]

    def generate(self, prompt, system_prompt="", temperature=0.3, max_tokens=1000):
        msgs = ([{"role": "system", "content": system_prompt}] if system_prompt else []) + [{"role": "user", "content": prompt}]
        model = OpenAICompat._chosen.get(self.base) or self.model
        try:
            return self._call(model, msgs, temperature, max_tokens)
        except RuntimeError as e:
            if not (self.auto and self._retryable(e)):
                raise
            first = e
        tried = [model]
        try:
            cands = self._candidates()
        except Exception:
            raise first
        for m in cands:
            if m in tried:
                continue
            tried.append(m)
            try:
                out = self._call(m, msgs, temperature, max_tokens)
                OpenAICompat._chosen[self.base] = m
                print("نموذج تلقائي:", m, flush=True)
                return out
            except RuntimeError as e:
                if not self._retryable(e):
                    raise
        raise RuntimeError("ما لقيت نموذجاً يعمل بمفتاحك. جُرّب: %s. آخر خطأ: %s" % (", ".join(tried), first))


def profile_names():
    return sorted(_models_cfg())


def profile_llm(name):
    c = _models_cfg().get(name)
    if not c:
        return None
    key = c.get("api_key") or _env_key(c.get("api_key_env", ""))
    if not key:
        return None
    return OpenAICompat(c["base_url"], c["model"], key, c.get("extra"))


def llm_for_agent(org, aid):
    n = org.kget("model_%d" % aid)
    return profile_llm(n) if n and n != "default" else None


def get_llm():
    if os.environ.get("ORG_FAKE_LLM") == "script":
        return ScriptLLM()
    if os.environ.get("ORG_FAKE_LLM"):
        return FakeLLM()
    p = profile_llm("default")
    if p:
        return p
    try:
        from llm import LLMClient  # الموجود على جوالك
        return LLMClient()
    except ImportError:
        key = _env_key("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("ما فيه نموذج افتراضي: لا llm.py ولا GEMINI_API_KEY")
        return OpenAICompat(os.environ.get("GEMINI_BASE") or "https://generativelanguage.googleapis.com/v1beta/openai",
                            os.environ.get("GEMINI_MODEL") or "gemini-3.5-flash-lite", key, {"reasoning_effort": "low"}, auto=True)


def parse_json(text):
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.I).strip()
    a, b = t.find("{"), t.rfind("}")
    if a < 0 or b <= a:
        raise ValueError("no json")
    return json.loads(t[a:b + 1])


def ask(org, system, prompt, temperature=0.3, max_tokens=1500, llm=None, agent_id=None):
    limit = int(os.environ.get("LLM_DAILY_LIMIT") or "150")
    if org.llm_calls_today() >= limit:
        raise BudgetExceeded("وصلنا للحد اليومي (%d استدعاء). يتجدد بكرة، أو ارفع LLM_DAILY_LIMIT." % limit)
    if llm is None and agent_id:
        llm = llm_for_agent(org, agent_id)
    org.bump_llm()
    if llm is not None:
        try:
            return llm.generate(prompt=prompt, system_prompt=system, temperature=temperature, max_tokens=max_tokens)
        except Exception as e:
            org.log("system", "model_fallback", "%s: %s" % (type(e).__name__, str(e)[:150]))
    return get_llm().generate(prompt=prompt, system_prompt=system, temperature=temperature, max_tokens=max_tokens)


def ask_json(org, system, prompt, llm=None, agent_id=None, **kw):
    raw = ask(org, system, prompt, llm=llm, agent_id=agent_id, **kw)
    try:
        return parse_json(raw)
    except Exception:
        raw = ask(org, system, prompt + "\n\nأعد JSON صالحاً فقط، بدون أي نص آخر.", llm=llm, agent_id=agent_id, **kw)
        return parse_json(raw)


SYSTEM = """أنت الرئيس التنفيذي لمؤسسة وكلاء ذكاء اصطناعي. حوّل هدف المالك إلى خطة عملية.
أعد JSON صالحاً فقط بهذا الشكل:
{"summary":"ملخص الخطة بجملتين",
 "tasks":[{"title":"عنوان قصير","description":"ما المطلوب بوضوح وكيف نعرف إنه تم","department":"اسم إدارة من القائمة أو من new_departments","priority":"normal|high"}],
 "new_departments":[{"name":"اسم إدارة جديدة","description":"وظيفتها"}]}
القواعد: من 1 إلى 5 مهام فقط. لا تخترع إدارة جديدة إلا لو لا توجد إدارة مناسبة (حد أقصى 2). لا تذكر وكلاء أو أسماء أشخاص. لا تدّعِ أن شيئاً تم تنفيذه.
ابنِ الخطة على هدف المالك الحالي فقط. «ذاكرة المؤسسة» خلفية للاستئناس ولا تنقل منها مهاماً من أهداف سابقة أبداً.
إذا كان الهدف سؤالاً عاماً أو مفتوحاً (مثل: ما أفضل ما تقدر تنفذه؟) فاجعل المهام تقييماً وتنفيذاً واقعياً مبنياً على «الأدوات الفعلية المتاحة للوكلاء» المذكورة، لا أفكاراً عامة."""


def plan_goal(org, goal, llm=None):
    org.ensure_departments()
    ctx = []
    for did, name, desc, mid, mname in org.departments():
        ctx.append("- %s: %s | %s" % (name, desc, ("مدير: " + mname) if mid else "بدون مدير"))
    mem = [(s, t) for s, t in org.recall(goal, k=8) if not t.startswith("هدف:")][:4]
    try:
        import tools as _tl
        tl = "؛ ".join("%s (%s)" % (n, d.split(" args:")[0][:70]) for n, (r, d, _) in _tl.REG.items() if n not in _tl.MANAGER_ONLY and r != "special")
    except Exception:
        tl = ""
    les = org.lessons_for(org.ceo_id(), k=3)
    prompt = "الإدارات الحالية:\n%s\n\n%s%s%sهدف المالك:\n%s" % (
        "\n".join(ctx),
        ("الأدوات الفعلية المتاحة للوكلاء: " + tl + "\n\n") if tl else "",
        ("ذاكرة المؤسسة (خلفية فقط، لا تنقل منها مهاماً):\n" + "\n".join("- " + t for _, t in mem) + "\n\n") if mem else "",
        ("دروس سابقة:\n" + "\n".join("- " + t for t in les) + "\n\n") if les else "", goal)
    data = ask_json(org, SYSTEM, prompt, llm=llm, temperature=0.3, max_tokens=1400)
    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("النموذج ما أرجع مهام صالحة")
    approvals, newd = [], {}
    for nd in (data.get("new_departments") or [])[:2]:
        if isinstance(nd, dict) and str(nd.get("name", "")).strip() and not org.find_dept(nd["name"]):
            nm = str(nd["name"]).strip()[:60]
            newd[orgx.norm(nm)] = nm
            approvals.append(org.propose("create_department", {"name": nm, "description": str(nd.get("description", ""))[:200]}))
    out = []
    ceo = org.ceo_id()
    for t in tasks[:5]:
        if not isinstance(t, dict) or not str(t.get("title", "")).strip():
            continue
        dname = str(t.get("department", "")).strip()
        did = org.find_dept(dname)
        mgr = org.dept_manager(did) if did else None
        pr = "high" if str(t.get("priority", "")).lower() == "high" else "normal"
        tid = org.create_task(str(t["title"]).strip(), str(t.get("description", "")).strip(), did, mgr, pr, by=ceo, dept_hint="" if did else dname)
        row = org.q("SELECT name FROM departments WHERE id=?", (did,)) if did else []
        out.append((tid, str(t["title"]).strip(), row[0][0] if row else (dname or "—"), org.agent(mgr)[1] if mgr else None, bool(did)))
        if did and not mgr:
            dn = row[0][0]
            approvals.append(org.propose("create_manager", {"department": dn, "name": "مدير " + dn, "specialty": next((d[2] for d in org.departments() if d[0] == did), "")}))
        elif not did and dname and orgx.norm(dname) not in newd:
            approvals.append(org.propose("create_department", {"name": dname[:60], "description": ""}))
    ids = [o[0] for o in out]
    if ids:
        org.kset("last_plan", json.dumps(ids))
        for i in ids:
            org.kset("grp_%d" % i, ids[0])
    org.remember("هدف: " + goal[:300] + " -> " + str(data.get("summary", ""))[:300], topic="goal", weight=1.5)
    org.log("CEO", "goal_planned", goal[:100])
    return {"summary": str(data.get("summary", "")), "tasks": out, "approvals": sorted(set(approvals))}
