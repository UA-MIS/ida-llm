import { query, queryOne, withTransaction } from '@/lib/db/pool';
import { config } from '@/lib/env';
import {
  assertNoCycle,
  evaluateReadiness,
  type BlockerRef,
  type DependencyGraph,
  type Readiness,
} from './dependencies';
import { toActor, type ActorLike, type WorkItemState } from './workitem';

/**
 * Dependency edges, readiness, and the shared current-sprint pointer.
 */

export interface DependencyEdge {
  itemId: number;
  dependsOnId: number;
  title: string;
  state: WorkItemState;
}

/** The whole graph for this board, used for cycle checks. */
export async function loadDependencyGraph(): Promise<DependencyGraph> {
  const rows = await query<{ item_id: number; depends_on_id: number }>(
    `SELECT d.item_id, d.depends_on_id
       FROM work_item_dependencies d
       JOIN work_items wi ON wi.id = d.item_id
      WHERE wi.instance_key = $1`,
    [config.instanceKey],
  );
  const graph: DependencyGraph = new Map();
  for (const r of rows) {
    graph.set(r.item_id, [...(graph.get(r.item_id) ?? []), r.depends_on_id]);
  }
  return graph;
}

export async function listBlockers(itemId: number): Promise<BlockerRef[]> {
  const rows = await query<{ id: number; title: string; state: string }>(
    `SELECT wi.id, wi.title, wi.state
       FROM work_item_dependencies d
       JOIN work_items wi ON wi.id = d.depends_on_id
      WHERE d.item_id = $1
      ORDER BY wi.id`,
    [itemId],
  );
  return rows.map((r) => ({ id: r.id, title: r.title, state: r.state as WorkItemState }));
}

/** Items that this item is blocking (the reverse edge). */
export async function listBlocking(itemId: number): Promise<BlockerRef[]> {
  const rows = await query<{ id: number; title: string; state: string }>(
    `SELECT wi.id, wi.title, wi.state
       FROM work_item_dependencies d
       JOIN work_items wi ON wi.id = d.item_id
      WHERE d.depends_on_id = $1
      ORDER BY wi.id`,
    [itemId],
  );
  return rows.map((r) => ({ id: r.id, title: r.title, state: r.state as WorkItemState }));
}

export async function readinessFor(itemId: number): Promise<Readiness> {
  const [blockers, override] = await Promise.all([
    listBlockers(itemId),
    queryOne<{ dep_override_by: string | null }>(
      'SELECT dep_override_by FROM work_items WHERE id = $1 AND instance_key = $2',
      [itemId, config.instanceKey],
    ),
  ]);
  return evaluateReadiness(blockers, override ? { by: override.dep_override_by } : null);
}

/**
 * Adds an edge, rejecting anything that would create a cycle.
 * The cycle check runs inside the transaction against the live graph.
 */
export async function addDependency(
  itemId: number,
  dependsOnId: number,
  actorLike: ActorLike,
): Promise<void> {
  const actor = toActor(actorLike);
  await withTransaction(async (client) => {
    const { rows: exists } = await client.query<{ id: number }>(
      'SELECT id FROM work_items WHERE id = ANY($1::int[]) AND instance_key = $2',
      [[itemId, dependsOnId], config.instanceKey],
    );
    if (exists.length !== 2) {
      throw new Error(`Both work items must exist on this board (#${itemId}, #${dependsOnId}).`);
    }

    const graph = await loadDependencyGraph();
    assertNoCycle(graph, itemId, dependsOnId);

    await client.query(
      `INSERT INTO work_item_dependencies (item_id, depends_on_id, created_by)
       VALUES ($1,$2,$3) ON CONFLICT DO NOTHING`,
      [itemId, dependsOnId, actor.login],
    );
    await client.query(
      `INSERT INTO activity (item_id, actor_login, source, field, old_value, new_value, note)
       VALUES ($1,$2,$3,'depends_on',NULL,$4,$5)`,
      [itemId, actor.login, actor.source, `#${dependsOnId}`, actor.note ?? null],
    );
  });
}

export async function removeDependency(
  itemId: number,
  dependsOnId: number,
  actorLike: ActorLike,
): Promise<boolean> {
  const actor = toActor(actorLike);
  const rows = await query<{ item_id: number }>(
    'DELETE FROM work_item_dependencies WHERE item_id = $1 AND depends_on_id = $2 RETURNING item_id',
    [itemId, dependsOnId],
  );
  if (rows.length) {
    await query(
      `INSERT INTO activity (item_id, actor_login, source, field, old_value, new_value)
       VALUES ($1,$2,$3,'depends_on',$4,NULL)`,
      [itemId, actor.login, actor.source, `#${dependsOnId}`],
    );
  }
  return rows.length > 0;
}

