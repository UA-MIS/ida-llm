import { withApi } from '@/lib/api/route';
import { apiError, ok } from '@/lib/api/respond';
import { listPageRevisions } from '@/lib/domain/pages';

export const dynamic = 'force-dynamic';

/** GET — prior versions of the page, newest first: who changed it, and when. */
export const GET = withApi(async ({ request, params }) => {
  const slug = params.slug ?? '';
  if (slug !== 'home') return apiError('not_found', `No page named "${slug}".`, 404);

  const limit = Number(new URL(request.url).searchParams.get('limit') ?? 25);
  return ok({
    revisions: await listPageRevisions(slug, Number.isFinite(limit) ? Math.min(limit, 100) : 25),
  });
});
