import { requireSession } from '@/lib/auth/guard';
import { ensureSchema } from '@/lib/bootstrap';
import { config } from '@/lib/env';
import { serverNow } from '@/lib/clock';
import { listSprints, listWorkItems } from '@/lib/domain/queries';
import { getCurrentSprint, readinessMap } from '@/lib/domain/deps-queries';
import { listTeamMembers } from '@/lib/github/client';
import { githubReadToken } from '@/lib/github/credential';
import { Shell } from '@/components/Shell';
import { Board } from '@/components/Board';

export const dynamic = 'force-dynamic';

export default async function BoardPage() {
  const session = await requireSession('/board');
  await ensureSchema();
  const ghToken = await githubReadToken({ githubToken: session.token || null });

  const [items, sprints, members, current, readiness] = await Promise.all([
    listWorkItems(),
    listSprints(),
    listTeamMembers(ghToken ?? ''),
    getCurrentSprint(),
    readinessMap(),
  ]);

  return (
    <Shell session={session} active="board">
      <Board
        initialItems={items.map((i) => ({
          ...i,
          readiness: readiness.get(i.id) ?? { ready: true, blockers: [], overridden: false },
        }))}
        sprints={sprints}
        members={members}
        currentUser={session.login}
        autoBranch={config.autoBranch}
        currentSprint={current}
        now={serverNow()}
        staleness={{ maxAgeDays: config.staleBranchDays, maxBehind: config.staleBranchBehind }}
      />
    </Shell>
  );
}
