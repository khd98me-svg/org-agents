import { NextResponse } from 'next/server';
import { requireAuth } from '../../../lib/auth';

type Row = Record<string, any>;

function epoch(value: unknown): number {
  if (typeof value === 'number' && Number.isFinite(value)) return value < 1e12 ? value * 1000 : value;
  if (typeof value === 'string' && value.trim()) {
    const parsed = Date.parse(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  return 0;
}

function colorFor(id: string): string {
  let hash = 0;
  for (const char of id) hash = char.charCodeAt(0) + ((hash << 5) - hash);
  return `hsl(${Math.abs(hash) % 360}, 48%, 52%)`;
}

function isRunning(status: unknown): boolean {
  return typeof status === 'string' &&
    ['running', 'working', 'in_progress', 'in-progress'].includes(status.toLowerCase());
}

function makeAgent(agent: Row, runs: Row[], tasks: Row[], now: number) {
  const ownRuns = runs
    .filter(run => String(run.agent_id) === String(agent.id))
    .sort((a, b) => epoch(b.updated || b.created) - epoch(a.updated || a.created));
  const latest = ownRuns[0];
  const activeRun = latest && isRunning(latest.status) ? latest : undefined;
  const run = latest;
  const task = run ? tasks.find(item => String(item.id) === String(run.task_id)) : undefined;
  const lastActivity = epoch(run?.updated || run?.created || agent.created_at);
  const activeWindowMs = Number(process.env.OFFICE_ACTIVE_WINDOW_MS || 5 * 60 * 1000);
  // A stale 'running' row may be an orphan; never display it as live work.
  const working = Boolean(activeRun && lastActivity > 0 && now - lastActivity <= activeWindowMs);

  return {
    id: String(agent.id),
    name: String(agent.name || `Agent ${agent.id}`),
    role: String(agent.specialty || agent.role || 'Agent'),
    emoji: '🤖',
    color: colorFor(String(agent.id)),
    status: working ? 'working' : 'idle',
    // The source engine has no mood/XP/skills model. Keep these neutral;
    // the UI must label or hide gamified fields rather than present them as facts.
    mood: 'okay',
    task: working ? String(task?.title || 'Executing assigned task') : undefined,
    lastActive: lastActivity ? new Date(lastActivity).toISOString() : 'No recorded activity',
    isNew: ownRuns.length === 0,
    hasIdentity: false,
    needs: { energy: 0, output: 0, collab: 0, queue: 0, focus: 0 },
    skills: [],
    xp: 0,
    level: 1,
    workEvidence: {
      hasToolCalls: false,
      lastToolUseTs: 0,
      lastActivityTs: lastActivity,
    },
    sourceStatus: agent.status,
    managerId: agent.manager_id ?? null,
  };
}

export async function GET(request: Request) {
  const authError = requireAuth(request);
  if (authError) return authError;

  const bridgeUrl = process.env.OFFICE_API_URL || 'http://127.0.0.1:8765/api/office';
  const bridgeToken = process.env.OFFICE_API_TOKEN;
  if (!bridgeToken || bridgeToken.length < 24) {
    return NextResponse.json(
      { error: 'office_bridge_not_configured' },
      { status: 503 },
    );
  }

  try {
    const upstream = await fetch(bridgeUrl, {
      method: 'GET',
      headers: { Authorization: `Bearer ${bridgeToken}` },
      cache: 'no-store',
    });
    if (!upstream.ok) {
      return NextResponse.json(
        { error: 'office_bridge_unavailable', upstreamStatus: upstream.status },
        { status: 503 },
      );
    }

    const snapshot = await upstream.json();
    if (snapshot?.ok !== true || snapshot?.mode !== 'read_only' || !snapshot?.data) {
      return NextResponse.json({ error: 'invalid_office_snapshot' }, { status: 502 });
    }

    const tables = snapshot.data as Record<string, Row[]>;
    const now = Date.now();
    const agents = (tables.agents || []).map(agent =>
      makeAgent(agent, tables.runs || [], tables.tasks || [], now),
    );

    const rawDepartments = tables.departments || [];
    const rawTasks = tables.tasks || [];
    const rawRuns = tables.runs || [];
    const rawReviews = tables.reviews || [];
    const rawLinks = tables.agent_departments || [];
    const rawReporting = tables.reporting_lines || [];
    const agentNames = new Map((tables.agents || []).map(agent => [
      String(agent.id), String(agent.name || `Agent ${agent.id}`),
    ]));
    const departmentNames = new Map(rawDepartments.map(dept => [
      String(dept.id), String(dept.name || `Department ${dept.id}`),
    ]));

    const enrichedAgents = agents.map(agent => {
      const id = String(agent.id);
      const memberships = rawLinks.filter(link =>
        String(link.agent_id) === id && String(link.status || 'active') === 'active'
      ).map(link => {
        const dept = rawDepartments.find(item => String(item.id) === String(link.department_id));
        return { id: String(link.department_id), name: dept?.name || ('Department #' + link.department_id), role: String(link.role || 'member') };
      });
      const ownTasks = rawTasks.filter(task => String(task.assigned_to ?? '') === id);
      const ownRuns = rawRuns.filter(run => String(run.agent_id ?? '') === id);
      const ownReviews = rawReviews.filter(review => {
        const reviewer = String(review.reviewer ?? '').trim();
        // Review records may store a numeric agent ID, the agent name,
        // or the engine's stable "agent<N>" reviewer key.
        const agentKey = /^agent(\d+)$/i.exec(reviewer);
        return reviewer === id ||
          reviewer === String(agent.name || '').trim() ||
          (agentKey !== null && agentKey[1] === id);
      });
      const reportsTo = rawReporting.filter(line => String(line.subordinate_agent_id) === id).map(line => ({
        managerId: String(line.manager_agent_id),
        managerName: agentNames.get(String(line.manager_agent_id)) || ('Agent #' + line.manager_agent_id),
        relation: String(line.relation || 'reports_to'),
      }));
      const directReports = rawReporting.filter(line => String(line.manager_agent_id) === id).map(line => ({
        agentId: String(line.subordinate_agent_id),
        agentName: agentNames.get(String(line.subordinate_agent_id)) || ('Agent #' + line.subordinate_agent_id),
        relation: String(line.relation || 'manages'),
      }));
      return { ...agent, departments: memberships, tasks: ownTasks.map(task => ({
        id: String(task.id), title: String(task.title || ('Task #' + task.id)), status: String(task.status || 'unknown'),
        priority: String(task.priority || 'normal'), updatedAt: task.updated_at || task.created_at || '',
      })), runs: ownRuns.map(run => ({
        id: String(run.id), taskId: run.task_id == null ? null : String(run.task_id),
        status: String(run.status || 'unknown'), steps: Number(run.steps || 0),
        createdAt: run.created || '', updatedAt: run.updated || '',
      })), reviews: ownReviews.map(review => ({
        id: String(review.id), taskId: review.task_id == null ? null : String(review.task_id),
        verdict: String(review.verdict || 'unknown'), score: review.score ?? null,
        notes: String(review.notes || '').slice(0, 300), ts: review.ts || '',
      })), reportsTo, directReports };
    });

    const departments = rawDepartments.map(dept => {
      const members = (tables.agent_departments || [])
        .filter(link => String(link.department_id) === String(dept.id) && String(link.status || 'active') === 'active')
        .map(link => ({
          id: String(link.agent_id),
          name: agentNames.get(String(link.agent_id)) || `Agent #${link.agent_id}`,
          role: String(link.role || 'member'),
        }));
      return {
        id: String(dept.id),
        name: String(dept.name || 'قسم بلا اسم'),
        description: String(dept.description || ''),
        status: String(dept.status || 'unknown'),
        manager: dept.manager_agent_id == null ? null : {
          id: String(dept.manager_agent_id),
          name: agentNames.get(String(dept.manager_agent_id)) || `Agent #${dept.manager_agent_id}`,
        },
        parentId: dept.parent_department_id == null ? null : String(dept.parent_department_id),
        members,
        taskCount: rawTasks.filter(task => String(task.department_id || '') === String(dept.id)).length,
      };
    });

    const tasks = rawTasks.map(task => ({
      id: String(task.id),
      title: String(task.title || `Task #${task.id}`),
      description: String(task.description || '').slice(0, 500),
      status: String(task.status || 'unknown'),
      priority: String(task.priority || 'normal'),
      assignedTo: task.assigned_to == null ? null : {
        id: String(task.assigned_to),
        name: agentNames.get(String(task.assigned_to)) || `Agent #${task.assigned_to}`,
      },
      department: task.department_id == null ? null : {
        id: String(task.department_id),
        name: departmentNames.get(String(task.department_id)) || `Department #${task.department_id}`,
      },
      parentId: task.parent_id == null ? null : String(task.parent_id),
      createdAt: task.created_at || '',
      updatedAt: task.updated_at || '',
      result: String(task.result || '').slice(0, 500),
      score: task.score == null ? null : task.score,
    }));

    const activeWindowMs = Number(process.env.OFFICE_ACTIVE_WINDOW_MS || 5 * 60 * 1000);
    const runs = rawRuns.map(run => {
      const updatedMs = epoch(run.updated || run.created);
      const sourceRunning = isRunning(run.status);
      const linkedTask = rawTasks.find(task => String(task.id) === String(run.task_id));
      return {
        id: String(run.id),
        taskId: run.task_id == null ? null : String(run.task_id),
        taskTitle: linkedTask?.title || `Task #${run.task_id ?? '?'}`,
        agentId: run.agent_id == null ? null : String(run.agent_id),
        agentName: agentNames.get(String(run.agent_id)) || `Agent #${run.agent_id ?? '?'}`,
        status: String(run.status || 'unknown'),
        steps: Number(run.steps || 0),
        createdAt: run.created || '',
        updatedAt: run.updated || '',
        isFresh: Boolean(sourceRunning && updatedMs > 0 && now - updatedMs <= activeWindowMs),
      };
    });

    const reviews = (tables.reviews || []).map(review => ({
      id: String(review.id),
      taskId: review.task_id == null ? null : String(review.task_id),
      reviewer: String(review.reviewer || 'unknown'),
      verdict: String(review.verdict || 'unknown'),
      score: review.score == null ? null : review.score,
      notes: String(review.notes || '').slice(0, 500),
      ts: review.ts || '',
    }));

    const activityLog = (tables.audit || []).slice(0, 80).map(item => ({
      t: item.created_at || '',
      who: String(item.actor || 'system'),
      text: [item.action, item.details].filter(Boolean).join(': '),
    }));

    // Water Cooler is a conversation view, not a task-lifecycle feed.
    // Reuse agentNames created above for department/task labels as well.
    const chatLog = [
      ...(tables.ceo_chat || []).map(item => ({
        from: String(item.role || 'CEO'),
        text: String(item.content || ''),
        ts: epoch(item.ts),
      })),
      ...(tables.messages || [])
        .filter(item => String(item.kind || 'msg') === 'msg')
        .map(item => {
          const sender = item.sender == null ? 'owner' : String(item.sender);
          return {
            from: sender === 'owner' ? 'المالك' : (agentNames.get(sender) || `Agent #${sender}`),
            text: String(item.body || ''),
            ts: epoch(item.ts),
          };
        }),
    ].filter(item => item.text).sort((a, b) => a.ts - b.ts).slice(-100);

    return NextResponse.json({
      agents: enrichedAgents,
      departments,
      tasks,
      runs,
      reviews,
      activityLog,
      chatLog,
      setupCheck: {
        status: 'ok',
        message: 'Connected to the existing organization engine (limited profile management)',
      },
      organization: {
        mode: 'limited_management',
        counts: snapshot.counts || {},
        summary: {
          departments: departments.length,
          agents: agents.length,
          tasks: Number(snapshot.counts?.tasks ?? tasks.length),
          runs: runs.length,
          pendingTasks: tasks.filter(task => ['pending', 'assigned', 'blocked'].includes(task.status)).length,
          submittedTasks: tasks.filter(task => task.status === 'submitted').length,
          completedTasks: tasks.filter(task => task.status === 'done').length,
          freshRuns: runs.filter(run => run.isFresh).length,
        },
      },
      timestamp: new Date().toISOString(),
    }, {
      headers: { 'Cache-Control': 'no-store' },
    });
  } catch {
    return NextResponse.json({ error: 'office_bridge_connection_failed' }, { status: 503 });
  }
}
