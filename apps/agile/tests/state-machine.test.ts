import { describe, it, expect } from 'vitest';
import {
  canTransition,
  assertTransition,
  allowedTransitions,
  InvalidTransitionError,
  isDone,
  BOARD_COLUMNS,
  WORK_ITEM_STATES,
  type WorkItemState,
} from '@/lib/domain/workitem';

describe('work item state machine', () => {
  it('allows the forward happy path New -> Active -> Resolved -> Closed', () => {
    expect(canTransition('New', 'Active')).toBe(true);
    expect(canTransition('Active', 'Resolved')).toBe(true);
    expect(canTransition('Resolved', 'Closed')).toBe(true);
  });

  it('allows sending work back one step for rework', () => {
    expect(canTransition('Active', 'New')).toBe(true);
    expect(canTransition('Resolved', 'Active')).toBe(true);
  });

  it('allows reactivating a closed item', () => {
    expect(canTransition('Closed', 'Active')).toBe(true);
  });

  it('treats a same-state move as a no-op that is always allowed', () => {
    for (const s of WORK_ITEM_STATES) {
      expect(canTransition(s, s), `${s} -> ${s}`).toBe(true);
    }
  });

  it('forbids skipping straight from New to Resolved or Closed', () => {
    expect(canTransition('New', 'Resolved')).toBe(false);
    expect(canTransition('New', 'Closed')).toBe(false);
  });

  it('forbids jumping from Active straight to Closed', () => {
    expect(canTransition('Active', 'Closed')).toBe(false);
  });

  it('forbids reopening a Closed item directly into New or Resolved', () => {
    expect(canTransition('Closed', 'New')).toBe(false);
    expect(canTransition('Closed', 'Resolved')).toBe(false);
  });

  it('forbids removing an item that is already Resolved or Closed', () => {
    expect(canTransition('Resolved', 'Removed')).toBe(false);
    expect(canTransition('Closed', 'Removed')).toBe(false);
  });

  it('allows removing New or Active work', () => {
    expect(canTransition('New', 'Removed')).toBe(true);
    expect(canTransition('Active', 'Removed')).toBe(true);
  });

  it('lets a Removed item be restored only to New', () => {
    expect(allowedTransitions('Removed')).toEqual(['New']);
  });

  it('assertTransition throws a descriptive InvalidTransitionError', () => {
    expect(() => assertTransition('New', 'Closed')).toThrow(InvalidTransitionError);
    try {
      assertTransition('New', 'Closed');
    } catch (err) {
      const e = err as InvalidTransitionError;
      expect(e.from).toBe('New');
      expect(e.to).toBe('Closed');
      expect(e.message).toContain('Allowed from "New"');
    }
  });

  it('assertTransition stays silent on a legal move', () => {
    expect(() => assertTransition('Active', 'Resolved')).not.toThrow();
  });

  it('never advertises a transition that canTransition would reject', () => {
    for (const from of WORK_ITEM_STATES) {
      for (const to of allowedTransitions(from)) {
        expect(canTransition(from, to), `${from} -> ${to}`).toBe(true);
      }
    }
  });

  it('every advertised transition targets a real state', () => {
    const valid = new Set<WorkItemState>(WORK_ITEM_STATES);
    for (const from of WORK_ITEM_STATES) {
      for (const to of allowedTransitions(from)) {
        expect(valid.has(to), `${from} -> ${to}`).toBe(true);
      }
    }
  });

  it('has no unreachable state (every state is some transition target)', () => {
    const reachable = new Set<WorkItemState>(['New']);
    for (const from of WORK_ITEM_STATES) {
      for (const to of allowedTransitions(from)) reachable.add(to);
    }
    for (const s of WORK_ITEM_STATES) {
      expect(reachable.has(s), `${s} is unreachable`).toBe(true);
    }
  });

  it('counts Closed and Removed as done, nothing else', () => {
    expect(isDone('Closed')).toBe(true);
    expect(isDone('Removed')).toBe(true);
    expect(isDone('New')).toBe(false);
    expect(isDone('Active')).toBe(false);
    expect(isDone('Resolved')).toBe(false);
  });

  it('keeps Removed off the board', () => {
    expect(BOARD_COLUMNS).toEqual(['New', 'Active', 'Resolved', 'Closed']);
    expect(BOARD_COLUMNS).not.toContain('Removed');
  });
});
