import { requireSession } from '@/lib/auth/guard';
import { ensureSchema } from '@/lib/bootstrap';
import { listSprints, sprintStats } from '@/lib/domain/queries';
import { Shell } from '@/components/Shell';
import { Sprints } from '@/components/Sprints';

export const dynamic = 'force-dynamic';

export default async function SprintsPage() {
  const session = await requireSession('/sprints');
  await ensureSchema();

  const sprints = await listSprints();
  const stats = await Promise.all(sprints.map((s) => sprintStats(s.id)));
  // Computed here rather than in the client component: reading the clock during
  // a React render is impure and risks a hydration mismatch.
  const today = new Date().toISOString().slice(0, 10);

  return (
    <Shell session={session} active="sprints">
      <Sprints initialSprints={sprints} initialStats={stats} today={today} />
    </Shell>
  );
}
