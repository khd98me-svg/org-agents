'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useAuthenticatedFetch } from '../../hooks/useAuthenticatedFetch';

type Item = Record<string, any>;
type Data = {
  agents?: Item[]; departments?: Item[]; tasks?: Item[]; runs?: Item[]; reviews?: Item[]; activityLog?: Item[];
  organization?: { summary?: Record<string, number> }; timestamp?: string;
};
const labels: Record<string, string> = {
  pending: 'بانتظار مسؤول', assigned: 'مسندة', submitted: 'بانتظار المراجعة',
  blocked: 'متوقفة', done: 'منجزة', rejected: 'مرفوضة', running: 'جارية في السجل',
  paused: 'متوقفة مؤقتاً', waiting_owner: 'بانتظار المالك',
  waiting_approval: 'بانتظار الموافقة', waiting_team: 'بانتظار الفريق', failed: 'فشلت',
};
const label = (s: string) => labels[s] || s || 'غير محدد';
const date = (s: string) => {
  if (!s) return '—';
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? s : d.toLocaleString('ar-SA');
};
const panel: React.CSSProperties = {
  background: '#151a24', border: '1px solid #30394b', borderRadius: 12,
  padding: 14, minWidth: 0,
};
const muted: React.CSSProperties = { color: '#aab4c5', fontSize: 12 };
const field: React.CSSProperties = {
  width: '100%', boxSizing: 'border-box', background: '#0e1420', color: '#edf2fa',
  border: '1px solid #39465c', borderRadius: 8, padding: '10px 11px', minHeight: 40,
};

