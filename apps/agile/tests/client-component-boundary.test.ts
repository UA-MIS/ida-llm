import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const SRC = fileURLToPath(new URL('../src', import.meta.url));

/**
 * AB#30 — the backlog page 500-ed with:
 *
 *   Error: Event handlers cannot be passed to Client Component props.
 *     {className: "pr-chip", ..., onClick: function onClick, ...}
 *
 * `src/components/chips.tsx` carried no 'use client' directive, but `PrChip`
 * passes `onClick` to an <a>. React Server Components cannot receive event
 * handlers as props, so rendering it from a Server Component throws at REQUEST
 * time. `src/app/backlog/page.tsx` is a Server Component and renders `PrChip`
 * directly, so the page died for any item with a linked pull request — while the
 * board survived, because `Board.tsx` is 'use client'.
 *
 * Two properties made this expensive to find, and both are why the gate is here:
 *
 *  - `next build` does NOT catch it. The build passed clean the whole time.
 *  - It only fires with REAL data. `pullRequests.map()` over an empty array
 *    renders no chip at all, so seeded items with no linked PR render fine.
 *
 * So this asserts the invariant at the only layer that can hold it: a module
 * that passes a JSX event handler must declare itself a client module. That
 * covers the whole class rather than this one instance.
 */

function tsxFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...tsxFiles(full));
    else if (entry.name.endsWith('.tsx')) out.push(full);
  }
  return out;
}

/** Matches a JSX event-handler prop: `onClick={`, `onDragStart={`, ... */
const HANDLER = /\bon[A-Z][a-zA-Z]*=\{/;

/**
 * True when the file's directive prologue declares a client module. The
 * directive must lead the file, so only comments and blank lines may precede it.
 */
function declaresUseClient(source: string): boolean {
  for (const raw of source.split('\n')) {
    const line = raw.trim();
    if (line === '' || line.startsWith('//') || line.startsWith('/*') || line.startsWith('*')) {
      continue;
    }
    return line === "'use client';" || line === '"use client";';
  }
  return false;
}

describe("client/server component boundary (AB#30)", () => {
  const files = tsxFiles(SRC);

  it('finds the component tree to check', () => {
    expect(files.length).toBeGreaterThan(10);
  });

  it('every module passing a JSX event handler declares itself a client module', () => {
    const violations = files
      .filter((f) => {
        const source = readFileSync(f, 'utf8');
        return HANDLER.test(source) && !declaresUseClient(source);
      })
      .map((f) => f.slice(SRC.length + 1));

    expect(
      violations,
      `these modules pass event handlers but are Server Components — rendering ` +
        `them from a Server Component throws at request time:\n  ${violations.join('\n  ')}`,
    ).toEqual([]);
  });

  it("chips.tsx specifically is a client module — it is the one a Server Component imports", () => {
    // The backlog page renders these chips directly, so this file is the exact
    // boundary that broke. Named explicitly so the reason survives a refactor.
    const chips = readFileSync(join(SRC, 'components', 'chips.tsx'), 'utf8');
    expect(HANDLER.test(chips), 'PrChip still carries the onClick this guards').toBe(true);
    expect(declaresUseClient(chips)).toBe(true);
  });

  it('the backlog page still renders PrChip — the import that made this load-bearing', () => {
    const page = readFileSync(join(SRC, 'app', 'backlog', 'page.tsx'), 'utf8');
    expect(page).toContain('PrChip');
    // If the page ever became a client component the invariant would be moot,
    // so assert it is still a Server Component and therefore still constrained.
    expect(declaresUseClient(page)).toBe(false);
  });
});

describe('declaresUseClient helper', () => {
  it('accepts a leading directive', () => {
    expect(declaresUseClient("'use client';\nimport x from 'y';")).toBe(true);
    expect(declaresUseClient('"use client";\n')).toBe(true);
  });

  it('accepts comments and blank lines before the directive', () => {
    expect(declaresUseClient("// why\n\n'use client';\nimport x from 'y';")).toBe(true);
  });

  it('rejects a file with no directive', () => {
    expect(declaresUseClient("import x from 'y';")).toBe(false);
  });

  it('rejects a directive that does not lead the file', () => {
    // Not a directive prologue any more — React ignores it, so must the test.
    expect(declaresUseClient("import x from 'y';\n'use client';")).toBe(false);
  });
});
