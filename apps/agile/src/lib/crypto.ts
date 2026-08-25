import { createCipheriv, createDecipheriv, createHash, hkdfSync, randomBytes } from 'node:crypto';

/**
 * Authenticated encryption helpers shared by the session cookie and by stored
 * GitHub tokens. Each use site passes its own `info` label so keys derived from
 * the same secret are domain-separated and a ciphertext from one context can
 * never be decrypted in another.
 */
const IV_BYTES = 12;
const TAG_BYTES = 16;

function deriveKey(secret: string, info: string): Buffer {
  return Buffer.from(hkdfSync('sha256', Buffer.from(secret), Buffer.alloc(0), info, 32));
}

export function encryptString(plaintext: string, secret: string, info: string): string {
  const iv = randomBytes(IV_BYTES);
  const cipher = createCipheriv('aes-256-gcm', deriveKey(secret, info), iv);
  const ct = Buffer.concat([cipher.update(plaintext, 'utf8'), cipher.final()]);
  return Buffer.concat([iv, ct, cipher.getAuthTag()]).toString('base64url');
}

/** Returns null for a wrong key, a tampered payload, or malformed input. */
export function decryptString(payload: string, secret: string, info: string): string | null {
  if (!payload) return null;
  let raw: Buffer;
  try {
    raw = Buffer.from(payload, 'base64url');
  } catch {
    return null;
  }
  if (raw.length <= IV_BYTES + TAG_BYTES) return null;

  try {
    const decipher = createDecipheriv(
      'aes-256-gcm',
      deriveKey(secret, info),
      raw.subarray(0, IV_BYTES),
    );
    decipher.setAuthTag(raw.subarray(raw.length - TAG_BYTES));
    return Buffer.concat([
      decipher.update(raw.subarray(IV_BYTES, raw.length - TAG_BYTES)),
      decipher.final(),
    ]).toString('utf8');
  } catch {
    return null;
  }
}

export function sha256Hex(value: string): string {
  return createHash('sha256').update(value).digest('hex');
}
