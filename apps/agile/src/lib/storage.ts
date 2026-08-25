import { config } from '@/lib/env';

/**
 * Object storage for attachments (MinIO / any S3-compatible endpoint).
 *
 * Attachments never touch the container filesystem — a pod is disposable, so
 * file bytes go to object storage and only metadata goes to Postgres. Requests
 * are signed with SigV4 directly; the app streams bytes through rather than
 * handing out presigned URLs, so the team-membership gate applies to downloads
 * too (an unguessable URL is not an authorization boundary).
 */
import { createHash, createHmac } from 'node:crypto';

function hash(payload: string | Buffer): string {
  return createHash('sha256').update(payload).digest('hex');
}

function hmac(key: Buffer | string, data: string): Buffer {
  return createHmac('sha256', key).update(data, 'utf8').digest();
}

interface SignedRequest {
  url: string;
  headers: Record<string, string>;
}

function signRequest(
  method: string,
  objectKey: string,
  body: Buffer | null,
  extraHeaders: Record<string, string> = {},
): SignedRequest {
  const endpoint = new URL(config.s3Endpoint);
  const bucket = config.s3Bucket;
  const encodedKey = objectKey.split('/').map(encodeURIComponent).join('/');

  // Path-style addressing keeps MinIO happy without per-bucket DNS.
  const path = config.s3ForcePathStyle
    ? `/${bucket}/${encodedKey}`
    : `/${encodedKey}`;
  const host = config.s3ForcePathStyle
    ? endpoint.host
    : `${bucket}.${endpoint.host}`;

  const now = new Date();
  const amzDate = now.toISOString().replace(/[:-]|\.\d{3}/g, '');
  const dateStamp = amzDate.slice(0, 8);
  const payloadHash = hash(body ?? '');

  const headers: Record<string, string> = {
    host,
    'x-amz-content-sha256': payloadHash,
    'x-amz-date': amzDate,
    ...extraHeaders,
  };

  const sortedKeys = Object.keys(headers).sort();
  const canonicalHeaders = sortedKeys.map((k) => `${k.toLowerCase()}:${headers[k]!.trim()}\n`).join('');
  const signedHeaders = sortedKeys.map((k) => k.toLowerCase()).join(';');

  const canonicalRequest = [method, path, '', canonicalHeaders, signedHeaders, payloadHash].join('\n');
  const scope = `${dateStamp}/${config.s3Region}/s3/aws4_request`;
  const stringToSign = ['AWS4-HMAC-SHA256', amzDate, scope, hash(canonicalRequest)].join('\n');

  const signingKey = hmac(
    hmac(hmac(hmac(`AWS4${config.s3SecretAccessKey}`, dateStamp), config.s3Region), 's3'),
    'aws4_request',
  );
  const signature = createHmac('sha256', signingKey).update(stringToSign, 'utf8').digest('hex');

  headers.authorization =
    `AWS4-HMAC-SHA256 Credential=${config.s3AccessKeyId}/${scope}, ` +
    `SignedHeaders=${signedHeaders}, Signature=${signature}`;

  return { url: `${endpoint.protocol}//${host}${path}`, headers };
}

export class StorageError extends Error {}

export async function putObject(
  objectKey: string,
  body: Buffer,
  contentType: string,
): Promise<void> {
  if (!config.attachmentsEnabled) throw new StorageError('Object storage is not configured.');
  const signed = signRequest('PUT', objectKey, body, { 'content-type': contentType });
  const res = await fetch(signed.url, {
    method: 'PUT',
    headers: signed.headers,
    // Wrap in a Blob: the exact bytes we signed, in a type fetch accepts
    // identically in the Node and DOM lib definitions.
    body: new Blob([new Uint8Array(body)], { type: contentType }),
  });
  if (!res.ok) {
    throw new StorageError(`Upload failed (HTTP ${res.status}): ${(await res.text()).slice(0, 200)}`);
  }
}

export async function getObject(objectKey: string): Promise<{ body: ArrayBuffer; contentType: string }> {
  if (!config.attachmentsEnabled) throw new StorageError('Object storage is not configured.');
  const signed = signRequest('GET', objectKey, null);
  const res = await fetch(signed.url, { method: 'GET', headers: signed.headers });
  if (!res.ok) throw new StorageError(`Download failed (HTTP ${res.status}).`);
  return {
    body: await res.arrayBuffer(),
    contentType: res.headers.get('content-type') ?? 'application/octet-stream',
  };
}

export async function deleteObject(objectKey: string): Promise<void> {
  if (!config.attachmentsEnabled) return;
  const signed = signRequest('DELETE', objectKey, null);
  await fetch(signed.url, { method: 'DELETE', headers: signed.headers }).catch(() => undefined);
}

/** Namespaced so several boards can share one bucket without collisions. */
export function attachmentKey(itemId: number, filename: string): string {
  const safe = filename.replace(/[^\w.-]/g, '_').slice(-100);
  const stamp = Date.now().toString(36);
  const instance = config.instanceKey.replace(/[^\w-]/g, '_');
  return `${instance}/items/${itemId}/${stamp}-${safe}`;
}
