import { describe, it, expect } from 'vitest';
import {
  assertNoCycle,
  blockedMessage,
  DependencyCycleError,
  evaluateReadiness,
  evaluateStaleness,
  findCycle,
  findCycleInGraph,
  isSatisfied,
  type DependencyGraph,
} from '@/lib/domain/dependencies';
import type { WorkItemState } from '@/lib/domain/workitem';

const graph = (edges: Record<number, number[]>): DependencyGraph =>
  new Map(Object.entries(edges).map(([k, v]) => [Number(k), v]));

const blocker = (id: number, state: WorkItemState) => ({ id, title: `Item ${id}`, state });

describe('dependency satisfaction', () => {
  it('counts only finished work as satisfying a dependency', () => {
    expect(isSatisfied('Resolved')).toBe(true);
    expect(isSatisfied('Closed')).toBe(true);
    expect(isSatisfied('New')).toBe(false);
    expect(isSatisfied('Active')).toBe(false);
    expect(isSatisfied('Removed')).toBe(false);
  });
});

describe('readiness gate', () => {
  it('is ready with no dependencies at all', () => {
    expect(evaluateReadiness([])).toEqual({ ready: true, blockers: [], overridden: false });
  });

  it('is ready when every dependency is finished', () => {
    const r = evaluateReadiness([blocker(1, 'Resolved'), blocker(2, 'Closed')]);
    expect(r.ready).toBe(true);
    expect(r.blockers).toEqual([]);
  });

  it('is BLOCKED while any dependency is unfinished, and names it', () => {
    const r = evaluateReadiness([blocker(1, 'Closed'), blocker(2, 'Active')]);
    expect(r.ready).toBe(false);
    expect(r.blockers.map((b) => b.id)).toEqual([2]);
    expect(r.overridden).toBe(false);
  });

  it('opens the gate when the LAST blocker finishes', () => {
    const before = evaluateReadiness([blocker(1, 'Active')]);
    expect(before.ready).toBe(false);
    const after = evaluateReadiness([blocker(1, 'Resolved')]);
    expect(after.ready).toBe(true);
  });

  it('an override opens the gate but still reports what was overridden', () => {
    const r = evaluateReadiness([blocker(1, 'Active')], { by: 'alice' });
    expect(r.ready).toBe(true);
    expect(r.overridden).toBe(true);
    expect(r.blockers.map((b) => b.id)).toEqual([1]);
  });

  it('an absent override does not open the gate', () => {
    expect(evaluateReadiness([blocker(1, 'New')], null).ready).toBe(false);
    expect(evaluateReadiness([blocker(1, 'New')], { by: null }).ready).toBe(false);
  });

  it('names the specific blockers rather than saying "blocked"', () => {
    const msg = blockedMessage([blocker(12, 'New'), blocker(15, 'Active')]);
    expect(msg).toContain('#12');
    expect(msg).toContain('#15');
    expect(msg).toContain('Item 12');
  });
});

