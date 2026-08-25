import { withApi } from '@/lib/api/route';
import { apiError, ok, parseId, readJson } from '@/lib/api/respond';
import { principalToActor } from '@/lib/auth/principal';
import { getWorkItem, updateWorkItem } from '@/lib/domain/queries';
import { readinessFor } from '@/lib/domain/deps-queries';
import { blockedMessage } from '@/lib/domain/dependencies';
import { startWork, checkoutCommand } from '@/lib/github/branches';
import { githubActionCredential } from '@/lib/github/credential';
import { canTransition, InvalidTransitionError } from '@/lib/domain/workitem';

export const dynamic = 'force-dynamic';

/**
 * POST /api/v1/items/{id}/start-work
 *
 * Moves the item to Active (when legal) and creates its branch.
 *
 * The two are deliberately decoupled: **the state transition is authoritative
 * and always applied first**, then the branch is attempted. If GitHub refuses,
 * the response is still 200 with `branch.status = "failed"` and a specific
 * message — a GitHub hiccup must never block the board.
 */
export const POST = withApi(async ({ request, params, principal }) => {
  const id = parseId(params.id ?? '');
  if (!id) return apiError('invalid_id', 'Work item id must be a positive integer.', 400);

  const parsed = await readJson(request).catch(() => ({ ok: true as const, value: {} }));
  const body = (parsed.ok ? parsed.value : {}) as { activate?: boolean; repo?: string };

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

  // 2. Branch second, and never fatally.
  const branch = await startWork(item, actor, githubActionCredential(principal), body.repo);
  if (branch.status === 'created' || branch.status === 'existing') item = branch.item;
  else warnings.push(branch.message);

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
