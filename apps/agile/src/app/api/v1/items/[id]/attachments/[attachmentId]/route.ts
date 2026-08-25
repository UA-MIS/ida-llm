import { withApi } from '@/lib/api/route';
import { apiError, ok, parseId } from '@/lib/api/respond';
import { deleteAttachment, getAttachment } from '@/lib/domain/queries';
import { deleteObject, getObject, StorageError } from '@/lib/storage';

export const dynamic = 'force-dynamic';

/**
 * GET — streams the file back through the app, so the same team-membership
 * gate that protects the board also protects its attachments.
 */
export const GET = withApi(async ({ params }) => {
  const id = parseId(params.id ?? '');
  const attachmentId = parseId(params.attachmentId ?? '');
  if (!id || !attachmentId) return apiError('invalid_id', 'Invalid item or attachment id.', 400);

  const meta = await getAttachment(id, attachmentId);
  if (!meta) return apiError('not_found', 'That attachment does not exist.', 404);

  try {
    const object = await getObject(meta.objectKey);
    return new Response(object.body, {
      headers: {
        'content-type': meta.contentType || object.contentType,
        'content-disposition': `attachment; filename="${meta.filename.replace(/"/g, '')}"`,
        'cache-control': 'private, max-age=300',
      },
    });
  } catch (err) {
    if (err instanceof StorageError) return apiError('storage_unavailable', err.message, 502);
    throw err;
  }
});

export const DELETE = withApi(async ({ params }) => {
  const id = parseId(params.id ?? '');
  const attachmentId = parseId(params.attachmentId ?? '');
  if (!id || !attachmentId) return apiError('invalid_id', 'Invalid item or attachment id.', 400);

  const objectKey = await deleteAttachment(id, attachmentId);
  if (!objectKey) return apiError('not_found', 'That attachment does not exist.', 404);
  // Metadata is gone; a failed object delete leaves only an orphan blob.
  await deleteObject(objectKey);
  return ok({ deleted: attachmentId });
});
