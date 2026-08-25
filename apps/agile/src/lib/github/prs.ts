import { config } from '@/lib/env';

export interface ParsedPrRef {
  repoFullName: string;
  prNumber: number;
}

/**
 * Accepts what a developer actually pastes:
 *   https://github.com/owner/repo/pull/123        (with or without /files, #discussion, ?w=1)
 *   owner/repo#123
 *   #123        -> the project repo
 *   123         -> the project repo
 */
export function parsePrReference(input: string, defaultRepo?: string): ParsedPrRef | null {
  const fallbackRepo = defaultRepo ?? config.primaryRepo;
  const raw = (input ?? '').trim();
  if (!raw) return null;

  const url = raw.match(
    /^(?:https?:\/\/)?(?:www\.)?github\.com\/([\w.-]+)\/([\w.-]+)\/pull\/(\d+)(?:[/?#].*)?$/i,
  );
  if (url) {
    return { repoFullName: `${url[1]}/${url[2]}`, prNumber: Number(url[3]) };
  }

  const shorthand = raw.match(/^([\w.-]+)\/([\w.-]+)#(\d+)$/);
  if (shorthand) {
    return { repoFullName: `${shorthand[1]}/${shorthand[2]}`, prNumber: Number(shorthand[3]) };
  }

  const bare = raw.match(/^#?(\d+)$/);
  if (bare) {
    const n = Number(bare[1]);
    return n > 0 ? { repoFullName: fallbackRepo, prNumber: n } : null;
  }

  return null;
}

/**
 * Finds work-item references inside a PR title/body, so a PR can offer to
 * attach itself to the items it mentions.
 *
 * Supported: `AB#123` (the Azure Boards convention the team already knows) and
 * the explicit `agile#123`. A bare `#123` is deliberately NOT matched — in a
 * GitHub PR body that almost always means an issue or another PR.
 */
export function extractWorkItemRefs(...texts: Array<string | null | undefined>): number[] {
  const found = new Set<number>();
  const pattern = /\b(?:AB|agile)#(\d+)\b/gi;

  for (const text of texts) {
    if (!text) continue;
    for (const match of text.matchAll(pattern)) {
      const n = Number(match[1]);
      if (Number.isInteger(n) && n > 0) found.add(n);
    }
  }

  return [...found].sort((a, b) => a - b);
}
