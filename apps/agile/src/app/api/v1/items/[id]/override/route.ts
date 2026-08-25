import { z } from 'zod';
import { withApi } from '@/lib/api/route';
import { apiError, ok, parseId, readJson, validationError } from '@/lib/api/respond';
import { config } from '@/lib/env';
import { principalToActor } from '@/lib/auth/principal';
import { clearDependencyOverride, overrideDependencyGate, readinessFor } from '@/lib/domain/deps-queries';

export const dynamic = 'force-dynamic';

const schema = z.object({ reason: z.string().trim().min(3).max(500) });

/**
 * POST /api/v1/items/{id}/override — start work despite unmet dependencies.
 *
 * A hard block with no way through gets worked around outside the tool, so the
 * escape hatch exists — but it demands a reason and writes it to history.
 */
export const POST = withApi(async ({ request, params, principal }) => {
  const id = parseId(params.id ?? '');
  if (!id) return apiError('invalid_id', 'Work item id must be a positive integer.', 400);

  if (!config.allowDependencyOverride) {
    return apiError(
      'override_disabled',
      'Dependency overrides are disabled on this board (ALLOW_DEPENDENCY_OVERRIDE=false).',
      403,
    );
  }

  const body = await readJson(request);
  if (!body.ok) return body.response;
  const parsed = schema.safeParse(body.value);
  if (!parsed.success) return validationError(parsed.error);

  const done = await overrideDependencyGate(id, parsed.data.reason, principalToActor(principal));
  if (!done) return apiError('not_found', `Work item #${id} does not exist.`, 404);

  return ok({ readiness: await readinessFor(id) });
});

/** DELETE — withdraw the override and re-apply the gate. */
export const DELETE = withApi(async ({ params }) => {
  const id = parseId(params.id ?? '');
  if (!id) return apiError('invalid_id', 'Work item id must be a positive integer.', 400);
  await clearDependencyOverride(id);
  return ok({ readiness: await readinessFor(id) });
});
