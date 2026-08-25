import { buildOpenApiDocument } from '@/lib/api/openapi';

export const dynamic = 'force-dynamic';

/**
 * The API contract, unauthenticated on purpose: it describes shapes only and
 * contains no board data, so an agent can discover how to call the API before
 * it has a token.
 */
export function GET() {
  return Response.json(buildOpenApiDocument(), {
    headers: { 'cache-control': 'public, max-age=300' },
  });
}
