import { withApi } from '@/lib/api/route';
import { apiError, ok, parseId } from '@/lib/api/respond';
import { config } from '@/lib/env';
import { getWorkItem, listAttachments, recordAttachment } from '@/lib/domain/queries';
import { attachmentKey, putObject, StorageError } from '@/lib/storage';

export const dynamic = 'force-dynamic';

export const GET = withApi(async ({ params }) => {
  const id = parseId(params.id ?? '');
  if (!id) return apiError('invalid_id', 'Work item id must be a positive integer.', 400);
  return ok({ attachments: await listAttachments(id), enabled: config.attachmentsEnabled });
});

/**
 * POST /api/v1/items/{id}/attachments — multipart upload.
 * Bytes go to object storage; only metadata is written to Postgres.
 */
export const POST = withApi(async ({ request, params, principal }) => {
  const id = parseId(params.id ?? '');
  if (!id) return apiError('invalid_id', 'Work item id must be a positive integer.', 400);
  if (!config.attachmentsEnabled) {
    return apiError(
      'attachments_disabled',
      'Attachments require object storage; set MINIO_ENDPOINT/MINIO_BUCKET and credentials.',
      501,
    );
  }
  if (!(await getWorkItem(id))) return apiError('not_found', `Work item #${id} does not exist.`, 404);

  let form: FormData;
  try {
    form = await request.formData();
  } catch {
    return apiError('invalid_form', 'Expected a multipart/form-data body with a "file" field.', 400);
  }

  const file = form.get('file');
  if (!(file instanceof File)) {
    return apiError('missing_file', 'A "file" field is required.', 422);
  }
  if (file.size > config.maxUploadBytes) {
    return apiError(
      'file_too_large',
      `That file is ${(file.size / 1048576).toFixed(1)} MB; the limit is ${(config.maxUploadBytes / 1048576).toFixed(0)} MB.`,
      413,
    );
  }

  const key = attachmentKey(id, file.name || 'upload.bin');
  try {
    await putObject(key, Buffer.from(await file.arrayBuffer()), file.type || 'application/octet-stream');
  } catch (err) {
    if (err instanceof StorageError) {
      return apiError('storage_unavailable', err.message, 502);
    }
    throw err;
  }

  const attachment = await recordAttachment(id, {
    objectKey: key,
    filename: file.name || 'upload.bin',
    contentType: file.type || 'application/octet-stream',
    sizeBytes: file.size,
    uploadedBy: principal.login,
  });

  return ok({ attachment }, 201);
});
