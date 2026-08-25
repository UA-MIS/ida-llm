import { requireSession } from '@/lib/auth/guard';
import { ensureSchema } from '@/lib/bootstrap';
import { listSprints, listWorkItems } from '@/lib/domain/queries';
import { readinessMap } from '@/lib/domain/deps-queries';
import { Shell } from '@/components/Shell';
import { Ready } from '@/components/Ready';

export const dynamic = 'force-dynamic';

export default async function ReadyPage() {
  const session = await requireSession('/ready');
  await ensureSchema();

  const [items, sprints, readiness] = await Promise.all([
    listWorkItems({ state: 'New' }),
    listSprints(),
    readinessMap(),
  ]);

  const unassigned = items.filter((i) => i.assigneeLogin === null);
  const ready = unassigned
    .filter((i) => readiness.get(i.id)?.ready !== false)
    .map((i) => ({ ...i, readiness: readiness.get(i.id) }));
  const blocked = unassigned
    .filter((i) => readiness.get(i.id)?.ready === false)
    .map((i) => ({ id: i.id, title: i.title, blockers: readiness.get(i.id)!.blockers }));

  return (
    <Shell session={session} active="ready">
      <Ready initialReady={ready} blocked={blocked} sprints={sprints} currentUser={session.login} />
    </Shell>
  );
}
