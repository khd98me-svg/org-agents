'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useAuthenticatedFetch } from '../../hooks/useAuthenticatedFetch';

type Item = Record<string, any>;
type Data = {
  agents?: Item[]; departments?: Item[]; tasks?: Item[]; runs?: Item[]; reviews?: Item[];
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

  const load = useCallback(async () => {
    try {
      const res = await authFetch('/api/office', { cache: 'no-store' });
      const body = await res.json();
      if (!res.ok) throw new Error(body.error || ('HTTP ' + res.status));
      setData(body); setError('');
    } catch (e: any) {
      setError(e?.message || 'تعذر تحميل بيانات المؤسسة');
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  useEffect(() => {
    load();
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, [load]);

  const summary = data?.organization?.summary || {};
  const tasks = data?.tasks || [];
  const runs = data?.runs || [];
  const reviews = data?.reviews || [];
  const departments = data?.departments || [];
  const tabs = [
    ['departments', 'الإدارات', departments.length],
    ['tasks', 'المهام', summary.tasks ?? tasks.length],
    ['runs', 'التشغيلات', runs.length],
    ['reviews', 'المراجعات', reviews.length],
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
          <div style={muted}>organization.db · وضع القراءة فقط · تحديث تلقائي كل 15 ثانية</div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <a href="/" style={{ color: '#b8c9e6', textDecoration: 'none', border: '1px solid #39465c', padding: '8px 12px', borderRadius: 8 }}>المكتب الافتراضي</a>
          <button onClick={load} style={{ background: '#263b5a', color: 'white', border: 0, padding: '9px 13px', borderRadius: 8 }}>تحديث الآن</button>
        </div>
      </header>

      {error && <div role="alert" style={{ ...panel, borderColor: '#a34b4b', color: '#ffb9b9', marginBottom: 14 }}>تعذر تحميل البيانات: {error}</div>}
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
                <button onClick={() => { setDepartmentFilter(String(dept.id)); setStatusFilter('all'); setQuery(''); setTab('tasks'); }}
                  style={{ marginTop: 12, width: '100%', background: '#263b5a', color: '#edf2fa', border: 0, borderRadius: 8, padding: 9, cursor: 'pointer' }}>
                  عرض مهام الإدارة
                </button>
              </article>
            )}
            {!departments.length && <div style={panel}>لا توجد إدارات في البيانات المسترجعة.</div>}
          </section>
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

        <footer style={{ ...muted, marginTop: 18, textAlign: 'center' }}>
          آخر مزامنة: {date(data.timestamp || '')} · جميع البيانات للعرض فقط · لم تُنفّذ أي أوامر على الوكلاء
        </footer>
      </>}
    </div>
  </main>;
}
