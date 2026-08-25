import { z } from 'zod';
import {
  createWorkItemSchema,
  sprintSchema,
  toActor,
  type ActorLike,
  type Sprint,
  type WorkItem,
} from '@/lib/domain/workitem';
import { createSprint, createWorkItem, getWorkItem } from '@/lib/domain/queries';
import { addDependency, setCurrentSprint } from '@/lib/domain/deps-queries';
import { findCycleInGraph } from '@/lib/domain/dependencies';

/**
 * One-call seeding of a whole semester: sprints, items, and the dependency
 * graph between them.
 *
 * Items reference each other by a **client-supplied `key`** rather than by id,
 * because the ids do not exist until the call runs. The same keys are used for
 * `sprintKey`, so a plan can be written top-to-bottom without a second
 * round trip. Keys are local to one request and are not persisted.
 */
const seedSprintSchema = sprintSchema.and(
  z.object({ key: z.string().trim().min(1).max(64) }),
);

const seedItemSchema = createWorkItemSchema.extend({
  /** Referenced by other items' `dependsOn`. */
  key: z.string().trim().min(1).max(64).optional(),
  /** A sprint `key` from this same request, instead of a numeric sprintId. */
  sprintKey: z.string().trim().min(1).max(64).optional(),
  /** Keys (or numeric ids of pre-existing items) this item is blocked by. */
  dependsOn: z.array(z.union([z.string(), z.number().int().positive()])).max(50).default([]),
})
  // Strict at the boundary, like every other request schema: a mistyped
  // `dependsOnn` in a 500-item seed must fail loudly, not vanish and leave the
  // dependency graph quietly wrong.
  .strict();

export const seedSchema = z.strictObject({
  sprints: z.array(seedSprintSchema).max(50).default([]),
  items: z.array(seedItemSchema).max(500).default([]),
  /** Optionally make one of the new sprints the board-wide current sprint. */
  currentSprintKey: z.string().trim().min(1).max(64).optional(),
});

export type SeedInput = z.input<typeof seedSchema>;

export interface SeedResult {
  sprints: Array<Sprint & { key: string }>;
  items: Array<WorkItem & { key?: string }>;
  dependencies: number;
  currentSprintId: number | null;
}

export class SeedError extends Error {
  constructor(
    message: string,
    readonly code: string,
  ) {
    super(message);
    this.name = 'SeedError';
  }
}

/**
 * Seeds in one transaction-per-stage so a malformed graph cannot leave a
 * half-built backlog: the dependency graph is validated for cycles BEFORE any
 * edge is written.
 */
export async function seedBoard(raw: SeedInput, actorLike: ActorLike): Promise<SeedResult> {
  const actor = toActor(actorLike);
  const input = seedSchema.parse(raw);

  // 1. Sprints first, so items can reference them by key.
  const sprintsByKey = new Map<string, Sprint>();
  const createdSprints: Array<Sprint & { key: string }> = [];
  for (const s of input.sprints) {
    if (sprintsByKey.has(s.key)) {
      throw new SeedError(`Duplicate sprint key "${s.key}".`, 'duplicate_key');
    }
    const sprint = await createSprint(s);
    sprintsByKey.set(s.key, sprint);
    createdSprints.push({ ...sprint, key: s.key });
  }

  // 2. Items, resolving sprintKey -> id.
  const itemsByKey = new Map<string, WorkItem>();
  const createdItems: Array<WorkItem & { key?: string }> = [];

  for (const item of input.items) {
    if (item.key && itemsByKey.has(item.key)) {
      throw new SeedError(`Duplicate item key "${item.key}".`, 'duplicate_key');
    }

    let sprintId = item.sprintId ?? null;
    if (item.sprintKey) {
      const sprint = sprintsByKey.get(item.sprintKey);
      if (!sprint) {
        throw new SeedError(
          `Item "${item.title}" references sprintKey "${item.sprintKey}", which is not in this request.`,
          'unknown_sprint_key',
        );
      }
      sprintId = sprint.id;
    }

    const created = await createWorkItem({ ...item, sprintId }, actor);
    if (item.key) itemsByKey.set(item.key, created);
    createdItems.push(item.key ? { ...created, key: item.key } : created);
  }

  // 3. Resolve every dependency edge to real ids, then validate the WHOLE graph
  //    for cycles before writing any of it.
  const edges: Array<[number, number]> = [];
  for (let i = 0; i < input.items.length; i++) {
    const spec = input.items[i]!;
    const created = createdItems[i]!;
    for (const ref of spec.dependsOn) {
      let blockerId: number;
      if (typeof ref === 'number') {
        if (!(await getWorkItem(ref))) {
          throw new SeedError(
            `Item "${spec.title}" depends on #${ref}, which does not exist on this board.`,
            'unknown_dependency',
          );
        }
        blockerId = ref;
      } else {
        const target = itemsByKey.get(ref);
        if (!target) {
          throw new SeedError(
            `Item "${spec.title}" depends on key "${ref}", which is not defined in this request. ` +
              'Use a key from this payload, or a numeric id of an existing item.',
            'unknown_dependency',
          );
        }
        blockerId = target.id;
      }
      edges.push([created.id, blockerId]);
    }
  }

  const cycle = findCycleInGraph(edges);
  if (cycle) {
    throw new SeedError(
      `The dependency graph contains a cycle: ${cycle.map((id) => `#${id}`).join(' → ')}.`,
      'dependency_cycle',
    );
  }

  for (const [itemId, blockerId] of edges) {
    await addDependency(itemId, blockerId, actor);
  }

  // 4. Optionally set the shared current sprint.
  let currentSprintId: number | null = null;
  if (input.currentSprintKey) {
    const sprint = sprintsByKey.get(input.currentSprintKey);
    if (!sprint) {
      throw new SeedError(
        `currentSprintKey "${input.currentSprintKey}" is not one of the sprints in this request.`,
        'unknown_sprint_key',
      );
    }
    await setCurrentSprint(sprint.id, actor);
    currentSprintId = sprint.id;
  }

  return {
    sprints: createdSprints,
    items: createdItems,
    dependencies: edges.length,
    currentSprintId,
  };
}
