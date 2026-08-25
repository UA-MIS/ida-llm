import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { decideProgression, progressionPath } from '@/lib/sync/progression';
import type { WorkItemState } from '@/lib/domain/workitem';

const item = (state: WorkItemState) => ({ state });

function setFlags(vals: Record<string, string | undefined>) {
  for (const [k, v] of Object.entries(vals)) {
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
  }
}

describe('auto-progression rules', () => {
  beforeEach(() =>
    setFlags({
      AUTO_PROGRESS: undefined,
      AUTO_PROGRESS_ON_COMMIT: undefined,
      AUTO_PROGRESS_ON_PR_OPEN: undefined,
      AUTO_PROGRESS_ON_PR_MERGE: undefined,
    }),
  );
  afterEach(() => setFlags({ AUTO_PROGRESS: undefined }));

  it('first commit on a New item moves it to Active', () => {
    const d = decideProgression(item('New'), { kind: 'commit', branch: 'story/1-x', count: 1 });
    expect(d.toState).toBe('Active');
    expect(d.note).toContain('moved by GitHub');
    expect(d.note).toContain('story/1-x');
  });

  it('a commit on an already-Active item changes nothing', () => {
    expect(decideProgression(item('Active'), { kind: 'commit', branch: 'b', count: 3 }).toState).toBeNull();
  });

  it('a commit does not resurrect a Closed item', () => {
    expect(decideProgression(item('Closed'), { kind: 'commit', branch: 'b', count: 1 }).toState).toBeNull();
  });

  it('opening a PR moves a New item to Active', () => {
    const d = decideProgression(item('New'), { kind: 'pr-opened', prNumber: 12, repo: 'o/r' });
    expect(d.toState).toBe('Active');
    expect(d.note).toContain('PR #12 opened');
  });

  it('opening a PR on a Resolved item reopens it as Active', () => {
    expect(decideProgression(item('Resolved'), { kind: 'pr-opened', prNumber: 3, repo: 'o/r' }).toState).toBe('Active');
  });

  it('merging a PR moves an Active item to Resolved — NOT Closed', () => {
    const d = decideProgression(item('Active'), { kind: 'pr-merged', prNumber: 9, repo: 'o/r' });
    expect(d.toState).toBe('Resolved');
    expect(d.note).toContain('PR #9 merged');
  });

  it('never auto-Closes: Closed stays a human decision', () => {
    for (const state of ['New', 'Active', 'Resolved'] as WorkItemState[]) {
      for (const trigger of [
        { kind: 'pr-merged', prNumber: 1, repo: 'o/r' },
        { kind: 'pr-opened', prNumber: 1, repo: 'o/r' },
        { kind: 'commit', branch: 'b', count: 1 },
      ] as const) {
        expect(decideProgression(item(state), trigger).toState).not.toBe('Closed');
      }
    }
  });

  it('merging from New still ends at Resolved, stepping through Active', () => {
    const d = decideProgression(item('New'), { kind: 'pr-merged', prNumber: 4, repo: 'o/r' });
    expect(d.toState).toBe('Resolved');
    // New -> Resolved is not a legal single hop, so the path walks via Active.
    expect(progressionPath('New', 'Resolved')).toEqual(['Active', 'Resolved']);
  });

  it('a PR closed without merging does NOT change state, but warns', () => {
    const d = decideProgression(item('Active'), {
      kind: 'pr-closed-unmerged',
      prNumber: 5,
      repo: 'o/r',
    });
    expect(d.toState).toBeNull();
    expect(d.warning).toContain('closed without merging');
  });

  it('AUTO_PROGRESS=false disables every rule', () => {
    setFlags({ AUTO_PROGRESS: 'false' });
    expect(decideProgression(item('New'), { kind: 'commit', branch: 'b', count: 1 }).toState).toBeNull();
    expect(decideProgression(item('New'), { kind: 'pr-opened', prNumber: 1, repo: 'o/r' }).toState).toBeNull();
    expect(decideProgression(item('Active'), { kind: 'pr-merged', prNumber: 1, repo: 'o/r' }).toState).toBeNull();
  });

  it('individual rules can be disabled independently', () => {
    setFlags({ AUTO_PROGRESS_ON_COMMIT: 'false' });
    expect(decideProgression(item('New'), { kind: 'commit', branch: 'b', count: 1 }).toState).toBeNull();
    // ...while PR rules still fire.
    expect(decideProgression(item('Active'), { kind: 'pr-merged', prNumber: 1, repo: 'o/r' }).toState).toBe('Resolved');
  });

  it('only ever produces legal transition paths', () => {
    expect(progressionPath('New', 'Active')).toEqual(['Active']);
    expect(progressionPath('Active', 'Resolved')).toEqual(['Resolved']);
    expect(progressionPath('Active', 'Active')).toEqual([]);
  });
});
