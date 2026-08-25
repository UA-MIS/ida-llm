import { z } from 'zod';
import { withApi } from '@/lib/api/route';
import { apiError, ok, parseId, readJson, validationError } from '@/lib/api/respond';
import { principalToActor } from '@/lib/auth/principal';
import {
  addDependency,
  listBlockers,
  listBlocking,
  readinessFor,
  removeDependency,
} from '@/lib/domain/deps-queries';
import { DependencyCycleError } from '@/lib/domain/dependencies';

export const dynamic = 'force-dynamic';

const addSchema = z.object({ dependsOn: z.number().int().positive() });

/** GET — what blocks this item, what it blocks, and whether it is ready. */
export const GET = withApi(async ({ params }) => {
  const id = parseId(params.id ?? '');
  if (!id) return apiError('invalid_id', 'Work item id must be a positive integer.', 400);

  const [blockedBy, blocking, readiness] = await Promise.all([
    listBlockers(id),
    listBlocking(id),
    readinessFor(id),
  ]);
  return ok({ blockedBy, blocking, readiness });
});

/** POST — declare that this item is blocked by another. Cycles are rejected. */
export const POST = withApi(async ({ request, params, principal }) => {
  const id = parseId(params.id ?? '');
  if (!id) return apiError('invalid_id', 'Work item id must be a positive integer.', 400);

  const body = await readJson(request);
  if (!body.ok) return body.response;
  const parsed = addSchema.safeParse(body.value);
  if (!parsed.success) return validationError(parsed.error);

  try {
    await addDependency(id, parsed.data.dependsOn, principalToActor(principal));
  } catch (err) {
    if (err instanceof DependencyCycleError) {
      return apiError('dependency_cycle', err.message, 409);
    }
    return apiError('invalid_dependency', (err as Error).message, 422);
  }

  return ok({ readiness: await readinessFor(id) }, 201);
});

/** DELETE /api/v1/items/{id}/dependencies?dependsOn=N */
export const DELETE = withApi(async ({ request, params, principal }) => {
  const id = parseId(params.id ?? '');
  const dependsOn = Number(new URL(request.url).searchParams.get('dependsOn'));
  if (!id || !Number.isInteger(dependsOn) || dependsOn <= 0) {
    return apiError('invalid_id', 'Both an item id and dependsOn are required.', 400);
  }

  const removed = await removeDependency(id, dependsOn, principalToActor(principal));
  if (!removed) return apiError('not_found', 'That dependency does not exist.', 404);
  return ok({ readiness: await readinessFor(id) });
});
