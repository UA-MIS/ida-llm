import { withApi } from '@/lib/api/route';
import { apiError, ok, readJson, validationError } from '@/lib/api/respond';
import { sprintSchema } from '@/lib/domain/workitem';
import { createSprint, listSprints, sprintStats } from '@/lib/domain/queries';

export const dynamic = 'force-dynamic';

export const GET = withApi(async () => {
  const sprints = await listSprints();
  const stats = await Promise.all(sprints.map((s) => sprintStats(s.id)));
  return ok({ sprints, stats });
});

export const POST = withApi(async ({ request }) => {
  const body = await readJson(request);
  if (!body.ok) return body.response;
  const parsed = sprintSchema.safeParse(body.value);
  if (!parsed.success) return validationError(parsed.error);

  try {
    return ok({ sprint: await createSprint(parsed.data) }, 201);
  } catch (err) {
    if ((err as { code?: string }).code === '23505') {
      return apiError('duplicate_sprint', 'A sprint with that name already exists.', 409);
    }
    throw err;
  }
});
