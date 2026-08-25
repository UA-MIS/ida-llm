import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { hasDb, installTestEnv } from './helpers/db';
import { createWorkItemSchema, updateWorkItemSchema } from '@/lib/domain/workitem';

const SCHEMA = 'agile_merge_patch_test';
installTestEnv(SCHEMA);
const d = hasDb ? describe : describe.skip;

/**
 * AB#28 — PATCH /api/v1/items/{id} must apply JSON merge-patch semantics:
 *
 *   key present with a value -> update
 *   key present as null      -> deliberate clear
 *   key ABSENT               -> leave untouched
 *
 * The regression these guard: `updateWorkItemSchema` was
 * `createWorkItemSchema.partial()`. `.partial()` wraps each field in ZodOptional
 * but does NOT strip its ZodDefault, so a partial body parsed into a FULL record
 * with every unsent field set to its default. `updateWorkItem` skips only
 * `undefined`, so those defaults were written to the row — the update path was
 * replace-not-merge and silently blanked real data.
 *
 * The parsing half runs everywhere (no database), which matters because CI runs
 * `npm test` without a DATABASE_URL — this is the layer the bug actually lived
 * at, so this is the layer that has to gate.
 */
describe('updateWorkItemSchema — merge-patch parsing (AB#28)', () => {
  it('leaves an unsent field ABSENT instead of defaulting it', () => {
    const parsed = updateWorkItemSchema.parse({ assigneeLogin: 'octocat' });
    expect(Object.keys(parsed)).toEqual(['assigneeLogin']);
  });

  it('parses the exact UI assign payload without touching anything else', () => {
    // The literal body Ready.tsx `claim()` sends.
    const parsed = updateWorkItemSchema.parse({ assigneeLogin: 'ccsmith33' });
    expect(parsed.assigneeLogin).toBe('ccsmith33');
    // The two fields the live incident on items 1 and 23 destroyed.
    expect('wave' in parsed).toBe(false);
    expect('repoFullName' in parsed).toBe(false);
    // The field the live incident on item 8 blanked.
    expect('description' in parsed).toBe(false);
  });

  it('never injects a state, so assigning cannot trip a transition check', () => {
    // The injected default `state: 'New'` also made assigning a Resolved or
    // Closed item fail as an illegal transition, not just lose data.
    const parsed = updateWorkItemSchema.parse({ assigneeLogin: 'octocat' });
    expect(parsed.state).toBeUndefined();
    expect('state' in parsed).toBe(false);
  });

  it('leaves every one of the ten defaulted fields absent on a title-only patch', () => {
    const parsed = updateWorkItemSchema.parse({ title: 'Renamed' });
    for (const field of [
      'description',
      'itemType',
      'state',
      'assigneeLogin',
      'assigneeAvatarUrl',
      'storyPoints',
      'priority',
      'sprintId',
      'tags',
      'repoFullName',
      'wave',
    ]) {
      expect(field in parsed, `${field} must stay absent`).toBe(false);
    }
  });

  it('keeps an explicit null as a null — a deliberate clear is a real feature', () => {
    // PATCH {"sprintId": null} means "move to the backlog" and must keep working.
    const parsed = updateWorkItemSchema.parse({ sprintId: null });
    expect('sprintId' in parsed).toBe(true);
    expect(parsed.sprintId).toBeNull();
  });

  it('distinguishes an explicit null from an absent key for every nullable field', () => {
    for (const field of ['assigneeLogin', 'storyPoints', 'sprintId', 'repoFullName', 'wave']) {
      const cleared = updateWorkItemSchema.parse({ [field]: null }) as Record<string, unknown>;
      expect(field in cleared, `${field} explicit null is present`).toBe(true);
      expect(cleared[field], `${field} explicit null stays null`).toBeNull();

      const untouched = updateWorkItemSchema.parse({ title: 'x' }) as Record<string, unknown>;
      expect(field in untouched, `${field} absent stays absent`).toBe(false);
    }
  });

  it('an empty patch body parses to an empty object, not a full default record', () => {
    expect(updateWorkItemSchema.parse({})).toEqual({});
  });

  it('still validates the fields it is given', () => {
    expect(updateWorkItemSchema.safeParse({ priority: 9 }).success).toBe(false);
    expect(updateWorkItemSchema.safeParse({ title: '' }).success).toBe(false);
    expect(updateWorkItemSchema.safeParse({ storyPoints: -1 }).success).toBe(false);
    expect(updateWorkItemSchema.safeParse({ repoFullName: 'not-a-repo' }).success).toBe(false);
    expect(updateWorkItemSchema.safeParse({ state: 'Nonsense' }).success).toBe(false);
  });

  it('leaves CREATE semantics alone — a missing key there still takes its default', () => {
    const created = createWorkItemSchema.parse({ title: 'Fresh' });
    expect(created).toEqual({
      title: 'Fresh',
      description: '',
      itemType: 'Story',
      state: 'New',
      assigneeLogin: null,
      assigneeAvatarUrl: null,
      storyPoints: null,
      priority: 2,
      sprintId: null,
      tags: [],
      repoFullName: null,
      wave: null,
    });
  });
});

