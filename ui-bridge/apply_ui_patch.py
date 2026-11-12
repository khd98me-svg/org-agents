#!/usr/bin/env python3
"""Safely install the read-only organization adapter and Quest Log approvals feed."""
from datetime import datetime, timezone
from pathlib import Path
import secrets
import shutil

REPO_ROOT = Path(__file__).resolve().parents[1]
UI_ROOT = Path.home() / "openclawfice"
PAGE = UI_ROOT / "app" / "page.tsx"
ROUTE = UI_ROOT / "app" / "api" / "office" / "route.ts"
ACTIONS_ROUTE = UI_ROOT / "app" / "api" / "office" / "actions" / "route.ts"
INSTRUMENTATION = UI_ROOT / "instrumentation.ts"
LEGACY_CONFIG = UI_ROOT / "app" / "api" / "office" / "config" / "route.ts"
LEGACY_MEETING = UI_ROOT / "app" / "api" / "office" / "meeting" / "route.ts"
LEGACY_AUTOWORK = UI_ROOT / "app" / "api" / "office" / "autowork" / "route.ts"
LEGACY_CHAT = UI_ROOT / "app" / "api" / "office" / "chat" / "route.ts"
ROUTE_SOURCE = REPO_ROOT / "ui-bridge" / "office-route.ts"
ACTIONS_SOURCE = REPO_ROOT / "ui-bridge" / "actions-route.ts"
INSTRUMENTATION_SOURCE = REPO_ROOT / "ui-bridge" / "instrumentation-safe.ts"
LEGACY_CONFIG_SOURCE = REPO_ROOT / "ui-bridge" / "legacy-config-route.ts"
LEGACY_MEETING_SOURCE = REPO_ROOT / "ui-bridge" / "legacy-meeting-route.ts"
LEGACY_AUTOWORK_SOURCE = REPO_ROOT / "ui-bridge" / "legacy-autowork-route.ts"
LEGACY_CHAT_SOURCE = REPO_ROOT / "ui-bridge" / "legacy-chat-route.ts"
ENV_FILE = UI_ROOT / ".env.local"

OLD = """              needs: defaults.needs,
              skills: a.skills || defaults.skills,
              xp: a.xp || defaults.xp,
              level: a.level || defaults.level,"""
NEW = """              // Preserve source values, including legitimate zero/empty values.
              // The organization engine does not currently calculate gamified metrics.
              needs: a.needs || defaults.needs,
              skills: Array.isArray(a.skills) ? a.skills : defaults.skills,
              xp: typeof a.xp === 'number' ? a.xp : defaults.xp,
              level: typeof a.level === 'number' ? a.level : defaults.level,"""

READ_ONLY_START = """              {/* Options buttons */}"""
READ_ONLY_WRAPPED_START = """              {action.data?.readOnly ? (
                <div style={{
                  background: 'rgba(245,158,11,0.08)',
                  border: '1px solid rgba(245,158,11,0.35)',
                  borderRadius: 6,
                  padding: 10,
                  color: '#fbbf24',
                  fontSize: 11,
                  lineHeight: 1.6,
                }}>
                  🛡️ عرض فقط — هذا طلب موافقة حقيقي من محرك المؤسسة.
                  <br />
                  أزرار الاعتماد غير مفعّلة حتى يكتمل ربط القرار الآمن بالمحرك.
                </div>
              ) : (
                <>
              {/* Options buttons */}"""

READ_ONLY_END = """              )}
            </div>
          </div>
        );
      })()}"""
READ_ONLY_WRAPPED_END = """              )}
                </>
              )}
            </div>
          </div>
        );
      })()}"""


