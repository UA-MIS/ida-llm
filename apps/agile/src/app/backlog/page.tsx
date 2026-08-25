import Link from 'next/link';
import { requireSession } from '@/lib/auth/guard';
import { ensureSchema } from '@/lib/bootstrap';
import { listSprints, listWorkItems } from '@/lib/domain/queries';
import { parseSprintFilter } from '@/lib/domain/workitem';
import { Shell } from '@/components/Shell';
import { Assignee, PriorityChip, PrChip, StateBadge, TypeChip } from '@/components/chips';
import { toPlainText } from '@/lib/markdown';

export const dynamic = 'force-dynamic';

export default async function BacklogPage({
  searchParams,
}: {
  searchParams: Promise<{ sprint?: string; q?: string; assignee?: string }>;
}) {
  const session = await requireSession('/backlog');
  await ensureSchema();

  const sp = await searchParams;
  const [sprints, items] = await Promise.all([
    listSprints(),
    listWorkItems({
      search: sp.q,
      assignee: sp.assignee === 'mine' ? session.login : sp.assignee || undefined,
      sprintId: parseSprintFilter(sp.sprint),
    }),
  ]);

  const sprintName = new Map(sprints.map((s) => [s.id, s.name]));
  const totalPoints = items.reduce((sum, i) => sum + (i.storyPoints ?? 0), 0);

  return (
    <Shell session={session} active="backlog">
      <div className="page-head">
        <h1>Backlog</h1>
        <form className="toolbar" method="get">
          <select name="sprint" defaultValue={sp.sprint ?? 'all'} aria-label="Filter by sprint">
            <option value="all">All sprints</option>
            <option value="none">No sprint</option>
            {sprints.map((s) => (
              <option key={s.id} value={String(s.id)}>{s.name}</option>
            ))}
          </select>
          <select name="assignee" defaultValue={sp.assignee ?? ''} aria-label="Filter by assignee">
            <option value="">Everyone</option>
            <option value="mine">My items</option>
          </select>
          <input type="search" name="q" defaultValue={sp.q ?? ''} placeholder="Search…" aria-label="Search" />
          <button className="btn" type="submit">Filter</button>
        </form>
        <span className="spacer" />
        <span className="muted">
          {items.length} item{items.length === 1 ? '' : 's'}
          {totalPoints > 0 ? ` · ${totalPoints} points` : ''}
        </span>
      </div>

      <div className="panel">
        {items.length === 0 ? (
          <div className="empty">
            No work items match. <Link href="/board">Go to the board</Link> to create one.
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th style={{ width: 60 }}>ID</th>
                <th style={{ width: 90 }}>Type</th>
                <th>Title</th>
                <th style={{ width: 120 }}>State</th>
                <th style={{ width: 150 }}>Assignee</th>
                <th style={{ width: 130 }}>Sprint</th>
                <th style={{ width: 50 }}>Pts</th>
                <th style={{ width: 50 }}>Pri</th>
                <th style={{ width: 120 }}>PRs</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td className="mono muted">#{item.id}</td>
                  <td><TypeChip type={item.itemType} /></td>
                  <td>
                    <Link href={`/items/${item.id}`}>{item.title}</Link>
                    {item.description ? (
                      <div className="muted" style={{ fontSize: 12 }}>{toPlainText(item.description, 110)}</div>
                    ) : null}
                  </td>
                  <td><StateBadge state={item.state} /></td>
                  <td><Assignee login={item.assigneeLogin} avatarUrl={item.assigneeAvatarUrl} /></td>
                  <td className="muted">
                    {item.sprintId ? (sprintName.get(item.sprintId) ?? '—') : <span className="muted">—</span>}
                  </td>
                  <td>{item.storyPoints ?? <span className="muted">—</span>}</td>
                  <td><PriorityChip priority={item.priority} /></td>
                  <td>
                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                      {item.pullRequests.map((pr) => <PrChip key={pr.id} pr={pr} />)}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Shell>
  );
}
