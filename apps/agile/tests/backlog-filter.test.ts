import { describe, it, expect } from 'vitest';
import { parseSprintFilter } from '@/lib/domain/workitem';

/**
 * AB#30 — the backlog's `?sprint=` query parameter.
 *
 * The regression this guards: the page computed `Number(sp.sprint)` with no
 * integer check. `Number('abc')` is NaN, and `typeof NaN === 'number'`, so the
 * value passed the query layer's `typeof filters.sprintId === 'number'` guard
 * and reached Postgres as a bind parameter — erroring the whole backlog page
 * with a 500 instead of simply ignoring an unusable filter.
 */
describe('parseSprintFilter (AB#30)', () => {
  it('treats an absent or "all" filter as every sprint', () => {
    expect(parseSprintFilter(undefined)).toBeUndefined();
    expect(parseSprintFilter('')).toBeUndefined();
    expect(parseSprintFilter('all')).toBeUndefined();
  });

  it('treats "none" as the no-sprint bucket, which is NOT the same as "all"', () => {
    // null and undefined mean different things to listWorkItems, so this
    // distinction has to survive.
    expect(parseSprintFilter('none')).toBeNull();
  });

  it('reads a positive integer sprint id', () => {
    expect(parseSprintFilter('1')).toBe(1);
    expect(parseSprintFilter('42')).toBe(42);
  });

  it('falls back to "all" for a value that is not a usable sprint id', () => {
    // Each of these previously produced NaN or a nonsense bind parameter.
    for (const raw of ['abc', 'NaN', '1.5', '-1', '0', ' ', '1; DROP TABLE work_items', '1e3abc']) {
      const parsed = parseSprintFilter(raw);
      expect(parsed, `${JSON.stringify(raw)} must not become a sprint id`).toBeUndefined();
    }
  });

  it('never returns NaN — the exact value that reached SQL and 500-ed the page', () => {
    for (const raw of ['abc', 'NaN', '', 'all', 'none', '7', '-3']) {
      const parsed = parseSprintFilter(raw);
      expect(Number.isNaN(parsed as number), `${JSON.stringify(raw)} produced NaN`).toBe(false);
    }
  });
});
