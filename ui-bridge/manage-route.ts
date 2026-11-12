import { NextResponse } from 'next/server';
import { requireAuth } from '../../../lib/auth';

export async function POST(request: Request) {
  const authError = requireAuth(request);
  if (authError) return authError;

  // Reject cross-origin browser writes. This app is a local owner console.
  const origin = request.headers.get('origin');
  const host = request.headers.get('host');
  if (!origin || !host) {
    return NextResponse.json({ error: 'same_origin_required' }, { status: 403 });
  }
  try {
    if (new URL(origin).host !== host) {
      return NextResponse.json({ error: 'same_origin_required' }, { status: 403 });
    }
  } catch {
    return NextResponse.json({ error: 'invalid_origin' }, { status: 403 });
  }

  const bridgeUrl = process.env.OFFICE_API_URL || 'http://127.0.0.1:8765/api/office';
  const bridgeToken = process.env.OFFICE_API_TOKEN;
  if (!bridgeToken || bridgeToken.length < 24) {
    return NextResponse.json({ error: 'office_bridge_not_configured' }, { status: 503 });
  }

  let payload: Record<string, unknown>;
  try {
    const raw = await request.text();
    if (raw.length > 8192) {
      return NextResponse.json({ error: 'invalid_body_size' }, { status: 413 });
    }
    payload = JSON.parse(raw);
  } catch {
    return NextResponse.json({ error: 'invalid_json' }, { status: 400 });
  }
  if (!payload || typeof payload !== 'object' || Array.isArray(payload) || payload.confirm !== true) {
    return NextResponse.json({ error: 'explicit_confirmation_required' }, { status: 403 });
  }

  try {
    const upstream = await fetch(bridgeUrl.replace(/\\/$/, '') + '/manage', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${bridgeToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
      cache: 'no-store',
    });
    const result = await upstream.json().catch(() => ({ error: 'invalid_bridge_response' }));
    return NextResponse.json(result, {
      status: upstream.status,
      headers: { 'Cache-Control': 'no-store' },
    });
  } catch {
    return NextResponse.json({ error: 'office_bridge_connection_failed' }, { status: 503 });
  }
}
