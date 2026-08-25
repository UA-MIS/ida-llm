import { withApi } from '@/lib/api/route';
import { ok } from '@/lib/api/respond';
import { listTeamMembers } from '@/lib/github/client';
import { githubReadToken } from '@/lib/github/credential';

export const dynamic = 'force-dynamic';

/**
 * GET /api/v1/members — members of the configured GitHub team.
 * Returns an empty list for token callers, which have no GitHub credential.
 */
export const GET = withApi(async ({ principal }) => {
  const token = githubReadToken(principal);
  if (!token) {
    return ok({
      members: [],
      note: 'No GitHub credential available. Set GITHUB_POLL_TOKEN to populate the assignee picker when signing in through Dex.',
    });
  }
  return ok({ members: await listTeamMembers(token) });
});