d('updateWorkItem — partial patches preserve unsent columns (real Postgres, AB#28)', () => {
  let db: typeof import('@/lib/db/pool');
  let q: typeof import('@/lib/domain/queries');

  const FULL = {
    title: 'Port the skeleton',
    description: '# Heading\n\nA real description that must survive an assign.',
    itemType: 'Story' as const,
    state: 'New' as const,
    assigneeLogin: null,
    assigneeAvatarUrl: null,
    storyPoints: 5,
    priority: 1,
    sprintId: null,
    tags: ['groundwork'],
    repoFullName: 'UA-MIS/ida-llm',
    wave: 'Groundwork',
  };

  beforeAll(async () => {
    db = await import('@/lib/db/pool');
    await db.query(`DROP SCHEMA IF EXISTS ${SCHEMA} CASCADE`);
    await (await import('@/lib/db/migrate')).runMigrations();
    q = await import('@/lib/domain/queries');
  });

  afterAll(async () => {
    if (db) {
      await db.query(`DROP SCHEMA IF EXISTS ${SCHEMA} CASCADE`).catch(() => {});
      await db.closePool();
    }
  });

  /** Mirrors the route: validate the raw body, then hand the result to the query. */
  async function patch(id: number, body: unknown) {
    return q.updateWorkItem(id, updateWorkItemSchema.parse(body), 'tester');
  }

  it('the UI assign payload preserves wave, repoFullName and description', async () => {
    const item = await q.createWorkItem(FULL, 'tester');
    const after = await patch(item.id, { assigneeLogin: 'ccsmith33' });

    expect(after?.assigneeLogin).toBe('ccsmith33');
    expect(after?.wave).toBe('Groundwork');
    expect(after?.repoFullName).toBe('UA-MIS/ida-llm');
    expect(after?.description).toBe(FULL.description);
    expect(after?.storyPoints).toBe(5);
    expect(after?.priority).toBe(1);
    expect(after?.tags).toEqual(['groundwork']);
  });

  it('a partial API patch leaves every field it did not mention untouched', async () => {
    const sprint = await q.createSprint({
      name: 'Sprint 1',
      goal: '',
      startsOn: '2026-08-01',
      endsOn: '2026-08-14',
      position: 0,
    });
    const item = await q.createWorkItem({ ...FULL, sprintId: sprint.id }, 'tester');

    const after = await patch(item.id, { storyPoints: 8 });

    expect(after?.storyPoints).toBe(8);
    expect(after?.title).toBe(FULL.title);
    expect(after?.description).toBe(FULL.description);
    expect(after?.wave).toBe('Groundwork');
    expect(after?.repoFullName).toBe('UA-MIS/ida-llm');
    expect(after?.sprintId).toBe(sprint.id);
    expect(after?.priority).toBe(1);
    expect(after?.itemType).toBe('Story');
    expect(after?.tags).toEqual(['groundwork']);
  });

  it('an explicit null still clears — {"sprintId": null} sends an item to the backlog', async () => {
    const sprint = await q.createSprint({
      name: 'Sprint 2',
      goal: '',
      startsOn: '2026-08-15',
      endsOn: '2026-08-28',
      position: 1,
    });
    const item = await q.createWorkItem({ ...FULL, sprintId: sprint.id }, 'tester');
    expect(item.sprintId).toBe(sprint.id);

    const after = await patch(item.id, { sprintId: null });

    expect(after?.sprintId).toBeNull();
    // ...and clearing one field must not clear its neighbours.
    expect(after?.wave).toBe('Groundwork');
    expect(after?.repoFullName).toBe('UA-MIS/ida-llm');
    expect(after?.description).toBe(FULL.description);
  });

  it('assigning a Resolved item succeeds instead of 409-ing on a phantom transition', async () => {
    const item = await q.createWorkItem(FULL, 'tester');
    await q.updateWorkItem(item.id, { state: 'Active' }, 'tester');
    await q.updateWorkItem(item.id, { state: 'Resolved' }, 'tester');

    // Resolved -> New is an illegal transition. The old schema injected
    // `state: 'New'` into every partial patch, so this threw.
    const after = await patch(item.id, { assigneeLogin: 'ccsmith33' });

    expect(after?.state).toBe('Resolved');
    expect(after?.assigneeLogin).toBe('ccsmith33');
  });

  it('records activity only for the field that actually changed', async () => {
    const item = await q.createWorkItem(FULL, 'tester');
    await patch(item.id, { assigneeLogin: 'ccsmith33' });

    const activity = await q.listActivity(item.id);
    const fields = activity.map((a) => a.field);
    expect(fields).toContain('assigneeLogin');
    for (const noisy of ['wave', 'repoFullName', 'description', 'storyPoints', 'priority']) {
      expect(fields, `${noisy} must not appear in the activity log`).not.toContain(noisy);
    }
  });
});
