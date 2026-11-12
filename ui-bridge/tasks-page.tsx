'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useAuthenticatedFetch } from '../../hooks/useAuthenticatedFetch';

type Row = Record<string, any>;
const field: React.CSSProperties = {
  width: '100%', boxSizing: 'border-box', background: '#0e1420', color: '#edf2fa',
  border: '1px solid #39465c', borderRadius: 8, padding: '10px 11px', minHeight: 42,
};
const panel: React.CSSProperties = {
  background: '#151a24', border: '1px solid #30394b', borderRadius: 12,
  padding: 14, minWidth: 0,
};
const muted: React.CSSProperties = { color: '#aab4c5', fontSize: 12 };
const statuses: Record<string, string> = {
  pending: 'بانتظار مسؤول', assigned: 'مسندة', submitted: 'بانتظار المراجعة',
  blocked: 'متوقفة', done: 'منجزة', rejected: 'مرفوضة',
};
const date = (value: string) => {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('ar-SA');
};

export default function TasksPage() {
  const authFetch = useAuthenticatedFetch();
  const [data, setData] = useState<{ tasks: Row[]; agents: Row[]; departments: Row[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [priority, setPriority] = useState('normal');
  const [departmentId, setDepartmentId] = useState('');
  const [createConfirmed, setCreateConfirmed] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState('');
  const [createNotice, setCreateNotice] = useState('');
  const [assignees, setAssignees] = useState<Record<string, string>>({});
  const [confirmedAssignments, setConfirmedAssignments] = useState<Record<string, boolean>>({});
  const [savingTask, setSavingTask] = useState('');
  const [taskError, setTaskError] = useState<Record<string, string>>({});
  const [taskNotice, setTaskNotice] = useState('');

  const load = useCallback(async () => {
    try {
      const response = await authFetch('/api/office', { cache: 'no-store' });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || ('HTTP ' + response.status));
      setData({ tasks: body.tasks || [], agents: body.agents || [], departments: body.departments || [] });
      setError('');
    } catch (err: any) {
      setError(err?.message || 'تعذر تحميل المهام');
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  useEffect(() => {
    load();
    const timer = setInterval(load, 15000);
    return () => clearInterval(timer);
  }, [load]);

  const tasks = data?.tasks || [];
  const agents = (data?.agents || []).filter(agent => agent.sourceStatus === 'active');
  const departments = (data?.departments || []).filter(dept => dept.status === 'active');
  const openTasks = useMemo(() => tasks.filter(task => ['pending', 'assigned', 'blocked'].includes(task.status)), [tasks]);

  const createTask = useCallback(async () => {
    if (!createConfirmed || !title.trim()) return;
    setCreating(true);
    setCreateError('');
    setCreateNotice('');
    try {
      const response = await authFetch('/api/office/manage', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          operation: 'task_create',
          title: title.trim(),
          description: description.trim(),
          priority,
          department_id: departmentId ? Number(departmentId) : null,
          confirm: true,
        }),
        cache: 'no-store',
      });
      const body = await response.json();
      if (!response.ok) {
        const messages: Record<string, string> = {
          invalid_title: 'عنوان المهمة مطلوب وبحد أقصى 200 حرف.',
          invalid_description: 'الوصف يجب ألا يتجاوز 2000 حرف.',
          invalid_priority: 'الأولوية المحددة غير صالحة.',
          department_not_found_or_inactive: 'الإدارة المختارة غير موجودة أو غير نشطة.',
        };
        throw new Error(messages[body.error] || body.error || ('HTTP ' + response.status));
      }
      setTitle('');
      setDescription('');
      setPriority('normal');
      setDepartmentId('');
      setCreateConfirmed(false);
      setCreateNotice('أُنشئت المهمة #' + body.id + ' بحالة «بانتظار مسؤول». لم يُسندها النظام ولم يشغّل أي وكيل.');
      await load();
    } catch (err: any) {
      setCreateError(err?.message || 'تعذر إنشاء المهمة');
    } finally {
      setCreating(false);
    }
  }, [authFetch, createConfirmed, title, description, priority, departmentId, load]);

  const assignTask = useCallback(async (task: Row) => {
    const selected = assignees[String(task.id)] ?? String(task.assignedTo?.id || '');
    if (!confirmedAssignments[String(task.id)]) return;
    setSavingTask(String(task.id));
    setTaskError(current => ({ ...current, [String(task.id)]: '' }));
    setTaskNotice('');
    try {
      const response = await authFetch('/api/office/manage', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          operation: 'task_assign',
          id: Number(task.id),
          assigned_to: selected ? Number(selected) : null,
          confirm: true,
        }),
        cache: 'no-store',
      });
      const body = await response.json();
      if (!response.ok) {
        const messages: Record<string, string> = {
          task_locked: 'لا يمكن تغيير إسناد مهمة بانتظار المراجعة أو منجزة أو مرفوضة.',
          assignee_not_found: 'الوكيل المختار غير موجود.',
          assignee_inactive: 'لا يمكن إسناد المهمة إلى وكيل غير نشط.',
          no_changes: 'لم يتغير المسؤول عن المهمة.',
        };
        throw new Error(messages[body.error] || body.error || ('HTTP ' + response.status));
      }
      setConfirmedAssignments(current => ({ ...current, [String(task.id)]: false }));
      setTaskNotice(selected ? 'أُسندت المهمة #' + task.id + '، وسُجل الإسناد وأُرسل إشعار داخلي للوكيل.' : 'أُزيل إسناد المهمة #' + task.id + ' وأعيدت إلى قائمة الانتظار.');
      await load();
    } catch (err: any) {
      setTaskError(current => ({ ...current, [String(task.id)]: err?.message || 'تعذر تحديث الإسناد' }));
    } finally {
      setSavingTask('');
    }
  }, [authFetch, assignees, confirmedAssignments, load]);

  return <main dir="rtl" style={{ minHeight: '100vh', background: '#0b0f17', color: '#edf2fa', padding: '18px 14px 40px', fontFamily: 'system-ui, sans-serif' }}>
    <header style={{ maxWidth: 1050, margin: '0 auto 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
      <div>
        <h1 style={{ margin: 0, fontSize: 25 }}>إدارة المهام</h1>
        <p style={{ ...muted, margin: '5px 0 0' }}>إنشاء المهام وإسنادها ومتابعتها. لا تتضمن هذه الصفحة تشغيل الوكلاء أو تنفيذ المهام.</p>
      </div>
      <a href="/organization" style={{ color: '#b8c9e6', border: '1px solid #39465c', borderRadius: 8, padding: '9px 12px', textDecoration: 'none' }}>لوحة المؤسسة</a>
    </header>
    <div style={{ maxWidth: 1050, margin: '0 auto', display: 'grid', gap: 12 }}>
      {error && <div role="alert" style={{ ...panel, color: '#ffb9b9' }}>تعذر الاتصال: {error}</div>}
      {loading && !data && <div style={panel}>جارٍ تحميل بيانات المؤسسة…</div>}

      <section style={panel}>
        <h2 style={{ margin: '0 0 10px', fontSize: 18 }}>إنشاء مهمة جديدة</h2>
        <div style={{ display: 'grid', gap: 9 }}>
          <label style={{ display: 'grid', gap: 5, ...muted }}>عنوان المهمة
            <input value={title} maxLength={200} onChange={event => { setTitle(event.target.value); setCreateConfirmed(false); }} placeholder="اكتب عنواناً واضحاً للمهمة" style={field} />
          </label>
          <label style={{ display: 'grid', gap: 5, ...muted }}>الوصف والمتطلبات
            <textarea value={description} maxLength={2000} onChange={event => { setDescription(event.target.value); setCreateConfirmed(false); }} rows={4} placeholder="صف المطلوب ومعيار اكتمال المهمة" style={{ ...field, resize: 'vertical' }} />
          </label>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 9 }}>
            <label style={{ display: 'grid', gap: 5, ...muted }}>الإدارة
              <select value={departmentId} onChange={event => { setDepartmentId(event.target.value); setCreateConfirmed(false); }} style={field}>
                <option value="">دون تحديد إدارة</option>
                {departments.map(dept => <option key={dept.id} value={String(dept.id)}>{dept.name}</option>)}
              </select>
            </label>
            <label style={{ display: 'grid', gap: 5, ...muted }}>الأولوية
              <select value={priority} onChange={event => { setPriority(event.target.value); setCreateConfirmed(false); }} style={field}>
                <option value="low">منخفضة</option>
                <option value="normal">عادية</option>
                <option value="high">عالية</option>
                <option value="urgent">عاجلة</option>
              </select>
            </label>
          </div>
          <label style={{ display: 'flex', gap: 9, alignItems: 'flex-start', fontSize: 13, lineHeight: 1.6 }}>
            <input type="checkbox" checked={createConfirmed} onChange={event => setCreateConfirmed(event.target.checked)} />
            أؤكد إنشاء هذه المهمة في قاعدة بيانات المؤسسة. ستبدأ بانتظار مسؤول ولن يبدأ أي وكيل تلقائياً.
          </label>
          {createError && <div role="alert" style={{ color: '#ffb9b9', fontSize: 13 }}>{createError}</div>}
          {createNotice && <div role="status" style={{ color: '#a9e5bd', fontSize: 13 }}>{createNotice}</div>}
          <button disabled={!createConfirmed || !title.trim() || creating} onClick={createTask}
            style={{ background: createConfirmed ? '#285b43' : '#26313f', color: '#fff', border: 0, borderRadius: 8, padding: 11, cursor: 'pointer', opacity: creating ? 0.6 : 1 }}>
            {creating ? 'جارٍ إنشاء المهمة…' : 'تأكيد إنشاء المهمة'}
          </button>
        </div>
      </section>

      <section style={{ display: 'grid', gap: 9 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <h2 style={{ margin: 0, fontSize: 18 }}>المهام المسجلة ({tasks.length})</h2>
          <span style={muted}>مفتوحة وقابلة للإسناد: {openTasks.length}</span>
        </div>
        {taskNotice && <div role="status" style={{ ...panel, color: '#a9e5bd' }}>{taskNotice}</div>}
        {tasks.map(task => {
          const editable = ['pending', 'assigned', 'blocked'].includes(task.status);
          const currentAssignee = String(task.assignedTo?.id || '');
          const selected = assignees[String(task.id)] ?? currentAssignee;
          const changed = selected !== currentAssignee;
          return <article key={task.id} style={panel}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' }}>
              <strong>#{task.id} · {task.title}</strong>
              <span style={muted}>{statuses[task.status] || task.status} · الأولوية: {task.priority || 'normal'}</span>
            </div>
            {task.description && <p style={{ whiteSpace: 'pre-wrap', lineHeight: 1.7, fontSize: 13 }}>{task.description}</p>}
            <div style={muted}>المسؤول الحالي: {task.assignedTo?.name || 'غير مسندة'} · الإدارة: {task.department?.name || 'غير محددة'} · آخر تحديث: {date(task.updatedAt || task.createdAt)}</div>
            {editable && <div style={{ display: 'grid', gap: 8, marginTop: 12, borderTop: '1px solid #30394b', paddingTop: 12 }}>
              <label style={{ display: 'grid', gap: 5, ...muted }}>إسناد المهمة إلى
                <select value={selected} onChange={event => {
                  setAssignees(current => ({ ...current, [String(task.id)]: event.target.value }));
                  setConfirmedAssignments(current => ({ ...current, [String(task.id)]: false }));
                }} style={field}>
                  <option value="">دون مسؤول (قائمة الانتظار)</option>
                  {agents.map(agent => <option key={agent.id} value={String(agent.id)}>{agent.name} · #{agent.id}</option>)}
                </select>
              </label>
              {changed && <>
                <label style={{ display: 'flex', gap: 9, alignItems: 'flex-start', fontSize: 13, lineHeight: 1.6 }}>
                  <input type="checkbox" checked={Boolean(confirmedAssignments[String(task.id)])}
                    onChange={event => setConfirmedAssignments(current => ({ ...current, [String(task.id)]: event.target.checked }))} />
                  أؤكد تغيير إسناد المهمة وتسجيله في سجل التدقيق{selected ? ' وإرسال إشعار داخلي للوكيل.' : '.'}
                </label>
                <button disabled={!confirmedAssignments[String(task.id)] || savingTask === String(task.id)} onClick={() => assignTask(task)}
                  style={{ background: '#263b5a', color: '#fff', border: 0, borderRadius: 8, padding: 10, cursor: 'pointer', opacity: savingTask === String(task.id) ? 0.6 : 1 }}>
                  {savingTask === String(task.id) ? 'جارٍ تحديث الإسناد…' : 'تأكيد تغيير الإسناد'}
                </button>
              </>}
              {taskError[String(task.id)] && <div role="alert" style={{ color: '#ffb9b9', fontSize: 13 }}>{taskError[String(task.id)]}</div>}
            </div>}
            {!editable && <div style={{ ...muted, marginTop: 10 }}>الإسناد مقفل لهذه الحالة؛ لا يمكن تغييره من هذه المرحلة.</div>}
          </article>;
        })}
        {!tasks.length && <div style={panel}>لا توجد مهام مسجلة حتى الآن.</div>}
      </section>
      <p style={{ ...muted, lineHeight: 1.7 }}>حدود المرحلة: إنشاء المهمة، إسنادها أو إعادتها لقائمة الانتظار، وتسجيل ذلك في سجل التدقيق. لا يوجد زر تشغيل أو استئناف أو تنفيذ، ولا تتغير نتائج المهام أو قرارات مراجعتها.</p>
    </div>
  </main>;
}
