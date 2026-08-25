import { withApi } from '@/lib/api/route';
import { ok } from '@/lib/api/respond';
import { boardSummary } from '@/lib/domain/summary';
import { serverToday } from '@/lib/clock';

export const dynamic = 'force-dynamic';

/**
 * GET /api/v1/summary — the auto-generated state of the board.
 * Everything is derived from board data; nothing here is hand-maintained.
 */
export const GET = withApi(async () => ok(await boardSummary(serverToday())));
