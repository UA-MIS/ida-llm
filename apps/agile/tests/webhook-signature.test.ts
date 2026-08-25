import { describe, it, expect } from 'vitest';
import { verifyWebhookSignature, signWebhookBody } from '@/lib/sync/webhook';

const SECRET = 'a-webhook-secret-value';
const BODY = JSON.stringify({ action: 'opened', number: 7 });

describe('webhook signature verification', () => {
  it('ACCEPTS a correctly signed body', () => {
    expect(verifyWebhookSignature(BODY, signWebhookBody(BODY, SECRET), SECRET)).toEqual({
      valid: true,
    });
  });

  it('REJECTS a missing signature header', () => {
    expect(verifyWebhookSignature(BODY, null, SECRET)).toEqual({
      valid: false,
      reason: 'missing-signature',
    });
    expect(verifyWebhookSignature(BODY, '', SECRET)).toEqual({
      valid: false,
      reason: 'missing-signature',
    });
  });

  it('REJECTS a forged signature', () => {
    const forged = `sha256=${'0'.repeat(64)}`;
    expect(verifyWebhookSignature(BODY, forged, SECRET)).toEqual({
      valid: false,
      reason: 'mismatch',
    });
  });

  it('REJECTS a signature made with the wrong secret', () => {
    const wrong = signWebhookBody(BODY, 'not-the-secret');
    expect(verifyWebhookSignature(BODY, wrong, SECRET)).toEqual({
      valid: false,
      reason: 'mismatch',
    });
  });

  it('REJECTS a valid signature over DIFFERENT bytes (tampered payload)', () => {
    const sig = signWebhookBody(BODY, SECRET);
    const tampered = JSON.stringify({ action: 'opened', number: 8 });
    expect(verifyWebhookSignature(tampered, sig, SECRET)).toEqual({
      valid: false,
      reason: 'mismatch',
    });
  });

  it.each([
    'sha1=abc',
    'abcdef',
    'sha256=',
    'sha256=zzzz',
    `sha256=${'0'.repeat(63)}`,
    `sha256=${'0'.repeat(65)}`,
  ])('REJECTS malformed signature header %j', (header) => {
    const verdict = verifyWebhookSignature(BODY, header, SECRET);
    expect(verdict.valid).toBe(false);
  });

  it('FAILS CLOSED when no secret is configured', () => {
    expect(verifyWebhookSignature(BODY, signWebhookBody(BODY, ''), '')).toEqual({
      valid: false,
      reason: 'not-configured',
    });
  });

  it('is byte-exact: whitespace changes invalidate the signature', () => {
    const sig = signWebhookBody(BODY, SECRET);
    expect(verifyWebhookSignature(` ${BODY}`, sig, SECRET).valid).toBe(false);
  });

  it('accepts an uppercase hex digest', () => {
    const sig = signWebhookBody(BODY, SECRET).toUpperCase().replace('SHA256=', 'sha256=');
    expect(verifyWebhookSignature(BODY, sig, SECRET)).toEqual({ valid: true });
  });
});
