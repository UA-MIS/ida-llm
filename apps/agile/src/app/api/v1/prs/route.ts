import { withApi } from '@/lib/api/route';
import { ok } from '@/lib/api/respond';
import { listLinkedPullRequests } from '@/lib/domain/queries';
import { groupLinkedPullRequests } from '@/lib/domain/board-prs';

export const dynamic = 'force-dynamic';

/**
 * GET /api/v1/prs — every pull request attached to a board item, open and
 * merged, one entry per PR, annotated with the items it belongs to.
 *
 * ── Board bug AB#29 ─────────────────────────────────────────────────────────
 * This route used to answer with GitHub's `state=open` PR list for the
 * configured repos. That was the wrong source twice over, and the board showed
 * it: `/summary` counted nine merged PRs while `/prs` returned `{"prs":[]}`.
 *
 *  - Wrong FILTER. `state=open` cannot return a merged PR, and merged PRs are
 *    exactly what this board treats as progress. Every PR the board cared about
 *    was excluded by construction.
 *  - Wrong JOIN. Nothing connected the result to `pull_request_links`, so a PR
 *    attached to an item was invisible unless GitHub also happened to have it
 *    open, and a PR attached to nothing was listed as though it were board work.
 *
 * Reading `pull_request_links` — the same table `boardSummary` reads — is what
 * makes the two agree by construction rather than by coincidence. Two useful
 * consequences follow: the endpoint no longer needs a GitHub credential (so it
 * cannot answer with an empty list because a token was missing or a call
 * failed), and it makes no outbound request at all, so viewing the board cannot
 * spend the org's GitHub rate budget.
 *
 * The GitHub-live open-PR list still exists for the one job it is right for:
 * the "attach a PR" picker on the item page, which must offer PRs that are NOT
 * yet attached. That is `listOpenPullRequests`, and it is deliberately still
 * separate from this endpoint.
 */
export const GET = withApi(async () => ok({ prs: groupLinkedPullRequests(await listLinkedPullRequests()) }));