ORG_PAGE = UI_ROOT / "app" / "organization" / "page.tsx"
ORG_PAGE_SOURCE = r"""'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { useAuthenticatedFetch } from '../../hooks/useAuthenticatedFetch';

type Data = { agents?: any[]; departments?: any[]; tasks?: any[]; runs?: any[]; reviews?: any[]; organization?: { summary?: Record<string, number> }; timestamp?: string };
const labels: Record<string, string> = { pending: 'بانتظار مسؤول', assigned: 'مسندة', submitted: 'بانتظار المراجعة', blocked: 'متوقفة', done: 'منجزة', rejected: 'مرفوضة', running: 'جارية في السجل', paused: 'متوقفة مؤقتاً', waiting_owner: 'بانتظار المالك', waiting_approval: 'بانتظار الموافقة', waiting_team: 'بانتظار الفريق', failed: 'فشلت' };
const label = (s: string) => labels[s] || s || 'غير محدد';
const date = (s: string) => { if (!s) return '—'; const d = new Date(s); return Number.isNaN(d.getTime()) ? s : d.toLocaleString('ar-SA'); };
const panel: React.CSSProperties = { background: '#151a24', border: '1px solid #30394b', borderRadius: 12, padding: 14, minWidth: 0 };
const muted: React.CSSProperties = { color: '#aab4c5', fontSize: 12 };

export default function OrganizationDashboard() {
  const authFetch = useAuthenticatedFetch();
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState('departments');
  const load = useCallback(async () => {
    try {
      const res = await authFetch('/api/office', { cache: 'no-store' });
      const body = await res.json();
      if (!res.ok) throw new Error(body.error || ('HTTP ' + res.status));
      setData(body); setError('');
    } catch (e: any) { setError(e?.message || 'تعذر تحميل بيانات المؤسسة'); }
    finally { setLoading(false); }
  }, [authFetch]);
  useEffect(() => { load(); const id = setInterval(load, 15000); return () => clearInterval(id); }, [load]);
  const summary = data?.organization?.summary || {};
  const tabs = [['departments', 'الإدارات'], ['tasks', 'المهام'], ['runs', 'التشغيلات'], ['reviews', 'المراجعات']];
  return <main dir="rtl" style={{ minHeight: '100vh', background: '#0b0f17', color: '#edf2fa', padding: '18px 14px 40px', fontFamily: 'system-ui,sans-serif' }}>
    <div style={{ maxWidth: 1100, margin: '0 auto' }}>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 18 }}>
        <div><div style={{ color: '#8fa8ce', fontSize: 11, letterSpacing: 1 }}>ORGANIZATION CONTROL ROOM</div><h1 style={{ fontSize: 24, margin: '6px 0' }}>لوحة المؤسسة</h1><div style={muted}>organization.db · وضع القراءة فقط</div></div>
        <div style={{ display: 'flex', gap: 8 }}><a href="/" style={{ color: '#b8c9e6', textDecoration: 'none', border: '1px solid #39465c', padding: '8px 12px', borderRadius: 8 }}>المكتب الافتراضي</a><button onClick={load} style={{ background: '#263b5a', color: 'white', border: 0, padding: '9px 13px', borderRadius: 8 }}>تحديث</button></div>
      </header>
      {error && <div role="alert" style={{ ...panel, borderColor: '#a34b4b', color: '#ffb9b9', marginBottom: 14 }}>تعذر تحميل البيانات: {error}</div>}
      {loading && !data && <div style={panel}>جارٍ تحميل بيانات المؤسسة…</div>}
      {data && <>
        <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(130px,1fr))', gap: 9, marginBottom: 16 }}>
          {([['الإدارات', summary.departments], ['الوكلاء', summary.agents], ['المهام', summary.tasks], ['مفتوحة / مسندة', summary.pendingTasks], ['بانتظار المراجعة', summary.submittedTasks], ['منجزة', summary.completedTasks], ['تشغيلات حديثة النشاط', summary.freshRuns]] as any[]).map(([name, value]) => <div key={name} style={panel}><div style={muted}>{name}</div><div style={{ fontSize: 25, fontWeight: 700, marginTop: 5 }}>{value ?? 0}</div></div>)}
        </section>
        <nav style={{ display: 'flex', gap: 7, flexWrap: 'wrap', marginBottom: 12 }}>{tabs.map(([key, title]) => <button key={key} onClick={() => setTab(key)} aria-pressed={tab === key} style={{ border: '1px solid ' + (tab === key ? '#7799ce' : '#39465c'), background: tab === key ? '#263b5a' : '#151a24', color: '#edf2fa', borderRadius: 8, padding: '9px 13px' }}>{title}</button>)}</nav>
        {tab === 'departments' && <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(245px,1fr))', gap: 10 }}>{(data.departments || []).map(dept => <article key={dept.id} style={panel}><h2 style={{ margin: '0 0 7px', fontSize: 17 }}>{dept.name}</h2><p style={{ ...muted, lineHeight: 1.7 }}>{dept.description || 'لا يوجد وصف'}</p><div style={{ fontSize: 13, margin: '10px 0' }}>المدير: {dept.manager?.name || 'غير محدد'}</div><div style={muted}>الأعضاء: {dept.members?.length || 0} · المهام: {dept.taskCount || 0}</div><div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>{(dept.members || []).map((m: any) => <span key={m.id} style={{ background: '#222d3d', padding: '5px 8px', borderRadius: 6, fontSize: 12 }}>{m.name} · {m.role}</span>)}</div></article>)}{!data.departments?.length && <div style={panel}>لا توجد إدارات في البيانات المسترجعة.</div>}</section>}
        {tab === 'tasks' && <section style={{ display: 'grid', gap: 9 }}>{(data.tasks || []).map(task => <article key={task.id} style={panel}><div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' }}><strong>#{task.id} · {task.title}</strong><span style={{ color: '#b9c9e2', fontSize: 12 }}>{label(task.status)} · الأولوية: {task.priority}</span></div><p style={{ ...muted, lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>{task.description || 'لا يوجد وصف'}</p><div style={muted}>المسؤول: {task.assignedTo?.name || 'غير مسندة'} · الإدارة: {task.department?.name || 'غير محددة'} · المهمة الأم: {task.parentId || '—'}</div>{task.result && <details style={{ marginTop: 8 }}><summary style={{ cursor: 'pointer' }}>عرض النتيجة المسجلة</summary><p style={{ whiteSpace: 'pre-wrap', lineHeight: 1.7 }}>{task.result}</p></details>}<div style={{ ...muted, marginTop: 7 }}>آخر تحديث: {date(task.updatedAt || task.createdAt)}</div></article>)}{!data.tasks?.length && <div style={panel}>لا توجد مهام ضمن السجلات المسترجعة.</div>}</section>}
        {tab === 'runs' && <section style={{ display: 'grid', gap: 9 }}><div style={{ ...muted, marginBottom: 2 }}>«حديث النشاط» يعني أن السجل يحمل حالة جارية وتحديثه خلال آخر خمس دقائق؛ هذه اللوحة لا تشغّل شيئاً.</div>{(data.runs || []).map(run => <article key={run.id} style={panel}><strong>تشغيل #{run.id} · المهمة #{run.taskId || '—'}: {run.taskTitle}</strong><div style={{ marginTop: 7, fontSize: 13 }}>الوكيل: {run.agentName} · الحالة المسجلة: {label(run.status)}</div><div style={{ ...muted, marginTop: 6 }}>الخطوات: {run.steps} · آخر تحديث: {date(run.updatedAt || run.createdAt)}</div><div style={{ marginTop: 7, color: run.isFresh ? '#9be2b0' : '#d8b77c', fontSize: 12 }}>{run.isFresh ? 'نشاط حديث بحسب وقت السجل' : 'لا يوجد دليل زمني كافٍ على نشاط حالي'}</div></article>)}{!data.runs?.length && <div style={panel}>لا توجد تشغيلات ضمن السجلات المسترجعة.</div>}</section>}
        {tab === 'reviews' && <section style={{ display: 'grid', gap: 9 }}>{(data.reviews || []).map(review => <article key={review.id} style={panel}><strong>مراجعة #{review.id} · المهمة #{review.taskId || '—'}</strong><div style={{ marginTop: 7, fontSize: 13 }}>المراجع: {review.reviewer} · القرار: {review.verdict} · التقييم: {review.score ?? '—'}</div><p style={{ ...muted, whiteSpace: 'pre-wrap', lineHeight: 1.7 }}>{review.notes || 'لا توجد ملاحظات'}</p><div style={muted}>{date(review.ts)}</div></article>)}{!data.reviews?.length && <div style={panel}>لا توجد مراجعات ضمن السجلات المسترجعة.</div>}</section>}
        <footer style={{ ...muted, marginTop: 18, textAlign: 'center' }}>آخر مزامنة: {date(data.timestamp || '')} · جميع البيانات للعرض فقط</footer>
      </>}
    </div>
  </main>;
}
"""

