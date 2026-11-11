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

    const activityLog = (tables.audit || []).slice(0, 80).map(item => ({
      t: item.created_at || '',
      who: String(item.actor || 'system'),
      text: [item.action, item.details].filter(Boolean).join(': '),
    }));

    const chatLog = [
      ...(tables.ceo_chat || []).map(item => ({
        from: String(item.role || 'CEO'),
        text: String(item.content || ''),
        ts: epoch(item.ts),
      })),
      ...(tables.messages || []).map(item => ({
        from: String(item.sender || 'unknown'),
        text: String(item.body || ''),
        ts: epoch(item.ts),
      })),
    ].filter(item => item.text).sort((a, b) => a.ts - b.ts).slice(-100);

    return NextResponse.json({
      agents,
      activityLog,
      chatLog,
      setupCheck: {
        status: 'ok',
        message: 'Connected to the existing organization engine (read-only)',
      },
      organization: {
        mode: 'read_only',
        counts: snapshot.counts || {},
      },
      timestamp: new Date().toISOString(),
    }, {
      headers: { 'Cache-Control': 'no-store' },
    });
  } catch {
    return NextResponse.json({ error: 'office_bridge_connection_failed' }, { status: 503 });
  }
}
