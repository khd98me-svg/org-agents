import { NextResponse } from 'next/server';
import { requireAuth } from '../../../../lib/auth';

export async function GET(request: Request) {
  const authError = requireAuth(request);
  if (authError) return authError;
  return NextResponse.json({ active: false, topic: '', participants: [], transcript: [], mode: 'read_only' });
}

export async function POST() {
  return NextResponse.json({ error: 'legacy_meeting_disabled' }, { status: 405 });
}

export async function DELETE() {
  return NextResponse.json({ error: 'legacy_meeting_disabled' }, { status: 405 });
}
