import { z } from 'zod';
import { withApi } from '@/lib/api/route';
import { apiError, ok, readJson, validationError } from '@/lib/api/respond';
import { principalToActor } from '@/lib/auth/principal';
import { getCurrentSprint, setCurrentSprint } from '@/lib/domain/deps-queries';

export const dynamic = 'force-dynamic';

const schema = z.object({ sprintId: z.number().int().positive().nullable() });

/** GET — the board-wide current sprint, and who set it. */
export const GET = withApi(async () => ok(await getCurrentSprint()));

/**
 * PUT — set the board-wide current sprint.
 *
 * This is SHARED state: after this call every visitor lands on this sprint by
 * default. It is deliberately a separate, explicit action from browsing a
 * sprint, so a casual click cannot reassign the team's default.
 */
export const PUT = withApi(async ({ request, principal }) => {
  const body = await readJson(request);
  if (!body.ok) return body.response;
  const parsed = schema.safeParse(body.value);
  if (!parsed.success) return validationError(parsed.error);

  try {
    return ok(await setCurrentSprint(parsed.data.sprintId, principalToActor(principal)));
  } catch (err) {
    return apiError('invalid_sprint', (err as Error).message, 422);
  }
});