describe('cycle detection — single edge', () => {
  it('rejects an item depending on itself', () => {
    expect(findCycle(graph({}), 1, 1)).toEqual([1, 1]);
  });

  it('rejects a direct two-item loop', () => {
    // 2 already depends on 1; adding 1 -> 2 closes the loop.
    expect(findCycle(graph({ 2: [1] }), 1, 2)).not.toBeNull();
  });

  it('rejects a longer transitive loop', () => {
    // 3 -> 2 -> 1 exists; adding 1 -> 3 closes it.
    const cycle = findCycle(graph({ 3: [2], 2: [1] }), 1, 3);
    expect(cycle).not.toBeNull();
    expect(cycle).toContain(1);
    expect(cycle).toContain(3);
  });

  it('ALLOWS a diamond, which is not a cycle', () => {
    // 4 depends on 2 and 3; both depend on 1. Adding 4 -> 3 is fine.
    expect(findCycle(graph({ 4: [2], 2: [1], 3: [1] }), 4, 3)).toBeNull();
  });

  it('allows an unrelated new edge', () => {
    expect(findCycle(graph({ 2: [1] }), 3, 4)).toBeNull();
  });

  it('terminates on a graph that already contains a loop elsewhere', () => {
    expect(findCycle(graph({ 5: [6], 6: [5] }), 1, 2)).toBeNull();
  });

  it('assertNoCycle throws a DependencyCycleError naming the loop', () => {
    expect(() => assertNoCycle(graph({ 2: [1] }), 1, 2)).toThrow(DependencyCycleError);
    try {
      assertNoCycle(graph({ 2: [1] }), 1, 2);
    } catch (err) {
      const e = err as DependencyCycleError;
      expect(e.message).toContain('cycle');
      expect(e.message).toMatch(/#1|#2/);
      expect(e.cycle.length).toBeGreaterThan(1);
    }
  });

  it('assertNoCycle stays silent for a legal edge', () => {
    expect(() => assertNoCycle(graph({ 2: [1] }), 3, 2)).not.toThrow();
  });
});

describe('cycle detection — whole graph (bulk seeding)', () => {
  it('accepts a valid dependency chain', () => {
    expect(findCycleInGraph([[2, 1], [3, 2], [4, 3]])).toBeNull();
  });

  it('accepts a diamond', () => {
    expect(findCycleInGraph([[2, 1], [3, 1], [4, 2], [4, 3]])).toBeNull();
  });

  it('rejects a self-edge', () => {
    expect(findCycleInGraph([[1, 1]])).toEqual([1, 1]);
  });

  it('rejects a two-item loop', () => {
    expect(findCycleInGraph([[1, 2], [2, 1]])).not.toBeNull();
  });

  it('rejects a three-item loop and reports the members', () => {
    const cycle = findCycleInGraph([[1, 2], [2, 3], [3, 1]]);
    expect(cycle).not.toBeNull();
    for (const id of [1, 2, 3]) expect(cycle).toContain(id);
  });

  it('finds a loop hidden among valid edges', () => {
    expect(findCycleInGraph([[10, 11], [11, 12], [20, 21], [21, 20]])).not.toBeNull();
  });

  it('handles an empty edge set', () => {
    expect(findCycleInGraph([])).toBeNull();
  });
});

describe('branch staleness (trunk-based signal)', () => {
  const cfg = { maxAgeDays: 5, maxBehind: 10 };
  const now = Date.parse('2026-08-25T00:00:00Z');
  const daysAgo = (n: number) => new Date(now - n * 86_400_000).toISOString();

  it('is never stale without a branch', () => {
    expect(evaluateStaleness(null, 99, now, cfg).stale).toBe(false);
  });

  it('is fresh for a young branch that is close to main', () => {
    expect(evaluateStaleness(daysAgo(1), 2, now, cfg).stale).toBe(false);
  });

  it('is stale once the branch is too old', () => {
    const s = evaluateStaleness(daysAgo(6), 0, now, cfg);
    expect(s.stale).toBe(true);
    expect(s.ageDays).toBe(6);
    expect(s.reason).toContain('6 days old');
  });

  it('is stale once the branch is too far behind main', () => {
    const s = evaluateStaleness(daysAgo(1), 14, now, cfg);
    expect(s.stale).toBe(true);
    expect(s.reason).toContain('14 behind main');
  });

  it('reports both reasons when both apply', () => {
    const s = evaluateStaleness(daysAgo(9), 20, now, cfg);
    expect(s.reason).toContain('days old');
    expect(s.reason).toContain('behind main');
  });

  it('can disable each threshold independently by zeroing it', () => {
    // Age check off: a very old branch that is level with main is not stale.
    expect(evaluateStaleness(daysAgo(99), 0, now, { maxAgeDays: 0, maxBehind: 10 }).stale).toBe(false);
    // Behind check off: a young branch far behind main is not stale.
    expect(evaluateStaleness(daysAgo(1), 99, now, { maxAgeDays: 5, maxBehind: 0 }).stale).toBe(false);
    // ...but the threshold that is still enabled continues to fire.
    expect(evaluateStaleness(daysAgo(9), 99, now, { maxAgeDays: 5, maxBehind: 0 }).stale).toBe(true);
    expect(evaluateStaleness(daysAgo(99), 99, now, { maxAgeDays: 0, maxBehind: 10 }).stale).toBe(true);
  });

  it('treats unknown behind-count as zero rather than stale', () => {
    expect(evaluateStaleness(daysAgo(1), null, now, cfg).stale).toBe(false);
  });
});
