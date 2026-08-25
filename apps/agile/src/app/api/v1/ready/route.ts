import { withApi } from '@/lib/api/route';
import { ok } from '@/lib/api/respond';
import { listWorkItems } from '@/lib/domain/queries';
import { readinessMap } from '@/lib/domain/deps-queries';

export const dynamic = 'force-dynamic';

/**
 * GET /api/v1/ready — the self-serve pickup queue.
 *
 * Items whose dependencies are ALL satisfied and that nobody has taken.
 * Filterable by `wave` and `sprintId` so a team can pull from the current band.
 */
export const GET = withApi(async ({ request }) => {
  const sp = new URL(request.url).searchParams;
  const sprintParam = sp.get('sprintId');
  const wave = sp.get('wave');

  const [items, readiness] = await Promise.all([
    listWorkItems({
      state: 'New',
      sprintId:
        sprintParam === null || sprintParam === '' || sprintParam === 'all'
          ? undefined
          : sprintParam === 'none'
            ? null
            : Number(sprintParam),
    }),
    readinessMap(),
  ]);

  const ready = items
    .filter((i) => i.assigneeLogin === null)
    .filter((i) => !wave || i.wave === wave)
    .filter((i) => readiness.get(i.id)?.ready !== false)
    .map((i) => ({ ...i, readiness: readiness.get(i.id) ?? { ready: true, blockers: [], overridden: false } }));

  const blocked = items
    .filter((i) => readiness.get(i.id)?.ready === false)
    .map((i) => ({ id: i.id, title: i.title, blockers: readiness.get(i.id)!.blockers }));

  return ok({ ready, count: ready.length, blocked });
});
