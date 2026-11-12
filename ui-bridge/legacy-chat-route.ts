import { NextResponse } from 'next/server';
import { requireAuth } from '../../../../lib/auth';

export async function GET(request: Request) {
  const authError = requireAuth(request);
  if (authError) return authError;
  const url = new URL(request.url);
  if (url.searchParams.has('status')) return NextResponse.json({ nextChatIn: 0, mode: 'read_only' });
  return NextResponse.json([]);
}

export async function POST() {
  return NextResponse.json({ error: 'legacy_chat_disabled' }, { status: 405 });
}
