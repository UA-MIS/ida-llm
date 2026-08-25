import { withApi } from '@/lib/api/route';
import { apiError, ok } from '@/lib/api/respond';
import { getPage } from '@/lib/domain/pages';
import { renderMarkdown } from '@/lib/markdown';

export const dynamic = 'force-dynamic';

/**
 * The page as sanitised HTML.
 *
 * Rendering happens on the server so the browser never has to run an untrusted
 * markdown pipeline — the same sanitiser used for work-item descriptions.
 */
export const GET = withApi(async ({ params }) => {
  const slug = params.slug ?? '';
  if (slug !== 'home') return apiError('not_found', `No page named "${slug}".`, 404);
  const page = await getPage(slug);
  return ok({ html: renderMarkdown(page.body), isTemplate: page.isTemplate });
});
