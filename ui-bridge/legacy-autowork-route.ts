import { NextResponse } from 'next/server';
import { requireAuth } from '../../../../lib/auth';

export async function GET(request: Request) {
  const authError = requireAuth(request);
  if (authError) return authError;
  return NextResponse.json({
    maxSendsPerTick: 0,
    mission: {},
    policies: {},
    mode: 'read_only',
    notice: 'Legacy OpenClaw autowork is disabled until connected to the organization engine.',
  });
}

export async function POST() {
  return NextResponse.json({ error: 'legacy_autowork_disabled' }, { status: 405 });
}

export async function PUT() {
  return NextResponse.json({ error: 'legacy_autowork_disabled' }, { status: 405 });
}
