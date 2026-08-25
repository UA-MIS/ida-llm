import { requireSession } from '@/lib/auth/guard';
import { ensureSchema } from '@/lib/bootstrap';
import { config } from '@/lib/env';
import { serverToday } from '@/lib/clock';
import { getPage } from '@/lib/domain/pages';
import { boardSummary } from '@/lib/domain/summary';
import { renderMarkdown } from '@/lib/markdown';
import { Shell } from '@/components/Shell';
import { Home } from '@/components/Home';

export const dynamic = 'force-dynamic';

/**
 * The landing route: a living README.
 *
 * The board is one click away and remains directly linkable at /board, so daily
 * use never has to bounce through here.
 */
export default async function HomePage() {
  const session = await requireSession('/');
  await ensureSchema();

  const [page, summary] = await Promise.all([getPage(), boardSummary(serverToday())]);

  return (
    <Shell session={session} active="home">
      <Home
        page={page}
        html={renderMarkdown(page.body)}
        summary={summary}
        boardTitle={config.boardTitle}
      />
    </Shell>
  );
}
