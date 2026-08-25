import { withApi } from '@/lib/api/route';
import { ok } from '@/lib/api/respond';
import { listOpenPullRequests } from '@/lib/github/client';
import { extractWorkItemRefs } from '@/lib/github/prs';
import { githubReadToken } from '@/lib/github/credential';

export const dynamic = 'force-dynamic';

/** GET /api/v1/prs — open PRs across configured repos, annotated with AB#<id> refs. */
export const GET = withApi(async ({ principal }) => {
  const token = githubReadToken(principal);
  if (!token) {
    return ok({
      prs: [],
      note: 'No GitHub credential available. Set GITHUB_POLL_TOKEN to list pull requests when signing in through Dex.',
    });
  }
  const prs = await listOpenPullRequests(token);
  return ok({
    prs: prs.map((pr) => ({ ...pr, suggestedItemIds: extractWorkItemRefs(pr.title, pr.body) })),
  });
});
