import { requireSession } from '@/lib/auth/guard';
import { ensureSchema } from '@/lib/bootstrap';
import { config } from '@/lib/env';
import { listApiTokens } from '@/lib/auth/tokens';
import { Shell } from '@/components/Shell';
import { Tokens } from '@/components/Tokens';

export const dynamic = 'force-dynamic';

export default async function TokensPage() {
  const session = await requireSession('/tokens');
  await ensureSchema();
  const tokens = await listApiTokens(session.login);

  return (
    <Shell session={session} active="tokens">
      <Tokens initialTokens={tokens} appUrl={config.appUrl} docsPath="/docs/api" />
    </Shell>
  );
}
