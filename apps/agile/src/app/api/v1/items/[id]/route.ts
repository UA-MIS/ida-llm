import { withApi } from '@/lib/api/route';
import { apiError, ok, parseId, readJson, validationError } from '@/lib/api/respond';
import { principalToActor } from '@/lib/auth/principal';
import { updateWorkItemSchema, InvalidTransitionError } from '@/lib/domain/workitem';
import {
  deleteWorkItem,
  getWorkItem,
  listActivity,
  listAttachments,
  listComments,
  updateWorkItem,
} from '@/lib/domain/queries';

export const dynamic = 'force-dynamic';

/** GET /api/v1/items/{id} — the item plus its comments, history and attachments. */
export const GET = withApi(async ({ params }) => {
  const id = parseId(params.id ?? '');
  if (!id) return apiError('invalid_id', 'Work item id must be a positive integer.', 400);

  const item = await getWorkItem(id);
  if (!item) return apiError('not_found', `Work item #${id} does not exist.`, 404);

  const [comments, activity, attachments] = await Promise.all([
    listComments(id),
    listActivity(id),
    listAttachments(id),
  ]);
  return ok({ item, comments, activity, attachments });
});

/** PATCH /api/v1/items/{id} — partial update. Illegal state moves return 409. */
export const PATCH = withApi(async ({ request, params, principal }) => {
  const id = parseId(params.id ?? '');
  if (!id) return apiError('invalid_id', 'Work item id must be a positive integer.', 400);

  const body = await readJson(request);
  if (!body.ok) return body.response;

  const parsed = updateWorkItemSchema.safeParse(body.value);
  if (!parsed.success) return validationError(parsed.error);

  try {
    const item = await updateWorkItem(id, parsed.data, principalToActor(principal));
    if (!item) return apiError('not_found', `Work item #${id} does not exist.`, 404);
    return ok({ item });
  } catch (err) {
    if (err instanceof InvalidTransitionError) {
      return apiError('illegal_transition', err.message, 409);
    }
    throw err;
  }
});

/** DELETE /api/v1/items/{id} — permanent. Prefer state "Removed" to keep history. */
export const DELETE = withApi(async ({ params }) => {
  const id = parseId(params.id ?? '');
  if (!id) return apiError('invalid_id', 'Work item id must be a positive integer.', 400);
  const removed = await deleteWorkItem(id);
  if (!removed) return apiError('not_found', `Work item #${id} does not exist.`, 404);
  return ok({ deleted: id });
});