/** Records an explicit, reasoned override of the dependency gate. */
export async function overrideDependencyGate(
  itemId: number,
  reason: string,
  actorLike: ActorLike,
): Promise<boolean> {
  const actor = toActor(actorLike);
  const rows = await query<{ id: number }>(
    `UPDATE work_items
        SET dep_override_by = $1, dep_override_reason = $2, dep_override_at = now()
      WHERE id = $3 AND instance_key = $4
      RETURNING id`,
    [actor.login, reason, itemId, config.instanceKey],
  );
  if (!rows.length) return false;

  await query(
    `INSERT INTO activity (item_id, actor_login, source, field, old_value, new_value, note)
     VALUES ($1,$2,$3,'dependency_override',NULL,'started anyway',$4)`,
    [itemId, actor.login, actor.source, reason],
  );
  return true;
}

export async function clearDependencyOverride(itemId: number): Promise<void> {
  await query(
    `UPDATE work_items SET dep_override_by = NULL, dep_override_reason = NULL, dep_override_at = NULL
      WHERE id = $1 AND instance_key = $2`,
    [itemId, config.instanceKey],
  );
}

/**
 * Readiness for many items in one round trip — the board renders every card's
 * gate state, so this must not be N queries.
 */
export async function readinessMap(): Promise<Map<number, Readiness>> {
  const rows = await query<{
    item_id: number;
    blocker_id: number | null;
    blocker_title: string | null;
    blocker_state: string | null;
    override_by: string | null;
  }>(
    `SELECT wi.id                AS item_id,
            b.id                 AS blocker_id,
            b.title              AS blocker_title,
            b.state              AS blocker_state,
            wi.dep_override_by   AS override_by
       FROM work_items wi
       LEFT JOIN work_item_dependencies d ON d.item_id = wi.id
       LEFT JOIN work_items b ON b.id = d.depends_on_id
      WHERE wi.instance_key = $1`,
    [config.instanceKey],
  );

  const blockersByItem = new Map<number, BlockerRef[]>();
  const overrideByItem = new Map<number, string | null>();

  for (const r of rows) {
    overrideByItem.set(r.item_id, r.override_by);
    if (r.blocker_id !== null) {
      blockersByItem.set(r.item_id, [
        ...(blockersByItem.get(r.item_id) ?? []),
        { id: r.blocker_id, title: r.blocker_title ?? '', state: r.blocker_state as WorkItemState },
      ]);
    }
  }

  const out = new Map<number, Readiness>();
  for (const [itemId, override] of overrideByItem) {
    out.set(
      itemId,
      evaluateReadiness(blockersByItem.get(itemId) ?? [], override ? { by: override } : null),
    );
  }
  return out;
}

// ---------------------------------------------------------------------------
// Shared current sprint
// ---------------------------------------------------------------------------

export interface CurrentSprint {
  sprintId: number | null;
  setBy: string | null;
  setAt: string | null;
}

export async function getCurrentSprint(): Promise<CurrentSprint> {
  const row = await queryOne<{
    current_sprint_id: number | null;
    current_sprint_set_by: string | null;
    current_sprint_set_at: Date | null;
  }>(
    `SELECT current_sprint_id, current_sprint_set_by, current_sprint_set_at
       FROM board_settings WHERE instance_key = $1`,
    [config.instanceKey],
  );
  return {
    sprintId: row?.current_sprint_id ?? null,
    setBy: row?.current_sprint_set_by ?? null,
    setAt: row?.current_sprint_set_at ? row.current_sprint_set_at.toISOString() : null,
  };
}

/**
 * Sets the board-wide current sprint.
 *
 * This is SHARED state, not a personal preference: after this call every
 * visitor lands on this sprint. Who did it and when is recorded so the change
 * is attributable.
 */
export async function setCurrentSprint(
  sprintId: number | null,
  actorLike: ActorLike,
): Promise<CurrentSprint> {
  const actor = toActor(actorLike);

  if (sprintId !== null) {
    const sprint = await queryOne<{ id: number }>(
      'SELECT id FROM sprints WHERE id = $1 AND instance_key = $2',
      [sprintId, config.instanceKey],
    );
    if (!sprint) throw new Error(`Sprint #${sprintId} does not exist on this board.`);
  }

  await query(
    `INSERT INTO board_settings (instance_key, current_sprint_id, current_sprint_set_by, current_sprint_set_at)
     VALUES ($1,$2,$3, now())
     ON CONFLICT (instance_key) DO UPDATE
       SET current_sprint_id = EXCLUDED.current_sprint_id,
           current_sprint_set_by = EXCLUDED.current_sprint_set_by,
           current_sprint_set_at = now()`,
    [config.instanceKey, sprintId, actor.login],
  );

  return getCurrentSprint();
}
