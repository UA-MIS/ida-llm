import { withApi } from '@/lib/api/route';
import { ok } from '@/lib/api/respond';
import { listOpenPullRequests } from '@/lib/github/client';
import { extractWorkItemRefs } from '@/lib/github/prs';

export const dynamic = 'force-dynamic';

/** GET /api/v1/prs — open PRs across configured repos, annotated with AB#<id> refs. */
export const GET = withApi(async ({ principal }) => {
  if (!principal.githubToken) return ok({ prs: [], note: 'Requires a signed-in session.' });
  const prs = await listOpenPullRequests(principal.githubToken);
  return ok({
    prs: prs.map((pr) => ({ ...pr, suggestedItemIds: extractWorkItemRefs(pr.title, pr.body) })),
  });
});
