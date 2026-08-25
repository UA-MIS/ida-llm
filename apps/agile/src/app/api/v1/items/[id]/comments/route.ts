import { z } from 'zod';
import { withApi } from '@/lib/api/route';
import { apiError, ok, parseId, readJson, validationError } from '@/lib/api/respond';
import { addComment, getWorkItem, listComments } from '@/lib/domain/queries';

export const dynamic = 'force-dynamic';

const commentSchema = z.object({ body: z.string().trim().min(1).max(10_000) });

export const GET = withApi(async ({ params }) => {
  const id = parseId(params.id ?? '');
  if (!id) return apiError('invalid_id', 'Work item id must be a positive integer.', 400);
  return ok({ comments: await listComments(id) });
});

export const POST = withApi(async ({ request, params, principal }) => {
  const id = parseId(params.id ?? '');
  if (!id) return apiError('invalid_id', 'Work item id must be a positive integer.', 400);
  if (!(await getWorkItem(id))) return apiError('not_found', `Work item #${id} does not exist.`, 404);

  const body = await readJson(request);
  if (!body.ok) return body.response;
  const parsed = commentSchema.safeParse(body.value);
  if (!parsed.success) return validationError(parsed.error);

  const comment = await addComment(
    id,
    { login: principal.login, avatarUrl: principal.avatarUrl || null },
    parsed.data.body,
  );
  return ok({ comment }, 201);
});
