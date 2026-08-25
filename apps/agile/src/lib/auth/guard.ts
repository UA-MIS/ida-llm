import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import { config } from '@/lib/env';
import { SESSION_COOKIE, unsealSession, type SessionPayload } from './session';
import { isStillOnTeam } from './revalidate';

/**
 * Reads the current session, or null. Never throws for an anonymous visitor.
 */
export async function getSession(): Promise<SessionPayload | null> {
  const jar = await cookies();
  return unsealSession(jar.get(SESSION_COOKIE)?.value, config.sessionSecret);
}

/**
 * For pages: redirects anonymous visitors to the sign-in screen.
 * Every page under the app shell must call this.
 */
export async function requireSession(returnTo = '/'): Promise<SessionPayload> {
  const session = await getSession();
  if (!session) {
    redirect(`/login?returnTo=${encodeURIComponent(returnTo)}`);
  }
  if (!(await isStillOnTeam(session.login, session.token))) {
    redirect(`/denied?reason=not-a-member&login=${encodeURIComponent(session.login)}`);
  }
  return session;
}

/**
 * For API routes: returns a 401 JSON response instead of redirecting.
 * Returns either the session or the Response to return immediately.
 */
export async function requireApiSession(): Promise<
  { ok: true; session: SessionPayload } | { ok: false; response: Response }
> {
  const session = await getSession();
  if (!session) {
    return {
      ok: false,
      response: Response.json(
        { error: 'Not authenticated. Sign in with GitHub.' },
        { status: 401 },
      ),
    };
  }
  if (!(await isStillOnTeam(session.login, session.token))) {
    return {
      ok: false,
      response: Response.json(
        { error: 'You are no longer a member of the ida-llm team.' },
        { status: 403 },
      ),
    };
  }
  return { ok: true, session };
}

export function jsonError(message: string, status: number): Response {
  return Response.json({ error: message }, { status });
}