def configure_env():
    text = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    lines = text.splitlines()
    token = ""
    for line in lines:
        if line.startswith("OFFICE_API_TOKEN="):
            token = line.split("=", 1)[1].strip().strip('"').strip("'")
            if token:
                break
    values = {
        "OFFICE_API_URL": "http://127.0.0.1:8765/api/office",
        "OFFICE_API_TOKEN": token or secrets.token_urlsafe(32),
    }
    seen = set()
    output = []
    for line in lines:
        key = line.split("=", 1)[0] if "=" in line else ""
        if key in values:
            if key not in seen:
                output.append(f"{key}={values[key]}")
                seen.add(key)
        else:
            output.append(line)
    for key, value in values.items():
        if key not in seen:
            output.append(f"{key}={value}")
    temp = ENV_FILE.with_name(".env.local.office-ui-bridge.tmp")
    temp.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    temp.replace(ENV_FILE)


def main():
    if not all(path.is_file() for path in (PAGE, ROUTE_SOURCE, ACTIONS_SOURCE, INSTRUMENTATION_SOURCE, INSTRUMENTATION, LEGACY_CONFIG_SOURCE, LEGACY_MEETING_SOURCE, LEGACY_AUTOWORK_SOURCE, LEGACY_CHAT_SOURCE)):
        raise SystemExit("Required file missing. Expected ~/openclawfice and both bridge route sources.")
    page_text = PAGE.read_text(encoding="utf-8")

    if OLD in page_text:
        patched_page = page_text.replace(OLD, NEW, 1)
    elif NEW in page_text:
        patched_page = page_text
    else:
        raise SystemExit("OpenClawfice agent normalization block differs; stopped without changes.")

    # Replace OpenClawfice's stale empty-state source label. The Quest Log
    # endpoint is now backed by organization.db:approvals, not actions.json.
    legacy_source = "(Pulled from ~/.openclaw/.status/actions.json)"
    current_source = "(Source: organization.db — pending approvals)"
    if legacy_source in patched_page:
        patched_page = patched_page.replace(legacy_source, current_source, 1)

    if READ_ONLY_START in patched_page:
        patched_page = patched_page.replace(READ_ONLY_START, READ_ONLY_WRAPPED_START, 1)
        if READ_ONLY_END not in patched_page:
            raise SystemExit("Quest modal closing block differs; stopped without changes.")
        patched_page = patched_page.replace(READ_ONLY_END, READ_ONLY_WRAPPED_END, 1)
    elif READ_ONLY_WRAPPED_START in patched_page and READ_ONLY_WRAPPED_END in patched_page:
        pass
    else:
        raise SystemExit("Quest Log modal differs from reviewed version; stopped without changes.")

    respond_old = """        const respondAction = async (response: string) => {
          await secureFetch('/api/office/actions', {"""
    respond_new = """        const respondAction = async (response: string) => {
          if (action.data?.readOnly) return;
          await secureFetch('/api/office/actions', {"""
    if respond_old in patched_page:
        patched_page = patched_page.replace(respond_old, respond_new, 1)
    elif respond_new not in patched_page:
        raise SystemExit("Quest response handler differs; stopped without changes.")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = Path.home() / ".cache" / "office-ui-bridge-backups" / stamp
    backup_dir.mkdir(parents=True, exist_ok=False)
    for path, name in (
        (PAGE, "page.tsx"),
        (ROUTE, "office-route.ts"),
        (ACTIONS_ROUTE, "actions-route.ts"),
        (ORG_PAGE, "organization-page.tsx"),
        (INSTRUMENTATION, "instrumentation.ts"),
        (LEGACY_CONFIG, "legacy-config-route.ts"),
        (LEGACY_MEETING, "legacy-meeting-route.ts"),
        (LEGACY_AUTOWORK, "legacy-autowork-route.ts"),
        (LEGACY_CHAT, "legacy-chat-route.ts"),
        (ENV_FILE, ".env.local"),
    ):
        if path.exists():
            shutil.copy2(path, backup_dir / name)

    temp_page = PAGE.with_name("page.tsx.office-ui-bridge.tmp")
    temp_page.write_text(patched_page, encoding="utf-8")
    temp_page.replace(PAGE)

    ROUTE.parent.mkdir(parents=True, exist_ok=True)
    for target, source, label in (
        (ROUTE, ROUTE_SOURCE, "office-route.ts"),
        (ACTIONS_ROUTE, ACTIONS_SOURCE, "actions-route.ts"),
        (INSTRUMENTATION, INSTRUMENTATION_SOURCE, "instrumentation.ts"),
        (LEGACY_CONFIG, LEGACY_CONFIG_SOURCE, "legacy-config-route.ts"),
        (LEGACY_MEETING, LEGACY_MEETING_SOURCE, "legacy-meeting-route.ts"),
        (LEGACY_AUTOWORK, LEGACY_AUTOWORK_SOURCE, "legacy-autowork-route.ts"),
        (LEGACY_CHAT, LEGACY_CHAT_SOURCE, "legacy-chat-route.ts"),
    ):
        temp = target.with_name(target.name + ".office-ui-bridge.tmp")
        shutil.copy2(source, temp)
        temp.replace(target)

    ORG_PAGE.parent.mkdir(parents=True, exist_ok=True)
    org_temp = ORG_PAGE.with_name("page.tsx.office-ui-bridge.tmp")
    org_temp.write_text(ORG_PAGE_SOURCE, encoding="utf-8")
    org_temp.replace(ORG_PAGE)

    configure_env()
    print("Installed the read-only organization adapter, Quest Log feed and organization dashboard.")
    print(f"Backup: {backup_dir}")
    print("Quest Log displays only approvals whose database status is pending.")
    print("Approval decisions remain disabled; no database or engine files were changed.")
    print("Legacy OpenClaw autowork and watercooler background tickers are disabled.")
    print("Legacy config, meeting, autowork, and chat write endpoints return HTTP 405.")
    print("Organization dashboard: http://localhost:3333/organization")
    print("The local bridge secret remains in .env.local and was not displayed.")


if __name__ == "__main__":
    main()
