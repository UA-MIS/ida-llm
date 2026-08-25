import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { requireSession } from '@/lib/auth/guard';
import { renderMarkdown } from '@/lib/markdown';
import { Shell } from '@/components/Shell';

export const dynamic = 'force-dynamic';

/** Serves docs/api.md in-app so the reference travels with the deployment. */
export default async function ApiDocsPage() {
  const session = await requireSession('/docs/api');

  let markdown: string;
  try {
    markdown = await readFile(path.join(process.cwd(), 'docs', 'api.md'), 'utf8');
  } catch {
    markdown =
      '# API reference\n\nThe reference file was not bundled with this build. ' +
      'The machine-readable spec is always available at [/api/v1/openapi.json](/api/v1/openapi.json).';
  }

  return (
    <Shell session={session} active="tokens">
      <div className="page-head">
        <h1>API reference</h1>
        <span className="spacer" />
        <a className="btn btn-sm" href="/api/v1/openapi.json">OpenAPI spec</a>
      </div>
      <div className="panel">
        <div className="section">
          <div className="markdown" dangerouslySetInnerHTML={{ __html: renderMarkdown(markdown) }} />
        </div>
      </div>
    </Shell>
  );
}
