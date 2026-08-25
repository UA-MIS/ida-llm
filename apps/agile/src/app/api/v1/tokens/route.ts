import { z } from 'zod';
import { withApi } from '@/lib/api/route';
import { apiError, ok, readJson, validationError } from '@/lib/api/respond';
import { createApiToken, listApiTokens } from '@/lib/auth/tokens';

export const dynamic = 'force-dynamic';

const createSchema = z.object({
  name: z.string().trim().min(1).max(80),
  expiresInDays: z.number().int().min(1).max(365).nullable().default(90),
});

/** GET /api/v1/tokens — the caller's own tokens. Never returns token values. */
export const GET = withApi(async ({ principal }) => {
  return ok({ tokens: await listApiTokens(principal.login) });
});

/**
 * POST /api/v1/tokens — mint a token.
 *
 * Requires a signed-in session: a token may not mint further tokens, which
 * would let a leaked token silently extend its own lifetime.
 * The plaintext value is returned here ONCE and is never recoverable.
 */
export const POST = withApi(async ({ request, principal }) => {
  if (principal.source !== 'user' || !principal.githubToken) {
    return apiError(
      'session_required',
      'Creating an API token requires a signed-in GitHub session, not another API token.',
      403,
    );
  }

  const body = await readJson(request);
  if (!body.ok) return body.response;
  const parsed = createSchema.safeParse(body.value);
  if (!parsed.success) return validationError(parsed.error);

  const { token, record } = await createApiToken({
    name: parsed.data.name,
    ownerLogin: principal.login,
    githubToken: principal.githubToken,
    expiresInDays: parsed.data.expiresInDays,
  });

  return ok(
    {
      token,
      record,
      warning: 'Copy this token now — it is stored only as a hash and cannot be shown again.',
    },
    201,
  );
});
