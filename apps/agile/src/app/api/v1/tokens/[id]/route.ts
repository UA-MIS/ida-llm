import { withApi } from '@/lib/api/route';
import { apiError, ok, parseId } from '@/lib/api/respond';
import { revokeApiToken } from '@/lib/auth/tokens';

export const dynamic = 'force-dynamic';

/** DELETE /api/v1/tokens/{id} — revoke. A caller may only revoke their own tokens. */
export const DELETE = withApi(async ({ params, principal }) => {
  const id = parseId(params.id ?? '');
  if (!id) return apiError('invalid_id', 'Token id must be a positive integer.', 400);
  const revoked = await revokeApiToken(id, principal.login);
  if (!revoked) {
    return apiError('not_found', 'That token does not exist, or is not yours, or is already revoked.', 404);
  }
  return ok({ revoked: id });
});
