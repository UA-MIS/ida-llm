import { withApi } from '@/lib/api/route';
import { ok } from '@/lib/api/respond';
import { listTeamMembers } from '@/lib/github/client';
import { githubReadToken, missingCredentialMessage } from '@/lib/github/credential';

export const dynamic = 'force-dynamic';

/**
 * GET /api/v1/members — members of the configured GitHub team.
 * Returns an empty list for token callers, which have no GitHub credential.
 */
export const GET = withApi(async ({ principal }) => {
  const token = await githubReadToken(principal);
  if (!token) {
    return ok({
      members: [],
      note: missingCredentialMessage('Listing the team'),
    });
  }
  return ok({ members: await listTeamMembers(token) });
});
