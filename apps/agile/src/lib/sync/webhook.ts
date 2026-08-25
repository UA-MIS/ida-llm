import { createHmac, timingSafeEqual } from 'node:crypto';

/**
 * GitHub webhook signature verification.
 *
 * This endpoint is deliberately EXEMPT from the team-membership OAuth gate —
 * GitHub cannot sign in — so the signature is the *entire* authentication
 * story for it. It therefore fails closed on every ambiguity: no secret
 * configured, missing header, wrong prefix, wrong length, or bad digest.
 */
export type SignatureVerdict =
  | { valid: true }
  | { valid: false; reason: 'not-configured' | 'missing-signature' | 'malformed' | 'mismatch' };

export function verifyWebhookSignature(
  rawBody: string | Buffer,
  signatureHeader: string | null | undefined,
  secret: string,
): SignatureVerdict {
  if (!secret) return { valid: false, reason: 'not-configured' };
  if (!signatureHeader) return { valid: false, reason: 'missing-signature' };
  if (!signatureHeader.startsWith('sha256=')) return { valid: false, reason: 'malformed' };

  const provided = signatureHeader.slice('sha256='.length).trim();
  if (!/^[0-9a-f]{64}$/i.test(provided)) return { valid: false, reason: 'malformed' };

  const expected = createHmac('sha256', secret)
    .update(typeof rawBody === 'string' ? Buffer.from(rawBody, 'utf8') : rawBody)
    .digest('hex');

  const a = Buffer.from(provided.toLowerCase(), 'utf8');
  const b = Buffer.from(expected, 'utf8');
  if (a.length !== b.length) return { valid: false, reason: 'malformed' };
  return timingSafeEqual(a, b) ? { valid: true } : { valid: false, reason: 'mismatch' };
}

/** Helper for tests and for the optional self-registration flow. */
export function signWebhookBody(rawBody: string, secret: string): string {
  return `sha256=${createHmac('sha256', secret).update(rawBody, 'utf8').digest('hex')}`;
}
