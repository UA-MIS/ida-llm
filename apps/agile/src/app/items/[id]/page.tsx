import { notFound } from 'next/navigation';
import { requireSession } from '@/lib/auth/guard';
import { ensureSchema } from '@/lib/bootstrap';
import { config } from '@/lib/env';
import {
  getWorkItem,
  listActivity,
  listAttachments,
  listComments,
  listSprints,
} from '@/lib/domain/queries';
import { listOpenPullRequests, listTeamMembers } from '@/lib/github/client';
import { githubReadToken } from '@/lib/github/credential';
import { extractWorkItemRefs } from '@/lib/github/prs';
import { reconcileItem } from '@/lib/sync/poller';
import { renderMarkdown } from '@/lib/markdown';
import { Shell } from '@/components/Shell';
import { ItemDetail } from '@/components/ItemDetail';

export const dynamic = 'force-dynamic';

export default async function ItemPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: rawId } = await params;
  const id = Number(rawId);
  if (!Number.isInteger(id) || id <= 0) notFound();

  const session = await requireSession(`/items/${rawId}`);
  await ensureSchema();
  const ghToken = githubReadToken({ githubToken: session.token || null });

  const existing = await getWorkItem(id);
  if (!existing) notFound();

  // On-view reconciliation: without webhooks configured this is what keeps the
  // item current. It self-throttles, so opening the page repeatedly is cheap.
  if (!config.webhooksEnabled) {
    await reconcileItem(existing, ghToken).catch(() => undefined);
  }

  const item = (await getWorkItem(id)) ?? existing;

  const [comments, activity, attachments, sprints, members, openPrs] = await Promise.all([
    listComments(id),
    listActivity(id),
    listAttachments(id),
    listSprints(),
    listTeamMembers(ghToken ?? ''),
    listOpenPullRequests(ghToken ?? ''),
  ]);

  return (
    <Shell session={session} active="item">
      <ItemDetail
        initialItem={item}
        descriptionHtml={renderMarkdown(item.description)}
        comments={comments}
        activity={activity}
        attachments={attachments}
        sprints={sprints}
        members={members}
        openPrs={openPrs.map((pr) => ({
          ...pr,
          suggestedItemIds: extractWorkItemRefs(pr.title, pr.body),
        }))}
        currentUser={{ login: session.login, avatarUrl: session.avatarUrl }}
        autoBranch={config.autoBranch}
        attachmentsEnabled={config.attachmentsEnabled}
      />
    </Shell>
  );
}
