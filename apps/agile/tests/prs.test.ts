import { describe, it, expect } from 'vitest';
import { parsePrReference, extractWorkItemRefs } from '@/lib/github/prs';

const DEFAULT = 'UA-MIS/ida-llm';

describe('parsePrReference', () => {
  it('parses a full PR URL', () => {
    expect(parsePrReference('https://github.com/UA-MIS/ida-llm/pull/42')).toEqual({
      repoFullName: 'UA-MIS/ida-llm',
      prNumber: 42,
    });
  });

  it.each([
    'https://github.com/UA-MIS/ida-llm/pull/42/files',
    'https://github.com/UA-MIS/ida-llm/pull/42#discussion_r1',
    'https://github.com/UA-MIS/ida-llm/pull/42?w=1',
    'http://github.com/UA-MIS/ida-llm/pull/42',
    'github.com/UA-MIS/ida-llm/pull/42',
    'https://www.github.com/UA-MIS/ida-llm/pull/42',
  ])('tolerates the real-world URL shape %s', (url) => {
    expect(parsePrReference(url)).toEqual({ repoFullName: 'UA-MIS/ida-llm', prNumber: 42 });
  });

  it('parses owner/repo#N shorthand', () => {
    expect(parsePrReference('UA-MIS/platform-infra#7')).toEqual({
      repoFullName: 'UA-MIS/platform-infra',
      prNumber: 7,
    });
  });

  it('parses a bare number against the project repo', () => {
    expect(parsePrReference('#15', DEFAULT)).toEqual({ repoFullName: DEFAULT, prNumber: 15 });
    expect(parsePrReference('15', DEFAULT)).toEqual({ repoFullName: DEFAULT, prNumber: 15 });
  });

  it('trims surrounding whitespace', () => {
    expect(parsePrReference('  https://github.com/UA-MIS/ida-llm/pull/9  ')).toEqual({
      repoFullName: 'UA-MIS/ida-llm',
      prNumber: 9,
    });
  });

  it.each([
    '',
    '   ',
    'not a pr',
    'https://gitlab.com/a/b/pull/1',
    'https://github.com/UA-MIS/ida-llm/issues/42',
    'https://github.com/UA-MIS/ida-llm/pull/',
    'https://evil.com/github.com/a/b/pull/1',
    '#0',
    '0',
  ])('rejects %j', (bad) => {
    expect(parsePrReference(bad, DEFAULT)).toBeNull();
  });

  it('does not treat an issue URL as a pull request', () => {
    expect(parsePrReference('https://github.com/UA-MIS/ida-llm/issues/1')).toBeNull();
  });
});

describe('extractWorkItemRefs', () => {
  it('finds AB#N references in a title', () => {
    expect(extractWorkItemRefs('Fix ingest AB#12')).toEqual([12]);
  });

  it('finds references across title and body, de-duplicated and sorted', () => {
    expect(extractWorkItemRefs('AB#9 and AB#3', 'also relates to AB#9, agile#1')).toEqual([1, 3, 9]);
  });

  it('is case-insensitive', () => {
    expect(extractWorkItemRefs('ab#5 Ab#6')).toEqual([5, 6]);
  });

  it('ignores a bare #N, which means a GitHub issue', () => {
    expect(extractWorkItemRefs('Closes #123')).toEqual([]);
  });

  it('ignores null/undefined/empty inputs', () => {
    expect(extractWorkItemRefs(null, undefined, '')).toEqual([]);
  });

  it('does not match AB# embedded in a longer word', () => {
    expect(extractWorkItemRefs('LAB#12')).toEqual([]);
  });

  it('returns an empty array when there is nothing to find', () => {
    expect(extractWorkItemRefs('a normal PR title')).toEqual([]);
  });
});
