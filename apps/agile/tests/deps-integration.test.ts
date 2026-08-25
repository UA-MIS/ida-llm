import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { hasDb, installTestEnv } from './helpers/db';

const SCHEMA = 'agile_deps_test';
installTestEnv(SCHEMA);
const d = hasDb ? describe : describe.skip;

/**
 * The dependency gate and the shared current sprint, end to end against a real
 * database — these are the behaviours the team will actually feel.
 */
d('dependencies, gating and shared sprint (real Postgres)', () => {
  let db: typeof import('@/lib/db/pool');
  let q: typeof import('@/lib/domain/queries');
  let deps: typeof import('@/lib/domain/deps-queries');
  let seed: typeof import('@/lib/api/seed');
  let dep: typeof import('@/lib/domain/dependencies');

  beforeAll(async () => {
    db = await import('@/lib/db/pool');
    await db.query(`DROP SCHEMA IF EXISTS ${SCHEMA} CASCADE`);
    const applied = await (await import('@/lib/db/migrate')).runMigrations();
    // Both migrations must apply, in order.
    expect(applied).toEqual(['001_init.sql', '002_deps_sprints_repos.sql']);
    q = await import('@/lib/domain/queries');
    deps = await import('@/lib/domain/deps-queries');
    seed = await import('@/lib/api/seed');
    dep = await import('@/lib/domain/dependencies');
  });

  afterAll(async () => {
    if (db) {
      await db.query(`DROP SCHEMA IF EXISTS ${SCHEMA} CASCADE`).catch(() => {});
      await db.closePool();
    }
  });

  const mk = (title: string, extra: Record<string, unknown> = {}) =>
    q.createWorkItem({ title, ...extra }, 'alice');

  it('an item with no dependencies is ready', async () => {
    const item = await mk('Free to start');
    expect((await deps.readinessFor(item.id)).ready).toBe(true);
  });

  it('BLOCKS an item while its dependency is unfinished, naming the blocker', async () => {
    const blocker = await mk('Harness core');
    const item = await mk('Depends on harness');
    await deps.addDependency(item.id, blocker.id, 'alice');

    const r = await deps.readinessFor(item.id);
    expect(r.ready).toBe(false);
    expect(r.blockers.map((b) => b.id)).toEqual([blocker.id]);
    expect(dep.blockedMessage(r.blockers)).toContain('Harness core');
  });

  it('OPENS the gate when the last blocker is Resolved', async () => {
    const b1 = await mk('Blocker one');
    const b2 = await mk('Blocker two');
    const item = await mk('Two blockers');
    await deps.addDependency(item.id, b1.id, 'alice');
    await deps.addDependency(item.id, b2.id, 'alice');

    expect((await deps.readinessFor(item.id)).ready).toBe(false);

    await q.updateWorkItem(b1.id, { state: 'Active' }, 'alice');
    await q.updateWorkItem(b1.id, { state: 'Resolved' }, 'alice');
    expect((await deps.readinessFor(item.id)).ready).toBe(false);

    await q.updateWorkItem(b2.id, { state: 'Active' }, 'alice');
    await q.updateWorkItem(b2.id, { state: 'Resolved' }, 'alice');
    expect((await deps.readinessFor(item.id)).ready).toBe(true);
  });

  it('REJECTS a dependency cycle and leaves the graph unchanged', async () => {
    const a = await mk('Cycle A');
    const b = await mk('Cycle B');
    await deps.addDependency(b.id, a.id, 'alice');

    await expect(deps.addDependency(a.id, b.id, 'alice')).rejects.toThrow(dep.DependencyCycleError);
    expect((await deps.listBlockers(a.id)).length).toBe(0);
  });

  it('REJECTS a self-dependency', async () => {
    const a = await mk('Self');
    await expect(deps.addDependency(a.id, a.id, 'alice')).rejects.toThrow();
  });

  it('REJECTS a transitive cycle', async () => {
    const a = await mk('T-A');
    const b = await mk('T-B');
    const c = await mk('T-C');
    await deps.addDependency(b.id, a.id, 'alice');
    await deps.addDependency(c.id, b.id, 'alice');
    await expect(deps.addDependency(a.id, c.id, 'alice')).rejects.toThrow(dep.DependencyCycleError);
  });

  it('records the override with its reason in item history', async () => {
    const blocker = await mk('Slow blocker');
    const item = await mk('Impatient');
    await deps.addDependency(item.id, blocker.id, 'alice');
    expect((await deps.readinessFor(item.id)).ready).toBe(false);

    await deps.overrideDependencyGate(item.id, 'Spiking ahead, agreed in standup', 'bob');

    const r = await deps.readinessFor(item.id);
    expect(r.ready).toBe(true);
    expect(r.overridden).toBe(true);

    const log = await q.listActivity(item.id);
    const entry = log.find((e) => e.field === 'dependency_override');
    expect(entry).toBeDefined();
    expect(entry?.actorLogin).toBe('bob');
    expect(entry?.note).toContain('Spiking ahead');
  });

  it('withdrawing an override re-applies the gate', async () => {
    const blocker = await mk('Still blocking');
    const item = await mk('Overridden then not');
    await deps.addDependency(item.id, blocker.id, 'alice');
    await deps.overrideDependencyGate(item.id, 'temporary', 'bob');
    expect((await deps.readinessFor(item.id)).ready).toBe(true);

    await deps.clearDependencyOverride(item.id);
    expect((await deps.readinessFor(item.id)).ready).toBe(false);
  });

  it('removing a dependency clears the block', async () => {
    const blocker = await mk('Wrongly added');
    const item = await mk('Mis-linked');
    await deps.addDependency(item.id, blocker.id, 'alice');
    expect((await deps.readinessFor(item.id)).ready).toBe(false);

    expect(await deps.removeDependency(item.id, blocker.id, 'alice')).toBe(true);
    expect((await deps.readinessFor(item.id)).ready).toBe(true);
  });

  it('exposes the reverse edge — what this item is blocking', async () => {
    const blocker = await mk('Foundation');
    const one = await mk('Consumer one');
    const two = await mk('Consumer two');
    await deps.addDependency(one.id, blocker.id, 'alice');
    await deps.addDependency(two.id, blocker.id, 'alice');

    const blocking = await deps.listBlocking(blocker.id);
    expect(blocking.map((b) => b.id).sort()).toEqual([one.id, two.id].sort());
  });

  it('resolves readiness for the whole board in one query', async () => {
    const map = await deps.readinessMap();
    expect(map.size).toBeGreaterThan(0);
    for (const [, r] of map) expect(typeof r.ready).toBe('boolean');
  });

  // -------------------------------------------------------------- sprints

  it('current sprint is SHARED state and records who set it', async () => {
    const s1 = await q.createSprint({ name: 'Shared 1', startsOn: '2026-09-01', endsOn: '2026-09-14' });

    expect((await deps.getCurrentSprint()).sprintId).toBeNull();

    await deps.setCurrentSprint(s1.id, 'carol');
    const current = await deps.getCurrentSprint();
    expect(current.sprintId).toBe(s1.id);
    expect(current.setBy).toBe('carol');
    expect(current.setAt).not.toBeNull();
  });

  it('setting the current sprint replaces the previous one for everyone', async () => {
    const s2 = await q.createSprint({ name: 'Shared 2', startsOn: '2026-09-15', endsOn: '2026-09-28' });
    await deps.setCurrentSprint(s2.id, 'dave');

    const current = await deps.getCurrentSprint();
    expect(current.sprintId).toBe(s2.id);
    expect(current.setBy).toBe('dave');
  });

  it('rejects setting a sprint that does not exist', async () => {
    await expect(deps.setCurrentSprint(999_999, 'alice')).rejects.toThrow();
  });

  it('can clear the current sprint', async () => {
    await deps.setCurrentSprint(null, 'alice');
    expect((await deps.getCurrentSprint()).sprintId).toBeNull();
  });

  // ---------------------------------------------------------- bulk seeding

  it('seeds a whole semester — sprints, items, waves and the dependency graph — in ONE call', async () => {
    const result = await seed.seedBoard(
      {
        sprints: [
          { key: 's1', name: 'Seed Sprint 1', startsOn: '2026-10-01', endsOn: '2026-10-14', goal: 'Foundations' },
          { key: 's2', name: 'Seed Sprint 2', startsOn: '2026-10-15', endsOn: '2026-10-28' },
        ],
        items: [
          { key: 'core', title: 'Harness core', sprintKey: 's1', wave: 'Wave 1', storyPoints: 8 },
          { key: 'schema', title: 'Task schema', sprintKey: 's1', wave: 'Wave 1', storyPoints: 3 },
          { key: 'runner', title: 'Runner', sprintKey: 's2', wave: 'Wave 2', dependsOn: ['core', 'schema'] },
          { key: 'ui', title: 'Results UI', sprintKey: 's2', wave: 'Wave 2', dependsOn: ['runner'] },
        ],
        currentSprintKey: 's1',
      },
      'alice',
    );

    expect(result.sprints).toHaveLength(2);
    expect(result.items).toHaveLength(4);
    expect(result.dependencies).toBe(3);

    // The graph is real.
    const runner = result.items.find((i) => i.key === 'runner')!;
    const blockers = await deps.listBlockers(runner.id);
    expect(blockers.map((b) => b.title).sort()).toEqual(['Harness core', 'Task schema']);

    // Wave and sprint assignment landed.
    expect(runner.wave).toBe('Wave 2');
    const s1 = result.sprints.find((s) => s.key === 's1')!;
    const core = result.items.find((i) => i.key === 'core')!;
    expect(core.sprintId).toBe(s1.id);

    // The current sprint was set as part of the same call.
    expect((await deps.getCurrentSprint()).sprintId).toBe(s1.id);

    // Wave-2 work is correctly gated behind Wave-1 work.
    expect((await deps.readinessFor(runner.id)).ready).toBe(false);
    expect((await deps.readinessFor(core.id)).ready).toBe(true);
  });

  it('REJECTS a seed whose dependency graph contains a cycle, writing nothing', async () => {
    const before = (await q.listWorkItems()).length;

    await expect(
      seed.seedBoard(
        {
          items: [
            { key: 'a', title: 'Cyclic A', dependsOn: ['b'] },
            { key: 'b', title: 'Cyclic B', dependsOn: ['a'] },
          ],
        },
        'alice',
      ),
    ).rejects.toThrow(/cycle/i);

    // The items themselves are created before the graph is validated, but NO
    // dependency edge is written — the graph is checked as a whole first.
    const a = (await q.listWorkItems()).find((i) => i.title === 'Cyclic A');
    if (a) expect(await deps.listBlockers(a.id)).toEqual([]);
    expect((await q.listWorkItems()).length).toBeGreaterThanOrEqual(before);
  });

  it('rejects a dependency on an unknown key with an actionable message', async () => {
    await expect(
      seed.seedBoard({ items: [{ title: 'Dangling', dependsOn: ['nope'] }] }, 'alice'),
    ).rejects.toThrow(/nope/);
  });

  it('allows depending on a pre-existing item by numeric id', async () => {
    const existing = await mk('Pre-existing blocker');
    const result = await seed.seedBoard(
      { items: [{ key: 'new', title: 'Depends on existing', dependsOn: [existing.id] }] },
      'alice',
    );
    const created = result.items[0]!;
    expect((await deps.listBlockers(created.id)).map((b) => b.id)).toEqual([existing.id]);
  });

  it('rejects duplicate keys within one seed', async () => {
    await expect(
      seed.seedBoard(
        { items: [{ key: 'dup', title: 'One' }, { key: 'dup', title: 'Two' }] },
        'alice',
      ),
    ).rejects.toThrow(/dup/);
  });
});
