import { NextResponse } from 'next/server';
import { requireAuth } from '../../../../lib/auth';

type Row = Record<string, any>;

function redact(value: unknown, depth = 0): unknown {
  if (depth > 5) return '[truncated]';
  if (Array.isArray(value)) return value.slice(0, 30).map(item => redact(item, depth + 1));
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      if (/token|secret|password|authorization|api[_-]?key|cookie/i.test(key)) {
        out[key] = '[redacted]';
      } else {
        out[key] = redact(item, depth + 1);
      }
    }
    return out;
  }
  if (typeof value === 'string') return value.length > 2000 ? value.slice(0, 2000) + '…' : value;
  return value;
}

function timestamp(value: unknown): number {
  if (typeof value === 'number' && Number.isFinite(value)) return value < 1e12 ? value * 1000 : value;
  if (typeof value === 'string' && value.trim()) {
    const parsed = Date.parse(value);
    return Number.isFinite(parsed) ? parsed : Date.now();
  }
  return Date.now();
}

function titleFor(kind: string): string {
  const labels: Record<string, string> = {
    create_department: 'طلب إنشاء إدارة',
    create_manager: 'طلب تعيين مدير',
    create_agent: 'طلب إنشاء وكيل',
    tool_call: 'طلب تشغيل أداة',
    tool: 'طلب استخدام أداة',
  };
  return labels[kind] || `طلب موافقة: ${kind || 'غير محدد'}`;
}

function toQuest(row: Row) {
  let payload: Record<string, unknown> = {};
  try {
    const parsed = typeof row.payload === 'string' ? JSON.parse(row.payload) : row.payload;
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) payload = parsed;
  } catch {
    payload = { raw: String(row.payload || '') };
  }
  const safePayload = redact(payload);
  const details = JSON.stringify(safePayload, null, 2);
  return {
    id: `org-approval-${row.id}`,
    type: 'read_only_approval',
    icon: '🛡️',
    title: titleFor(String(row.kind || '')),
    description: [
      `رقم الموافقة: #${row.id}`,
      `النوع: ${String(row.kind || 'غير محدد')}`,
      'الحالة: بانتظار موافقتك',
      'تفاصيل الطلب:',
      details.length > 4500 ? details.slice(0, 4500) + '…' : details,
    ].join('\\n'),
    from: 'محرك المؤسسة',
    priority: row.kind === 'tool_call' || row.kind === 'tool' ? 'high' : 'medium',
    createdAt: timestamp(row.ts),
    data: {
      readOnly: true,
      approvalId: row.id,
      approvalKind: row.kind,
    },
  };
}

export async function GET(request: Request) {
  const authError = requireAuth(request);
  if (authError) return authError;

  const bridgeUrl = process.env.OFFICE_API_URL || 'http://127.0.0.1:8765/api/office';
  const bridgeToken = process.env.OFFICE_API_TOKEN;
  if (!bridgeToken || bridgeToken.length < 24) {
    return NextResponse.json({ error: 'office_bridge_not_configured' }, { status: 503 });
  }

  const url = new URL(request.url);
  if (url.searchParams.has('archiveOffset')) {
    return NextResponse.json({ archive: [], archiveTotal: 0, offset: 0, limit: 0 });
  }

  try {
    const upstream = await fetch(bridgeUrl, {
      method: 'GET',
      headers: { Authorization: `Bearer ${bridgeToken}` },
      cache: 'no-store',
    });
    if (!upstream.ok) {
      return NextResponse.json({ error: 'office_bridge_unavailable' }, { status: 503 });
    }
    const snapshot = await upstream.json();
    if (snapshot?.ok !== true || snapshot?.mode !== 'read_only' || !snapshot?.data) {
      return NextResponse.json({ error: 'invalid_office_snapshot' }, { status: 502 });
    }
    const rows: Row[] = Array.isArray(snapshot.data.approvals) ? snapshot.data.approvals : [];
    const actions = rows
      .filter(row => String(row.status || '').toLowerCase() === 'pending')
      .map(toQuest)
      .sort((a, b) => b.createdAt - a.createdAt);
    return NextResponse.json({
      actions,
      accomplishments: [],
      approvalCounts: {
        total: rows.length,
        pending: actions.length,
      },
      source: 'organization.db:approvals',
      mode: 'read_only',
      timestamp: new Date().toISOString(),
    }, { headers: { 'Cache-Control': 'no-store' } });
  } catch {
    return NextResponse.json({ error: 'office_bridge_connection_failed' }, { status: 503 });
  }
}

// Decisions remain disabled until a separately reviewed, owner-authenticated
// engine command is implemented. Never route these to OpenClaw's legacy files.
export async function POST() {
  return NextResponse.json({ error: 'approval_actions_disabled_read_only' }, { status: 405 });
}
