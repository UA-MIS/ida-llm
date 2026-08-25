import { withApi } from '@/lib/api/route';
import { apiError, ok, parseId, readJson, validationError } from '@/lib/api/respond';
import { principalToActor } from '@/lib/auth/principal';
import { getWorkItem, updateWorkItem } from '@/lib/domain/queries';
import { readinessFor } from '@/lib/domain/deps-queries';
import { blockedMessage } from '@/lib/domain/dependencies';
import { startWork, checkoutCommand, type StartWorkOutcome } from '@/lib/github/branches';
import { githubActionCredential } from '@/lib/github/credential';
import {
  canTransition,
  shouldCreateBranch,
  startWorkSchema,
  InvalidTransitionError,
} from '@/lib/domain/workitem';

export const dynamic = 'force-dynamic';

/** The branch was not attempted, and that is the correct outcome — not a failure. */
type SkippedBranch = { status: 'skipped'; message: string };

/**
 * POST /api/v1/items/{id}/start-work
 *
 * Moves the item to Active (when legal), assigns it, and — for the types whose
 * work lives in git — creates its branch.
 *
 * Two decouplings matter here:
 *
 *  - **State vs. branch.** The state transition is authoritative and always
 *    applied first, then the branch is attempted. If GitHub refuses, the
 *    response is still 200 with `branch.status = "failed"` and a specific
 *    message — a GitHub hiccup must never block the board.
 *  - **Starting vs. branching.** Starting a Spike or a Task is a real, complete
 *    action: the item goes Active and gets an owner, and NO branch is created.
 *    Only Story and Bug branch by default (see `BRANCHING_ITEM_TYPES`). Before
 *    this, every type branched, so a research spike was handed a `spike/25-...`
 *    ref it could never use (AB#25). `{"branch": true|false}` overrides the
 *    default in either direction for the case that needs it.
 */
export const POST = withApi(async ({ request, params, principal }) => {
  const id = parseId(params.id ?? '');
  if (!id) return apiError('invalid_id', 'Work item id must be a positive integer.', 400);

  // An absent or unparseable body is the common case (the UI sends `{}`), so it
  // degrades to "no options"; a body that IS present is validated strictly.
  const raw = await readJson(request).catch(() => ({ ok: true as const, value: {} }));
  const parsedBody = startWorkSchema.safeParse(raw.ok ? (raw.value ?? {}) : {});
  if (!parsedBody.success) return validationError(parsedBody.error);
  const body = parsedBody.data;

  let item = await getWorkItem(id);
  if (!item) return apiError('not_found', `Work item #${id} does not exist.`, 404);

  const actor = principalToActor(principal);
  const warnings: string[] = [];

  // 0. Dependency gate. Blocked work cannot be started, and the refusal names
  //    the specific blockers so the caller knows what to chase.
  const readiness = await readinessFor(id);
  if (!readiness.ready) {
    return Response.json(
      {
        error: {
          code: 'blocked_by_dependencies',
          message: `${blockedMessage(readiness.blockers)}. Resolve them, or override with a reason via POST /api/v1/items/${id}/override.`,
          blockers: readiness.blockers,
        },
      },
      { status: 409 },
    );
  }
  if (readiness.overridden) {
    warnings.push(
      `Started despite ${readiness.blockers.length} unmet dependency/dependencies (override recorded).`,
    );
  }

  // 1. State first — this is the part that must not be lost.
  const shouldActivate = body.activate !== false && item.state === 'New';
  if (shouldActivate && canTransition(item.state, 'Active')) {
    try {
      const moved = await updateWorkItem(id, { state: 'Active' }, actor);
      if (moved) item = moved;
    } catch (err) {
      if (!(err instanceof InvalidTransitionError)) throw err;
      warnings.push(err.message);
    }
  }

  // 1b. Assignment. Starting work means taking it; an item that already has an
  //     owner keeps them, and `{"assign": false}` opts out entirely for the
  //     lead who is starting a card on someone else's behalf.
  if (body.assign !== false && !item.assigneeLogin && actor.login) {
    const claimed = await updateWorkItem(id, { assigneeLogin: actor.login }, actor);
    if (claimed) item = claimed;
  }

  // 2. Branch second, never fatally, and only when this type branches at all.
  const branch: StartWorkOutcome | SkippedBranch = shouldCreateBranch(item.itemType, body.branch)
    ? await startWork(item, actor, await githubActionCredential(principal), body.repo)
    : {
        status: 'skipped',
        message:
          `${item.itemType} items do not use a branch, so none was created. ` +
          'Pass {"branch": true} if this one needs a scratch branch anyway.',
      };

  if (branch.status === 'created' || branch.status === 'existing') item = branch.item;
  // "skipped" is the designed outcome for a non-code item, not a degradation,
  // so it is deliberately NOT a warning.
  else if (branch.status !== 'skipped') warnings.push(branch.message);

  return ok({
    item,
    branch:
      branch.status === 'created' || branch.status === 'existing'
        ? {
            status: branch.status,
            name: branch.branch,
            url: branch.url,
            checkout: checkoutCommand(branch.branch),
          }
        : { status: branch.status, message: branch.message },
    warnings,
  });
});
