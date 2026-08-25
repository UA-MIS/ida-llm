import type { WorkItemState } from './workitem';

/**
 * Dependency rules.
 *
 * Pure functions over a graph, so cycle detection and gating are directly
 * testable without a database and behave identically in the UI, the API and
 * the bulk-seed path.
 */

/** A dependency is satisfied once the blocker is finished. */
export function isSatisfied(state: WorkItemState): boolean {
  return state === 'Resolved' || state === 'Closed';
}

export interface BlockerRef {
  id: number;
  title: string;
  state: WorkItemState;
}

export interface Readiness {
  ready: boolean;
  blockers: BlockerRef[];
  /** True when the gate is only open because someone explicitly overrode it. */
  overridden: boolean;
}

export function evaluateReadiness(
  blockers: BlockerRef[],
  override?: { by: string | null } | null,
): Readiness {
  const unmet = blockers.filter((b) => !isSatisfied(b.state));
  if (unmet.length === 0) return { ready: true, blockers: [], overridden: false };
  if (override?.by) return { ready: true, blockers: unmet, overridden: true };
  return { ready: false, blockers: unmet, overridden: false };
}

/** Human-readable reason a control is disabled, naming the actual blockers. */
export function blockedMessage(blockers: BlockerRef[]): string {
  if (blockers.length === 0) return '';
  const list = blockers.map((b) => `#${b.id} ${b.title}`).join(', ');
  return `Blocked by ${list}`;
}

export class DependencyCycleError extends Error {
  constructor(readonly cycle: number[]) {
    super(
      `That dependency would create a cycle: ${cycle.map((id) => `#${id}`).join(' → ')}. ` +
        'Work items cannot depend on each other in a loop.',
    );
    this.name = 'DependencyCycleError';
  }
}

export type DependencyGraph = Map<number, number[]>;

/**
 * Finds the cycle that adding `item -> dependsOn` would create, or null.
 *
 * `graph` maps an item to the items it already depends on. A cycle exists iff
 * `dependsOn` can already reach `item`; the returned path is the actual loop,
 * so the error can name it rather than saying "cycle detected".
 */
export function findCycle(
  graph: DependencyGraph,
  item: number,
  dependsOn: number,
): number[] | null {
  if (item === dependsOn) return [item, item];

  // Depth-first search from dependsOn looking for item, tracking the path.
  const stack: Array<{ node: number; path: number[] }> = [{ node: dependsOn, path: [dependsOn] }];
  const seen = new Set<number>();

  while (stack.length) {
    const { node, path } = stack.pop()!;
    if (node === item) return [item, ...path];
    if (seen.has(node)) continue;
    seen.add(node);

    for (const next of graph.get(node) ?? []) {
      stack.push({ node: next, path: [...path, next] });
    }
  }
  return null;
}

export function assertNoCycle(graph: DependencyGraph, item: number, dependsOn: number): void {
  const cycle = findCycle(graph, item, dependsOn);
  if (cycle) throw new DependencyCycleError(cycle);
}

/**
 * Validates a whole proposed graph at once — used by bulk seeding, where the
 * edges arrive together and must be checked as a set rather than one at a time.
 */
export function findCycleInGraph(edges: Array<[number, number]>): number[] | null {
  const graph: DependencyGraph = new Map();
  for (const [item, dep] of edges) {
    if (item === dep) return [item, item];
    graph.set(item, [...(graph.get(item) ?? []), dep]);
  }

  const WHITE = 0, GREY = 1, BLACK = 2;
  const colour = new Map<number, number>();
  const parent = new Map<number, number>();

  function visit(node: number): number[] | null {
    colour.set(node, GREY);
    for (const next of graph.get(node) ?? []) {
      const c = colour.get(next) ?? WHITE;
      if (c === GREY) {
        // Reconstruct the loop from the back edge.
        const cycle = [next];
        let cur = node;
        while (cur !== next && cur !== undefined) {
          cycle.push(cur);
          cur = parent.get(cur)!;
        }
        cycle.push(next);
        return cycle.reverse();
      }
      if (c === WHITE) {
        parent.set(next, node);
        const found = visit(next);
        if (found) return found;
      }
    }
    colour.set(node, BLACK);
    return null;
  }

  for (const node of graph.keys()) {
    if ((colour.get(node) ?? WHITE) === WHITE) {
      const found = visit(node);
      if (found) return found;
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Trunk-based signals
// ---------------------------------------------------------------------------

/**
 * Staleness of a board-created branch.
 *
 * The delivery model is trunk-based, so a board branch is short-lived by
 * definition. Commits are *activity*, never progress — progress is a merged
 * PR. This signal exists so the board nudges toward trunk-based habits instead
 * of quietly hosting a long-lived branch.
 */
export interface StalenessConfig {
  maxAgeDays: number;
  maxBehind: number;
}

export interface Staleness {
  stale: boolean;
  ageDays: number;
  behindBy: number | null;
  reason: string;
}

export function evaluateStaleness(
  branchCreatedAt: string | null,
  behindBy: number | null,
  now: number,
  config: StalenessConfig,
): Staleness {
  if (!branchCreatedAt) {
    return { stale: false, ageDays: 0, behindBy, reason: '' };
  }

  const created = Date.parse(branchCreatedAt);
  const ageDays = Number.isNaN(created) ? 0 : Math.floor((now - created) / 86_400_000);

  const tooOld = config.maxAgeDays > 0 && ageDays >= config.maxAgeDays;
  const tooFarBehind = config.maxBehind > 0 && (behindBy ?? 0) >= config.maxBehind;

  if (!tooOld && !tooFarBehind) {
    return { stale: false, ageDays, behindBy, reason: '' };
  }

  const parts: string[] = [];
  if (tooOld) parts.push(`${ageDays} day${ageDays === 1 ? '' : 's'} old`);
  if (tooFarBehind) parts.push(`${behindBy} behind main`);
  return { stale: true, ageDays, behindBy, reason: `branch stale — ${parts.join(', ')}` };
}
