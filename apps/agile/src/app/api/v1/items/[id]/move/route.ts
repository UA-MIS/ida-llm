import { z } from 'zod';
import { withApi } from '@/lib/api/route';
import { apiError, ok, parseId, readJson, validationError } from '@/lib/api/respond';
import { principalToActor } from '@/lib/auth/principal';
import { InvalidTransitionError, WORK_ITEM_STATES } from '@/lib/domain/workitem';
import { moveWorkItem } from '@/lib/domain/queries';

export const dynamic = 'force-dynamic';

const moveSchema = z.object({
  toState: z.enum(WORK_ITEM_STATES),
  /** Optional: the destination column's full ordered id list, for board ordering. */
  orderedIds: z.array(z.number().int().positive()).max(500).default([]),
});

/** POST /api/v1/items/{id}/move — transition state (and optionally reorder). */
export const POST = withApi(async ({ request, params, principal }) => {
  const id = parseId(params.id ?? '');
  if (!id) return apiError('invalid_id', 'Work item id must be a positive integer.', 400);

  const body = await readJson(request);
  if (!body.ok) return body.response;

  const parsed = moveSchema.safeParse(body.value);
  if (!parsed.success) return validationError(parsed.error);

  try {
    const item = await moveWorkItem(
      id,
      parsed.data.toState,
      parsed.data.orderedIds,
      principalToActor(principal),
    );
    if (!item) return apiError('not_found', `Work item #${id} does not exist.`, 404);
    return ok({ item });
  } catch (err) {
    if (err instanceof InvalidTransitionError) {
      return apiError('illegal_transition', err.message, 409);
    }
    throw err;
  }
});
