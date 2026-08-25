import { withApi } from '@/lib/api/route';
import { ok } from '@/lib/api/respond';
import { listTeamMembers } from '@/lib/github/client';

export const dynamic = 'force-dynamic';

/**
 * GET /api/v1/members — members of the configured GitHub team.
 * Returns an empty list for token callers, which have no GitHub credential.
 */
export const GET = withApi(async ({ principal }) => {
  if (!principal.githubToken) return ok({ members: [], note: 'Requires a signed-in session.' });
  return ok({ members: await listTeamMembers(principal.githubToken) });
});
