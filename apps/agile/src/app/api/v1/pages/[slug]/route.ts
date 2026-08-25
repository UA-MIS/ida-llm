import { z } from 'zod';
import { withApi } from '@/lib/api/route';
import { apiError, ok, readJson, validationError } from '@/lib/api/respond';
import { principalToActor } from '@/lib/auth/principal';
import { getPage, savePage } from '@/lib/domain/pages';

export const dynamic = 'force-dynamic';

const SLUGS = new Set(['home']);
const bodySchema = z.object({ body: z.string().max(100_000) });

/**
 * GET /api/v1/pages/{slug} — the narrative page.
 * Returns the starter template (with `isTemplate: true`) when never edited.
 */
export const GET = withApi(async ({ params }) => {
  const slug = params.slug ?? '';
  if (!SLUGS.has(slug)) return apiError('not_found', `No page named "${slug}".`, 404);
  return ok({ page: await getPage(slug) });
});

/** PUT /api/v1/pages/{slug} — replace the markdown. Records a revision. */
export const PUT = withApi(async ({ request, params, principal }) => {
  const slug = params.slug ?? '';
  if (!SLUGS.has(slug)) return apiError('not_found', `No page named "${slug}".`, 404);

  const body = await readJson(request);
  if (!body.ok) return body.response;
  const parsed = bodySchema.safeParse(body.value);
  if (!parsed.success) return validationError(parsed.error);

  return ok({ page: await savePage(parsed.data.body, principalToActor(principal), slug) });
});
