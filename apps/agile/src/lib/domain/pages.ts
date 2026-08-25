import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { query, queryOne, withTransaction } from '@/lib/db/pool';
import { config } from '@/lib/env';
import { toActor, type ActorLike } from './workitem';

/**
 * The narrative half of the homepage: a living README the team edits in the
 * browser, stored in Postgres with full revision history.
 */
export const HOME_SLUG = 'home';

export interface BoardPage {
  slug: string;
  body: string;
  updatedBy: string;
  updatedAt: string | null;
  /** True when nobody has edited it yet and this is the starter template. */
  isTemplate: boolean;
}

export interface PageRevision {
  id: number;
  body: string;
  editedBy: string;
  editedAt: string;
}

/**
 * Starter content for a fresh instance.
 *
 * A new board must never show a blank page — every team provisioned by the
 * wizard gets an instance, and this is their first impression of it. The text
 * is overridable per instance so a different class can ship its own.
 */
export function defaultHomeTemplate(): string {
  return `# ${config.boardTitle}

Welcome. This page is the project's living README — edit it in place as the
project changes. Everything below the divider is generated from the board and
updates itself.

## What this project is

_Describe the project in a couple of sentences: what it is, who it is for, and
why it exists._

## Goals

- _What does success look like this semester?_
- _What are the two or three outcomes that matter most?_

## Current focus

_What the team is working on right now. The live sprint summary below shows the
state; this is the "why"._

## How we work

- Work is tracked on the [board](/board); pick up anything in [Ready](/ready).
- Branches are created from a work item with **Start work**, and pull requests
  link back to it automatically.
- A pull request merging moves its item to **Resolved**; a human accepts it to
  **Closed**.

## Links

- Repository: https://github.com/${config.primaryRepo}
- Board API: [\`docs/api.md\`](/docs/api)
`;
}

/**
 * The configured starter template.
 * `HOME_TEMPLATE` wins; otherwise `HOME_TEMPLATE_PATH` is read from disk;
 * otherwise the built-in default is used.
 */
export async function starterTemplate(): Promise<string> {
  const inline = process.env.HOME_TEMPLATE;
  if (inline && inline.trim()) return inline;

  const file = process.env.HOME_TEMPLATE_PATH;
  if (file && file.trim()) {
    try {
      return await readFile(path.resolve(file), 'utf8');
    } catch (err) {
      console.warn(`[pages] HOME_TEMPLATE_PATH could not be read: ${(err as Error).message}`);
    }
  }
  return defaultHomeTemplate();
}

interface PageRow {
  slug: string;
  body: string;
  updated_by: string;
  updated_at: Date;
}

/** Returns the stored page, or the starter template when none exists yet. */
export async function getPage(slug: string = HOME_SLUG): Promise<BoardPage> {
  const row = await queryOne<PageRow>(
    'SELECT slug, body, updated_by, updated_at FROM board_pages WHERE instance_key = $1 AND slug = $2',
    [config.instanceKey, slug],
  );

  if (!row) {
    return {
      slug,
      body: await starterTemplate(),
      updatedBy: '',
      updatedAt: null,
      isTemplate: true,
    };
  }

  return {
    slug: row.slug,
    body: row.body,
    updatedBy: row.updated_by,
    updatedAt: row.updated_at.toISOString(),
    isTemplate: false,
  };
}

/**
 * Saves the page, archiving the text it replaces.
 *
 * The PREVIOUS body is written to the revision log (not the new one), so the
 * log reads as "what it used to say, and who changed it".
 */
export async function savePage(
  body: string,
  actorLike: ActorLike,
  slug: string = HOME_SLUG,
): Promise<BoardPage> {
  const actor = toActor(actorLike);

  return withTransaction(async (client) => {
    const { rows: existing } = await client.query<PageRow>(
      'SELECT slug, body, updated_by, updated_at FROM board_pages WHERE instance_key = $1 AND slug = $2 FOR UPDATE',
      [config.instanceKey, slug],
    );

    const previous = existing[0];
    if (previous && previous.body !== body) {
      await client.query(
        `INSERT INTO board_page_revisions (instance_key, slug, body, edited_by, edited_at)
         VALUES ($1,$2,$3,$4,$5)`,
        [config.instanceKey, slug, previous.body, previous.updated_by, previous.updated_at],
      );
    }

    const { rows } = await client.query<PageRow>(
      `INSERT INTO board_pages (instance_key, slug, body, updated_by, updated_at)
       VALUES ($1,$2,$3,$4, now())
       ON CONFLICT (instance_key, slug) DO UPDATE
         SET body = EXCLUDED.body, updated_by = EXCLUDED.updated_by, updated_at = now()
       RETURNING slug, body, updated_by, updated_at`,
      [config.instanceKey, slug, body, actor.login],
    );

    const saved = rows[0]!;
    return {
      slug: saved.slug,
      body: saved.body,
      updatedBy: saved.updated_by,
      updatedAt: saved.updated_at.toISOString(),
      isTemplate: false,
    };
  });
}

export async function listPageRevisions(
  slug: string = HOME_SLUG,
  limit = 25,
): Promise<PageRevision[]> {
  const rows = await query<{ id: number; body: string; edited_by: string; edited_at: Date }>(
    `SELECT id, body, edited_by, edited_at
       FROM board_page_revisions
      WHERE instance_key = $1 AND slug = $2
      ORDER BY edited_at DESC, id DESC
      LIMIT $3`,
    [config.instanceKey, slug, limit],
  );
  return rows.map((r) => ({
    id: r.id,
    body: r.body,
    editedBy: r.edited_by,
    editedAt: r.edited_at.toISOString(),
  }));
}
