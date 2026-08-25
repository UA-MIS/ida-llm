import { z } from 'zod';
import { withApi } from '@/lib/api/route';
import { apiError, ok, parseId, readJson, validationError } from '@/lib/api/respond';
import { principalToActor } from '@/lib/auth/principal';
import {
  getWorkItem,
  linkPullRequest,
  recordPrLinkActivity,
  unlinkPullRequest,
} from '@/lib/domain/queries';
import { parsePrReference } from '@/lib/github/prs';
import { fetchPullRequest } from '@/lib/github/client';
import { syncBacklinkComment } from '@/lib/sync/backlink';
import { config } from '@/lib/env';

export const dynamic = 'force-dynamic';

const linkSchema = z.object({ reference: z.string().min(1).max(300) });

/** POST /api/v1/items/{id}/links — attach a PR by URL, owner/repo#N, or bare number. */
export const POST = withApi(async ({ request, params, principal }) => {
  const id = parseId(params.id ?? '');
  if (!id) return apiError('invalid_id', 'Work item id must be a positive integer.', 400);

  const item = await getWorkItem(id);
  if (!item) return apiError('not_found', `Work item #${id} does not exist.`, 404);

  const body = await readJson(request);
  if (!body.ok) return body.response;
  const parsed = linkSchema.safeParse(body.value);
  if (!parsed.success) return validationError(parsed.error);

  const ref = parsePrReference(parsed.data.reference);
  if (!ref) {
    return apiError(
      'unparsable_reference',
      'Could not read that as a pull request. Use a PR URL, owner/repo#123, or just 123.',
      422,
    );
  }
  if (!config.isKnownRepo(ref.repoFullName)) {
    return apiError(
      'repo_not_configured',
      `Repository ${ref.repoFullName} is not configured for this board (GITHUB_REPOS).`,
      422,
    );
  }

  // Reading a PR needs a GitHub credential, which only a signed-in user has.
  if (!principal.githubToken) {
    return apiError(
      'github_credential_required',
      'Linking a pull request reads it from GitHub, so it requires a signed-in session rather than an API token.',
      400,
    );
  }

  const pr = await fetchPullRequest(ref.repoFullName, ref.prNumber, principal.githubToken);
  if (!pr) {
    return apiError(
      'pr_not_found',
      `Pull request ${ref.repoFullName}#${ref.prNumber} could not be found on GitHub.`,
      404,
    );
  }

  const actor = principalToActor(principal);
  const link = await linkPullRequest(
    id,
    {
      repoFullName: pr.repoFullName,
      prNumber: pr.number,
      url: pr.url,
      title: pr.title,
      prState: pr.state,
      merged: pr.merged,
      draft: pr.draft,
      checksState: pr.checksState,
      headRef: pr.headRef,
      baseRef: pr.baseRef,
    },
    actor,
  );
  await recordPrLinkActivity(id, actor, pr.number, pr.repoFullName);

  // Backlink is a courtesy: never fail the link because the comment failed.
  const fresh = (await getWorkItem(id)) ?? item;
  const backlink = await syncBacklinkComment(
    fresh,
    pr.repoFullName,
    pr.number,
    principal.githubToken,
  );

  return ok({ link, item: fresh, backlink }, 201);
});

/** DELETE /api/v1/items/{id}/links?linkId=N */
export const DELETE = withApi(async ({ request, params }) => {
  const id = parseId(params.id ?? '');
  const linkId = Number(new URL(request.url).searchParams.get('linkId'));
  if (!id || !Number.isInteger(linkId) || linkId <= 0) {
    return apiError('invalid_id', 'Both a work item id and a linkId are required.', 400);
  }
  const removed = await unlinkPullRequest(id, linkId);
  if (!removed) return apiError('not_found', 'That pull request link does not exist.', 404);
  return ok({ unlinked: linkId });
});
