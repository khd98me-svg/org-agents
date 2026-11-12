import { NextResponse } from 'next/server';
import { requireAuth } from '../../../../lib/auth';

export async function GET(request: Request) {
  const authError = requireAuth(request);
  if (authError) return authError;
  return NextResponse.json({
    waterCooler: { enabled: false, frequency: '45s', maxMessages: 0, quiet: { enabled: false, start: '23:00', end: '08:00' } },
    mission: { goal: '', priorities: [], context: '' },
    mode: 'read_only',
    notice: 'Legacy OpenClaw settings are disconnected from the organization engine.',
  });
}

export async function POST() {
  return NextResponse.json({ error: 'legacy_config_disabled' }, { status: 405 });
}
