import { withApi } from '@/lib/api/route';
import { apiError, ok, parseId, readJson, validationError } from '@/lib/api/respond';
import { sprintSchema } from '@/lib/domain/workitem';
import { deleteSprint, updateSprint } from '@/lib/domain/queries';

export const dynamic = 'force-dynamic';

export const PATCH = withApi(async ({ request, params }) => {
  const id = parseId(params.id ?? '');
  if (!id) return apiError('invalid_id', 'Sprint id must be a positive integer.', 400);

  const body = await readJson(request);
  if (!body.ok) return body.response;
  const parsed = sprintSchema.safeParse(body.value);
  if (!parsed.success) return validationError(parsed.error);

  const sprint = await updateSprint(id, parsed.data);
  if (!sprint) return apiError('not_found', `Sprint #${id} does not exist.`, 404);
  return ok({ sprint });
});

export const DELETE = withApi(async ({ params }) => {
  const id = parseId(params.id ?? '');
  if (!id) return apiError('invalid_id', 'Sprint id must be a positive integer.', 400);
  const removed = await deleteSprint(id);
  if (!removed) return apiError('not_found', `Sprint #${id} does not exist.`, 404);
  return ok({ deleted: id });
});
