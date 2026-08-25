import { requireSession } from '@/lib/auth/guard';
import { ensureSchema } from '@/lib/bootstrap';
import { config } from '@/lib/env';
import { listSprints, listWorkItems } from '@/lib/domain/queries';
import { listTeamMembers } from '@/lib/github/client';
import { Shell } from '@/components/Shell';
import { Board } from '@/components/Board';

export const dynamic = 'force-dynamic';

export default async function BoardPage() {
  const session = await requireSession('/board');
  await ensureSchema();

  const [items, sprints, members] = await Promise.all([
    listWorkItems(),
    listSprints(),
    listTeamMembers(session.token),
  ]);

  return (
    <Shell session={session} active="board">
      <Board
        initialItems={items}
        sprints={sprints}
        members={members}
        currentUser={session.login}
        autoBranch={config.autoBranch}
      />
    </Shell>
  );
}