export default function OrganizationDashboard() {
  const authFetch = useAuthenticatedFetch();
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState('departments');
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [departmentFilter, setDepartmentFilter] = useState('all');
  const [selectedAgentId, setSelectedAgentId] = useState('');
  const [editor, setEditor] = useState<{ kind: 'agent' | 'department'; id: string; title: string; originalName: string; originalDetail: string } | null>(null);
  const [editName, setEditName] = useState('');
  const [editDetail, setEditDetail] = useState('');
  const [confirmSave, setConfirmSave] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [saveNotice, setSaveNotice] = useState('');
  const [auditQuery, setAuditQuery] = useState('');
  const [auditActionFilter, setAuditActionFilter] = useState('all');
  const [auditActorFilter, setAuditActorFilter] = useState('all');
  const [auditFrom, setAuditFrom] = useState('');
  const [auditTo, setAuditTo] = useState('');
  const [auditSort, setAuditSort] = useState('newest');

  const load = useCallback(async () => {
    try {
      const res = await authFetch('/api/office', { cache: 'no-store' });
      const body = await res.json();
      if (!res.ok) throw new Error(body.error === 'department_name_exists' ? 'اسم الإدارة مستخدم بالفعل.' : body.error === 'unsupported_fields' ? 'تحتوي البيانات على حقل غير مسموح.' : (body.error || ('HTTP ' + res.status)));
      setData(body); setError('');
    } catch (e: any) {
      setError(e?.message || 'تعذر تحميل بيانات المؤسسة');
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  const openEditor = (kind: 'agent' | 'department', item: Item) => {
    const originalName = String(item.name || '');
    const originalDetail = kind === 'agent' ? String(item.role || '') : String(item.description || '');
    setEditor({ kind, id: String(item.id), title: originalName, originalName, originalDetail });
    setEditName(originalName);
    setEditDetail(originalDetail);
    setConfirmSave(false);
    setSaveError('');
    setSaveNotice('');
  };

  const saveProfile = useCallback(async () => {
    if (!editor || !confirmSave) return;
    setSaving(true);
    setSaveError('');
    try {
      const payload: Item = {
        operation: editor.kind === 'agent' ? 'agent_profile' : 'department_profile',
        id: Number(editor.id),
        confirm: true,
      };
      if (editName.trim() !== editor.originalName) payload.name = editName.trim();
      if (editDetail.trim() !== editor.originalDetail) {
        payload[editor.kind === 'agent' ? 'specialty' : 'description'] = editDetail.trim();
      }
      if (!('name' in payload) && !(editor.kind === 'agent' ? 'specialty' in payload : 'description' in payload)) {
        setSaveError('لم تغيّر أي حقل.');
        setSaving(false);
        return;
      }
      const res = await authFetch('/api/office/manage', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        cache: 'no-store',
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.error || ('HTTP ' + res.status));
      setEditor(null);
      setConfirmSave(false);
      setSaveNotice('تم حفظ التعديل وتسجيله في سجل التدقيق.');
      await load();
    } catch (e: any) {
      setSaveError(e?.message || 'تعذر حفظ التعديل');
    } finally {
      setSaving(false);
    }
  }, [authFetch, editor, confirmSave, editName, editDetail, load]);

  useEffect(() => {
    load();
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, [load]);

  const summary = data?.organization?.summary || {};
  const tasks = data?.tasks || [];
  const runs = data?.runs || [];
  const reviews = data?.reviews || [];
  const activityLog = data?.activityLog || [];
  const auditActions = useMemo(() => Array.from(new Set(
    activityLog.map(entry => String(entry.action || '')).filter(Boolean)
  )).sort(), [activityLog]);
  const auditActors = useMemo(() => Array.from(new Set(
    activityLog.map(entry => String(entry.who || '')).filter(Boolean)
  )).sort((a, b) => a.localeCompare(b, 'ar')), [activityLog]);
  const filteredAuditLog = useMemo(() => {
    const q = auditQuery.trim().toLocaleLowerCase();
    const from = auditFrom ? new Date(auditFrom + 'T00:00:00').getTime() : null;
    const to = auditTo ? new Date(auditTo + 'T23:59:59.999').getTime() : null;
    return activityLog.filter(entry => {
      const matchesQuery = !q || [
        entry.id, entry.action, entry.details, entry.text, entry.who, entry.actor,
      ].some(value => String(value || '').toLocaleLowerCase().includes(q));
      const matchesAction = auditActionFilter === 'all' || entry.action === auditActionFilter;
      const matchesActor = auditActorFilter === 'all' || entry.who === auditActorFilter;
      const timestamp = new Date(entry.t || '').getTime();
      const matchesFrom = from === null || (Number.isFinite(timestamp) && timestamp >= from);
      const matchesTo = to === null || (Number.isFinite(timestamp) && timestamp <= to);
      return matchesQuery && matchesAction && matchesActor && matchesFrom && matchesTo;
    }).sort((a, b) => {
      const timeA = new Date(a.t || '').getTime() || 0;
      const timeB = new Date(b.t || '').getTime() || 0;
      return auditSort === 'oldest' ? timeA - timeB : timeB - timeA;
    });
  }, [activityLog, auditQuery, auditActionFilter, auditActorFilter, auditFrom, auditTo, auditSort]);
  const resetAuditFilters = () => {
    setAuditQuery('');
    setAuditActionFilter('all');
    setAuditActorFilter('all');
    setAuditFrom('');
    setAuditTo('');
    setAuditSort('newest');
  };
  const departments = data?.departments || [];
  const agents = data?.agents || [];
  const selectedAgent = agents.find(agent => String(agent.id) === selectedAgentId) || null;
  const tabs = [
    ['departments', 'الإدارات', departments.length],
    ['agents', 'الوكلاء', agents.length],
    ['tasks', 'المهام', summary.tasks ?? tasks.length],
    ['runs', 'التشغيلات', runs.length],
    ['reviews', 'المراجعات', reviews.length],
    ['audit', 'سجل التدقيق', activityLog.length],
  ];

  const filteredTasks = useMemo(() => {
    const q = query.trim().toLocaleLowerCase();
    return tasks.filter(task => {
      const matchesQuery = !q || [
        task.id, task.title, task.description, task.assignedTo?.name,
        task.department?.name, task.result,
      ].some(value => String(value || '').toLocaleLowerCase().includes(q));
      const matchesStatus = statusFilter === 'all' || task.status === statusFilter;
      const matchesDepartment = departmentFilter === 'all' ||
        String(task.department?.id || '') === departmentFilter;
      return matchesQuery && matchesStatus && matchesDepartment;
    });
  }, [tasks, query, statusFilter, departmentFilter]);

  const resetFilters = () => {
    setQuery('');
    setStatusFilter('all');
    setDepartmentFilter('all');
  };

  return <main dir="rtl" style={{ minHeight: '100vh', background: '#0b0f17', color: '#edf2fa', padding: '18px 14px 40px', fontFamily: 'system-ui,sans-serif' }}>
    <div style={{ maxWidth: 1100, margin: '0 auto' }}>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 18 }}>
        <div>
          <div style={{ color: '#8fa8ce', fontSize: 11, letterSpacing: 1 }}>ORGANIZATION CONTROL ROOM</div>
          <h1 style={{ fontSize: 24, margin: '6px 0' }}>لوحة المؤسسة</h1>
          <div style={muted}>organization.db · قراءة مع تعديل محدود · تحديث تلقائي كل 15 ثانية</div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <a href="/" style={{ color: '#b8c9e6', textDecoration: 'none', border: '1px solid #39465c', padding: '8px 12px', borderRadius: 8 }}>المكتب الافتراضي</a>
          <button onClick={load} style={{ background: '#263b5a', color: 'white', border: 0, padding: '9px 13px', borderRadius: 8 }}>تحديث الآن</button>
        </div>
      </header>

      {error && <div role="alert" style={{ ...panel, borderColor: '#a34b4b', color: '#ffb9b9', marginBottom: 14 }}>تعذر تحميل البيانات: {error}</div>}
      {saveNotice && <div role="status" style={{ ...panel, borderColor: '#397a55', color: '#a8e6bb', marginBottom: 14 }}>{saveNotice}</div>}
      {loading && !data && <div style={panel}>جارٍ تحميل بيانات المؤسسة…</div>}

      {data && <>
        <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(130px,1fr))', gap: 9, marginBottom: 16 }}>
          {([
            ['الإدارات', summary.departments], ['الوكلاء', summary.agents],
            ['المهام', summary.tasks], ['مفتوحة / مسندة', summary.pendingTasks],
            ['بانتظار المراجعة', summary.submittedTasks], ['منجزة', summary.completedTasks],
            ['تشغيلات حديثة النشاط', summary.freshRuns],
          ] as any[]).map(([name, value]) =>
            <div key={name} style={panel}><div style={muted}>{name}</div><div style={{ fontSize: 25, fontWeight: 700, marginTop: 5 }}>{value ?? 0}</div></div>
          )}
        </section>

        <nav aria-label="أقسام المؤسسة" style={{ display: 'flex', gap: 7, flexWrap: 'wrap', marginBottom: 12 }}>
          {tabs.map(([key, title, count]) =>
            <button key={key} onClick={() => setTab(String(key))} aria-pressed={tab === key}
              style={{
                border: '1px solid ' + (tab === key ? '#7799ce' : '#39465c'),
                background: tab === key ? '#263b5a' : '#151a24', color: '#edf2fa',
                borderRadius: 8, padding: '9px 13px', cursor: 'pointer',
              }}>{title} ({count})</button>
          )}
        </nav>

        {tab === 'departments' && <>
          <div style={{ ...muted, marginBottom: 10 }}>اختر إدارة لعرض مهامها مباشرة. لا يؤدي الاختيار إلى تعديل بيانات المؤسسة.</div>
          <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(245px,1fr))', gap: 10 }}>
            {departments.map(dept =>
              <article key={dept.id} style={panel}>
                <h2 style={{ margin: '0 0 7px', fontSize: 17 }}>{dept.name}</h2>
                <p style={{ ...muted, lineHeight: 1.7 }}>{dept.description || 'لا يوجد وصف'}</p>
                <div style={{ fontSize: 13, margin: '10px 0' }}>المدير: {dept.manager?.name || 'غير محدد'}</div>
                <div style={muted}>الأعضاء: {dept.members?.length || 0} · المهام: {dept.taskCount || 0}</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>
                  {(dept.members || []).map((m: Item) =>
                    <span key={m.id} style={{ background: '#222d3d', padding: '5px 8px', borderRadius: 6, fontSize: 12 }}>{m.name} · {m.role}</span>
                  )}
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 7, marginTop: 12 }}>
                  <button onClick={() => { setDepartmentFilter(String(dept.id)); setStatusFilter('all'); setQuery(''); setTab('tasks'); }}
                    style={{ background: '#263b5a', color: '#edf2fa', border: 0, borderRadius: 8, padding: 9, cursor: 'pointer' }}>
                    عرض المهام
                  </button>
                  <button onClick={() => openEditor('department', dept)}
                    style={{ background: '#222d3d', color: '#edf2fa', border: '1px solid #52627b', borderRadius: 8, padding: 9, cursor: 'pointer' }}>
                    تعديل الإدارة
                  </button>
                </div>
              </article>
            )}
            {!departments.length && <div style={panel}>لا توجد إدارات في البيانات المسترجعة.</div>}
          </section>
        </>}

        {tab === 'agents' && <>
          <div style={{ ...muted, marginBottom: 10 }}>اختر وكيلاً لعرض ملفه التنظيمي وسجل عمله. هذه البيانات مسترجعة من قاعدة المؤسسة ولا تتضمن أي أوامر تشغيل أو تعديل.</div>
          <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(230px,1fr))', gap: 9 }}>
            {agents.map(agent => <button key={agent.id} onClick={() => setSelectedAgentId(String(agent.id))}
              aria-pressed={selectedAgentId === String(agent.id)}
              style={{ ...panel, textAlign: 'right', color: '#edf2fa', cursor: 'pointer', borderColor: selectedAgentId === String(agent.id) ? '#7799ce' : '#30394b' }}>
              <strong>{agent.emoji || '🤖'} {agent.name}</strong>
              <div style={{ ...muted, marginTop: 6 }}>{agent.role || 'دون تخصص مسجل'} · {agent.status === 'working' ? 'نشاط حديث مسجل' : 'لا يوجد نشاط حديث مثبت'}</div>
              <div style={{ ...muted, marginTop: 5 }}>المهام: {agent.tasks?.length || 0} · التشغيلات: {agent.runs?.length || 0} · الإدارات: {agent.departments?.length || 0}</div>
            </button>)}
          </section>
          {!agents.length && <div style={panel}>لا يوجد وكلاء في البيانات المسترجعة.</div>}
          {selectedAgent && <section style={{ ...panel, marginTop: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
              <div><h2 style={{ margin: 0, fontSize: 20 }}>{selectedAgent.name}</h2><div style={muted}>{selectedAgent.role} · المعرّف #{selectedAgent.id}</div></div>
              <button onClick={() => openEditor('agent', selectedAgent)}
                style={{ background: '#263b5a', color: '#edf2fa', border: 0, borderRadius: 8, padding: '8px 12px', cursor: 'pointer' }}>
                تعديل بيانات الوكيل
              </button>
              <span style={{ ...muted, alignSelf: 'center' }}>الحالة المسجلة: {selectedAgent.sourceStatus || 'غير محددة'}</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(130px,1fr))', gap: 8, marginTop: 12 }}>
              {[['المهام المسندة', selectedAgent.tasks?.length], ['التشغيلات', selectedAgent.runs?.length], ['المراجعات', selectedAgent.reviews?.length], ['الإدارات', selectedAgent.departments?.length]].map(([name, count]) =>
                <div key={String(name)} style={{ background: '#101722', borderRadius: 8, padding: 10 }}><div style={muted}>{name}</div><strong>{count ?? 0}</strong></div>
              )}
            </div>
            <div style={{ marginTop: 14 }}><strong>الانتماء الإداري</strong>
              <p style={muted}>{selectedAgent.departments?.length ? selectedAgent.departments.map((d: Item) => d.name + ' · ' + d.role).join('، ') : 'لا يوجد ارتباط إداري نشط مسجل'}</p>
            </div>
            <div style={{ marginTop: 14 }}><strong>التسلسل الإداري</strong>
              <p style={muted}>يرفع تقاريره إلى: {selectedAgent.reportsTo?.length ? selectedAgent.reportsTo.map((x: Item) => x.managerName).join('، ') : 'غير محدد'}</p>
              <p style={muted}>يتبعه: {selectedAgent.directReports?.length ? selectedAgent.directReports.map((x: Item) => x.agentName).join('، ') : 'لا توجد تقارير مباشرة مسجلة'}</p>
            </div>
            <div style={{ marginTop: 14 }}><strong>المهام المسندة</strong>
              {selectedAgent.tasks?.length ? selectedAgent.tasks.map((task: Item) => <div key={task.id} style={{ background: '#101722', borderRadius: 8, padding: 9, marginTop: 7 }}>#{task.id} · {task.title}<div style={muted}>{label(task.status)} · {task.priority} · {date(task.updatedAt)}</div></div>) : <p style={muted}>لا توجد مهام مسندة مسجلة.</p>}
            </div>
            <div style={{ marginTop: 14 }}><strong>سجل التشغيلات</strong>
              {selectedAgent.runs?.length ? selectedAgent.runs.map((run: Item) => <div key={run.id} style={{ background: '#101722', borderRadius: 8, padding: 9, marginTop: 7 }}>تشغيل #{run.id} · المهمة #{run.taskId || '—'} · {label(run.status)}<div style={muted}>الخطوات: {run.steps} · {date(run.updatedAt || run.createdAt)}</div></div>) : <p style={muted}>لا توجد تشغيلات مسجلة لهذا الوكيل.</p>}
            </div>
            <div style={{ marginTop: 14 }}><strong>المراجعات التي أجراها</strong>
              {selectedAgent.reviews?.length ? selectedAgent.reviews.map((review: Item) => <div key={review.id} style={{ background: '#101722', borderRadius: 8, padding: 9, marginTop: 7 }}>مراجعة #{review.id} · المهمة #{review.taskId || '—'} · {review.verdict} · {review.score ?? '—'}<div style={muted}>{date(review.ts)}</div>{review.notes && <p style={{ fontSize: 13, whiteSpace: 'pre-wrap' }}>{review.notes}</p>}</div>) : <p style={muted}>لا توجد مراجعات مسجلة باسم معرّف هذا الوكيل.</p>}
            </div>
            <div style={{ ...muted, marginTop: 14 }}>ملف للعرض فقط. لا توجد أزرار لتعديل الوكيل أو تشغيله أو إيقافه في هذه المرحلة.</div>
          </section>}
        </>}

        {tab === 'tasks' && <>
          <section style={{ ...panel, marginBottom: 10 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(190px,1fr))', gap: 9 }}>
              <label style={{ display: 'grid', gap: 5, ...muted }}>
                البحث في المهام
                <input value={query} onChange={e => setQuery(e.target.value)} placeholder="رقم المهمة أو عنوانها أو المسؤول…" style={field} />
              </label>
              <label style={{ display: 'grid', gap: 5, ...muted }}>
                الحالة
                <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} style={field}>
                  <option value="all">كل الحالات</option>
                  {Array.from(new Set(tasks.map(task => String(task.status || 'unknown')))).sort().map(status =>
                    <option key={status} value={status}>{label(status)}</option>
                  )}
                </select>
              </label>
              <label style={{ display: 'grid', gap: 5, ...muted }}>
                الإدارة
                <select value={departmentFilter} onChange={e => setDepartmentFilter(e.target.value)} style={field}>
                  <option value="all">كل الإدارات</option>
                  {departments.map(dept => <option key={dept.id} value={String(dept.id)}>{dept.name}</option>)}
                </select>
              </label>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
              <span style={muted}>النتائج: {filteredTasks.length} من {tasks.length} مهمة مسترجعة</span>
              <button onClick={resetFilters} style={{ background: 'transparent', color: '#b8c9e6', border: '1px solid #39465c', borderRadius: 7, padding: '7px 10px', cursor: 'pointer' }}>مسح عوامل التصفية</button>
            </div>
          </section>
          <section style={{ display: 'grid', gap: 9 }}>
            {filteredTasks.map(task => {
              const relatedRuns = runs.filter(run => String(run.taskId || '') === String(task.id));
              const relatedReviews = reviews.filter(review => String(review.taskId || '') === String(task.id));
              return <article key={task.id} style={panel}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' }}>
                  <strong>#{task.id} · {task.title}</strong>
                  <span style={{ color: '#b9c9e2', fontSize: 12 }}>{label(task.status)} · الأولوية: {task.priority}</span>
                </div>
                <p style={{ ...muted, lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>{task.description || 'لا يوجد وصف'}</p>
                <div style={muted}>المسؤول: {task.assignedTo?.name || 'غير مسندة'} · الإدارة: {task.department?.name || 'غير محددة'} · المهمة الأم: {task.parentId || '—'}</div>
                <details style={{ marginTop: 10 }}>
                  <summary style={{ cursor: 'pointer', color: '#b8c9e6' }}>تفاصيل المهمة وسجلها ({relatedRuns.length} تشغيلات · {relatedReviews.length} مراجعات)</summary>
                  <div style={{ marginTop: 10, borderTop: '1px solid #30394b', paddingTop: 10 }}>
                    <div style={muted}>أُنشئت: {date(task.createdAt)} · آخر تحديث: {date(task.updatedAt || task.createdAt)}</div>
                    {task.result && <div style={{ marginTop: 10 }}>
                      <strong style={{ fontSize: 13 }}>النتيجة المسجلة</strong>
                      <p style={{ whiteSpace: 'pre-wrap', lineHeight: 1.7, fontSize: 13 }}>{task.result}</p>
                      <div style={muted}>قد يكون النص المعروض مقتطفاً محدود الطول من سجل المحرك.</div>
                    </div>}
                    <div style={{ marginTop: 12 }}>
                      <strong style={{ fontSize: 13 }}>التشغيلات المرتبطة</strong>
                      {relatedRuns.length ? relatedRuns.map(run =>
                        <div key={run.id} style={{ background: '#101722', borderRadius: 8, padding: 9, marginTop: 7 }}>
                          <div>تشغيل #{run.id} · {label(run.status)} · الوكيل: {run.agentName}</div>
                          <div style={muted}>الخطوات: {run.steps} · آخر تحديث: {date(run.updatedAt || run.createdAt)}</div>
                        </div>
                      ) : <p style={muted}>لا توجد تشغيلات مسترجعة لهذه المهمة.</p>}
                    </div>
                    <div style={{ marginTop: 12 }}>
                      <strong style={{ fontSize: 13 }}>المراجعات المرتبطة</strong>
                      {relatedReviews.length ? relatedReviews.map(review =>
                        <div key={review.id} style={{ background: '#101722', borderRadius: 8, padding: 9, marginTop: 7 }}>
                          <div>مراجعة #{review.id} · القرار: {review.verdict} · التقييم: {review.score ?? '—'}</div>
                          <div style={{ ...muted, marginTop: 4 }}>المراجع: {review.reviewer} · {date(review.ts)}</div>
                          {review.notes && <p style={{ whiteSpace: 'pre-wrap', fontSize: 13 }}>{review.notes}</p>}
                        </div>
                      ) : <p style={muted}>لا توجد مراجعات مسترجعة لهذه المهمة.</p>}
                    </div>
                  </div>
                </details>
              </article>;
            })}
            {!filteredTasks.length && <div style={panel}>لا توجد مهام تطابق عوامل البحث والتصفية الحالية.</div>}
          </section>
        </>}

        {tab === 'runs' && <>
          <div style={{ ...muted, marginBottom: 8 }}>«حديث النشاط» يتطلب حالة جارية وتحديثاً خلال آخر خمس دقائق؛ هذه اللوحة لا تشغّل شيئاً.</div>
          <section style={{ display: 'grid', gap: 9 }}>
            {runs.map(run =>
              <article key={run.id} style={panel}>
                <strong>تشغيل #{run.id} · المهمة #{run.taskId || '—'}: {run.taskTitle}</strong>
                <div style={{ marginTop: 7, fontSize: 13 }}>الوكيل: {run.agentName} · الحالة المسجلة: {label(run.status)}</div>
                <div style={{ ...muted, marginTop: 6 }}>الخطوات: {run.steps} · آخر تحديث: {date(run.updatedAt || run.createdAt)}</div>
                <div style={{ marginTop: 7, color: run.isFresh ? '#9be2b0' : '#d8b77c', fontSize: 12 }}>{run.isFresh ? 'نشاط حديث بحسب وقت السجل' : 'لا يوجد دليل زمني كافٍ على نشاط حالي'}</div>
              </article>
            )}
            {!runs.length && <div style={panel}>لا توجد تشغيلات ضمن السجلات المسترجعة.</div>}
          </section>
        </>}

        {tab === 'audit' && <section style={{ display: 'grid', gap: 10 }}>
          <div style={{ ...muted, marginBottom: 2 }}>سجل تغييرات المؤسسة كما سجّلها المحرك. يمكنك البحث والتصفية والترتيب؛ السجل للعرض فقط ولا يتيح تعديل الأحداث أو حذفها.</div>
          <div style={{ ...panel, display: 'grid', gap: 10 }}>
            <input aria-label="البحث في سجل التدقيق" value={auditQuery}
              onChange={e => setAuditQuery(e.target.value)} placeholder="ابحث في الحدث أو التفاصيل أو المنفذ أو المعرّف…" style={field} />
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(145px,1fr))', gap: 8 }}>
              <label style={{ display: 'grid', gap: 5, ...muted }}>نوع الحدث
                <select value={auditActionFilter} onChange={e => setAuditActionFilter(e.target.value)} style={field}>
                  <option value="all">كل الأحداث</option>
                  {auditActions.map(action => <option key={action} value={action}>{action}</option>)}
                </select>
              </label>
              <label style={{ display: 'grid', gap: 5, ...muted }}>المنفذ
                <select value={auditActorFilter} onChange={e => setAuditActorFilter(e.target.value)} style={field}>
                  <option value="all">جميع المنفذين</option>
                  {auditActors.map(actor => <option key={actor} value={actor}>{actor}</option>)}
                </select>
              </label>
              <label style={{ display: 'grid', gap: 5, ...muted }}>من تاريخ
                <input type="date" value={auditFrom} max={auditTo || undefined}
                  onChange={e => setAuditFrom(e.target.value)} style={field} />
              </label>
              <label style={{ display: 'grid', gap: 5, ...muted }}>إلى تاريخ
                <input type="date" value={auditTo} min={auditFrom || undefined}
                  onChange={e => setAuditTo(e.target.value)} style={field} />
              </label>
              <label style={{ display: 'grid', gap: 5, ...muted }}>ترتيب الأحداث
                <select value={auditSort} onChange={e => setAuditSort(e.target.value)} style={field}>
                  <option value="newest">الأحدث أولاً</option>
                  <option value="oldest">الأقدم أولاً</option>
                </select>
              </label>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <span style={muted}>يعرض {filteredAuditLog.length} من أصل {activityLog.length} حدثاً</span>
              <button type="button" onClick={resetAuditFilters}
                style={{ background: 'transparent', color: '#cbd5e1', border: '1px solid #52627b', borderRadius: 8, padding: '8px 12px' }}>
                مسح عوامل التصفية
              </button>
            </div>
          </div>
          {filteredAuditLog.map((entry: Item, index: number) => {
            const actionNames: Record<string, string> = {
              agent_profile_updated: 'تعديل بيانات وكيل',
              department_profile_updated: 'تعديل بيانات إدارة',
              task_created: 'إنشاء مهمة',
              task_assigned: 'إسناد مهمة',
              task_submitted: 'تسليم مهمة',
              task_reviewed: 'مراجعة مهمة',
              run_started: 'بدء تشغيل',
              run_stopped: 'إيقاف تشغيل',
              approval_requested: 'طلب موافقة',
              approval_approved: 'الموافقة على إجراء',
              approval_rejected: 'رفض إجراء',
              agent_created: 'إنشاء وكيل',
              goal_planned: 'تخطيط هدف',
            };
            const action = String(entry.action || '');
            return <article key={String(entry.id || action + '-' + index)} style={panel}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap' }}>
                <strong>{actionNames[action] || action.replaceAll('_', ' ') || 'حدث مسجل'}</strong>
                <span style={{ ...muted, direction: 'ltr' }}>{action}</span>
              </div>
              {entry.details && <div style={{ marginTop: 9, padding: 10, background: '#101722', borderRadius: 8, fontSize: 13, lineHeight: 1.7, overflowWrap: 'anywhere' }}>
                <span style={muted}>التفاصيل: </span>{entry.details}
              </div>}
              <div style={{ ...muted, marginTop: 9 }}>المنفذ: {entry.who || 'غير محدد'} · {date(entry.t)}{entry.id ? ' · سجل #' + entry.id : ''}</div>
            </article>;
          })}
          {!filteredAuditLog.length && <div style={panel}>
            {activityLog.length ? 'لا توجد أحداث تطابق عوامل البحث والتصفية الحالية.' : 'لا توجد أحداث تدقيق ضمن السجلات المسترجعة.'}
          </div>}
        </section>}

        {tab === 'reviews' && <section style={{ display: 'grid', gap: 9 }}>
          {reviews.map(review =>
            <article key={review.id} style={panel}>
              <strong>مراجعة #{review.id} · المهمة #{review.taskId || '—'}</strong>
              <div style={{ marginTop: 7, fontSize: 13 }}>المراجع: {review.reviewer} · القرار: {review.verdict} · التقييم: {review.score ?? '—'}</div>
              <p style={{ ...muted, whiteSpace: 'pre-wrap', lineHeight: 1.7 }}>{review.notes || 'لا توجد ملاحظات'}</p>
              <div style={muted}>{date(review.ts)}</div>
            </article>
          )}
          {!reviews.length && <div style={panel}>لا توجد مراجعات ضمن السجلات المسترجعة.</div>}
        </section>}

        {editor && <div role="dialog" aria-modal="true" aria-labelledby="office-edit-title"
          style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,0.72)', display: 'grid', placeItems: 'center', padding: 14 }}>
          <section style={{ ...panel, width: 'min(100%, 480px)', boxShadow: '0 20px 70px rgba(0,0,0,0.5)' }}>
            <h2 id="office-edit-title" style={{ margin: '0 0 6px', fontSize: 19 }}>تعديل {editor.kind === 'agent' ? 'بيانات الوكيل' : 'بيانات الإدارة'}</h2>
            <p style={muted}>#{editor.id} · {editor.title}. لا يمكن من هذه النافذة تغيير الصلاحيات أو المسؤولين أو تشغيل الوكلاء.</p>
            <label style={{ display: 'grid', gap: 5, ...muted, marginTop: 12 }}>
              {editor.kind === 'agent' ? 'اسم الوكيل' : 'اسم الإدارة'}
              <input value={editName} maxLength={80} onChange={e => { setEditName(e.target.value); setConfirmSave(false); }} style={field} />
            </label>
            <label style={{ display: 'grid', gap: 5, ...muted, marginTop: 10 }}>
              {editor.kind === 'agent' ? 'التخصص' : 'الوصف'}
              <textarea value={editDetail} maxLength={editor.kind === 'agent' ? 200 : 500}
                onChange={e => { setEditDetail(e.target.value); setConfirmSave(false); }}
                style={{ ...field, minHeight: 90, resize: 'vertical' }} />
            </label>
            <label style={{ display: 'flex', gap: 9, alignItems: 'flex-start', marginTop: 13, color: '#e6edf8', fontSize: 13, lineHeight: 1.6 }}>
              <input type="checkbox" checked={confirmSave} onChange={e => setConfirmSave(e.target.checked)} />
              أؤكد حفظ هذه التغييرات في قاعدة بيانات المؤسسة، مع تسجيلها في سجل التدقيق.
            </label>
            {saveError && <div role="alert" style={{ color: '#ffb9b9', marginTop: 10, fontSize: 13 }}>{saveError}</div>}
            <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
              <button disabled={!confirmSave || saving || !editName.trim() || !editDetail.trim() ||
                (editName.trim() === editor.originalName && editDetail.trim() === editor.originalDetail)}
                onClick={saveProfile}
                style={{ flex: 1, background: confirmSave ? '#285b43' : '#26313f', color: '#fff', border: 0, borderRadius: 8, padding: 10, opacity: saving ? 0.6 : 1 }}>
                {saving ? 'جارٍ الحفظ…' : 'تأكيد الحفظ'}
              </button>
              <button disabled={saving} onClick={() => setEditor(null)}
                style={{ background: 'transparent', color: '#cbd5e1', border: '1px solid #52627b', borderRadius: 8, padding: '10px 14px' }}>
                إلغاء
              </button>
            </div>
          </section>
        </div>}

        <footer style={{ ...muted, marginTop: 18, textAlign: 'center' }}>
          آخر مزامنة: {date(data.timestamp || '')} · التعديل محصور في الأسماء والأوصاف بموافقة صريحة · لا يوجد تشغيل للوكلاء أو تنفيذ للمهام
        </footer>
      </>}
    </div>
  </main>;
}
