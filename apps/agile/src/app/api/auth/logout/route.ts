import { NextResponse } from 'next/server';
import { config } from '@/lib/env';
import { SESSION_COOKIE } from '@/lib/auth/session';

export const dynamic = 'force-dynamic';

function clear() {
  const res = NextResponse.redirect(new URL('/login', config.appUrl));
  res.cookies.set(SESSION_COOKIE, '', {
    httpOnly: true,
    secure: config.isProduction,
    sameSite: 'lax',
    path: '/',
    maxAge: 0,
  });
  return res;
}

export const GET = clear;
export const POST = clear;
