import { authenticate, type Principal } from '@/lib/auth/principal';
import { ensureSchema } from '@/lib/bootstrap';
import { apiError } from './respond';
import { consume } from './ratelimit';

/**
 * The single entry point for every API route.
 *
 * Guarantees, in order, for UI and machine callers alike: the schema exists,
 * the caller is an authenticated member of the configured team, and they are
 * within their rate budget. There is no other way into the API — which is what
 * keeps the UI and the public API from drifting apart.
 */
export function withApi(
  handler: (ctx: { request: Request; principal: Principal; params: Record<string, string> }) => Promise<Response>,
) {
  return async (
    request: Request,
    context?: { params?: Promise<Record<string, string>> },
  ): Promise<Response> => {
    try {
      await ensureSchema();
    } catch (err) {
      console.error('[api] schema unavailable', err);
      return apiError('database_unavailable', 'The board database is not available yet. Retry shortly.', 503);
    }

    const auth = await authenticate(request);
    if (!auth.ok) {
      return apiError(auth.failure.reason.replace(/-/g, '_'), auth.failure.message, auth.failure.status);
    }

    const verdict = consume(`${auth.principal.source}:${auth.principal.login}`);
    if (!verdict.allowed) {
      return apiError(
        'rate_limited',
        `Too many requests. Retry in ${verdict.retryAfterSeconds}s.`,
        429,
      );
    }

    const params = context?.params ? await context.params : {};

    try {
      return await handler({ request, principal: auth.principal, params });
    } catch (err) {
      const message = (err as Error)?.message ?? 'Unexpected error';
      console.error('[api] unhandled error', err);
      return apiError('internal_error', `The request failed: ${message}`, 500);
    }
  };
}
