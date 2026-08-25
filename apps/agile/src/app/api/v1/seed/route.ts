import { withApi } from '@/lib/api/route';
import { apiError, ok, readJson, validationError } from '@/lib/api/respond';
import { lookupIdempotent, saveIdempotent } from '@/lib/api/idempotency';
import { principalToActor } from '@/lib/auth/principal';
import { seedBoard, seedSchema, SeedError } from '@/lib/api/seed';

export const dynamic = 'force-dynamic';

/**
 * POST /api/v1/seed — create sprints, items and their dependency graph in ONE call.
 *
 * This is the "seed a semester" entry point: an agent writes the whole plan
 * top-to-bottom, referencing items and sprints by client-supplied keys, and
 * gets back the real ids. Honours `Idempotency-Key`.
 */
export const POST = withApi(async ({ request, principal }) => {
  const parsedBody = await readJson(request);
  if (!parsedBody.ok) return parsedBody.response;
  const body = parsedBody.value;

  const idemKey = request.headers.get('idempotency-key')?.trim();
  if (idemKey) {
    const found = await lookupIdempotent(idemKey, principal.login, body);
    if (found.kind === 'conflict') {
      return apiError(
        'idempotency_conflict',
        'This Idempotency-Key was already used with a different payload.',
        409,
      );
    }
    if (found.kind === 'replay') {
      return new Response(found.replay.body, {
        status: found.replay.status,
        headers: { 'content-type': 'application/json', 'idempotent-replay': 'true' },
      });
    }
  }

  const parsed = seedSchema.safeParse(body);
  if (!parsed.success) return validationError(parsed.error);

  try {
    const result = await seedBoard(parsed.data, principalToActor(principal));
    const payload = {
      sprints: result.sprints,
      items: result.items,
      counts: {
        sprints: result.sprints.length,
        items: result.items.length,
        dependencies: result.dependencies,
      },
      currentSprintId: result.currentSprintId,
    };
    if (idemKey) await saveIdempotent(idemKey, principal.login, body, 201, payload);
    return ok(payload, 201);
  } catch (err) {
    if (err instanceof SeedError) return apiError(err.code, err.message, 422);
    throw err;
  }
});
