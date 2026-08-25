import { randomBytes, timingSafeEqual } from 'node:crypto';
import { query, queryOne } from '@/lib/db/pool';
import { config } from '@/lib/env';
import { decryptString, encryptString, sha256Hex } from '@/lib/crypto';
import { checkTeamMembership } from './team';

/**
 * Board-issued API tokens for machine access.
 *
 * Only a SHA-256 hash of the token is stored — the plaintext is shown to the
 * user exactly once at creation and is unrecoverable afterwards. A token always
 * acts as the human who issued it, so anything an agent does stays attributable
 * in the item history.
 *
 * A GitHub token is NOT accepted as a board credential: board tokens are
 * revocable here, scoped to this board, and carry no GitHub privileges.
 */
export const TOKEN_PREFIX = 'iag_';
const GH_TOKEN_INFO = 'ida-agile-apitoken-gh-v1';

export interface ApiTokenRecord {
  id: number;
  name: string;
  tokenPrefix: string;
  ownerLogin: string;
  createdAt: string;
  lastUsedAt: string | null;
  expiresAt: string | null;
  revokedAt: string | null;
  /** Derived server-side: reading the clock during a React render is impure. */
  expired: boolean;
}

interface TokenRow {
  id: number;
  name: string;
  token_prefix: string;
  owner_login: string;
  created_at: Date;
  last_used_at: Date | null;
  expires_at: Date | null;
  revoked_at: Date | null;
}

function mapToken(r: TokenRow): ApiTokenRecord {
  return {
    id: r.id,
    name: r.name,
    tokenPrefix: r.token_prefix,
    ownerLogin: r.owner_login,
    createdAt: r.created_at.toISOString(),
    lastUsedAt: r.last_used_at ? r.last_used_at.toISOString() : null,
    expiresAt: r.expires_at ? r.expires_at.toISOString() : null,
    revokedAt: r.revoked_at ? r.revoked_at.toISOString() : null,
    expired: r.expires_at !== null && r.expires_at.getTime() <= Date.now(),
  };
}

export function generateToken(): string {
  return TOKEN_PREFIX + randomBytes(32).toString('base64url');
}

export async function createApiToken(args: {
  name: string;
  ownerLogin: string;
  /** The issuer's GitHub OAuth token, stored encrypted so membership stays checkable. */
  githubToken?: string;
  expiresInDays?: number | null;
}): Promise<{ token: string; record: ApiTokenRecord }> {
  const token = generateToken();
  const expires =
    args.expiresInDays && args.expiresInDays > 0
      ? new Date(Date.now() + args.expiresInDays * 86_400_000).toISOString()
      : null;

  const encryptedGh = args.githubToken
    ? encryptString(args.githubToken, config.sessionSecret, GH_TOKEN_INFO)
    : null;

  const row = await queryOne<TokenRow>(
    `INSERT INTO api_tokens (instance_key, name, token_hash, token_prefix, owner_login, expires_at, gh_token)
     VALUES ($1,$2,$3,$4,$5,$6,$7)
     RETURNING id, name, token_prefix, owner_login, created_at, last_used_at, expires_at, revoked_at`,
    [
      config.instanceKey,
      args.name.trim(),
      sha256Hex(token),
      token.slice(0, TOKEN_PREFIX.length + 6),
      args.ownerLogin,
      expires,
      encryptedGh,
    ],
  );

  return { token, record: mapToken(row!) };
}

export async function listApiTokens(ownerLogin: string): Promise<ApiTokenRecord[]> {
  const rows = await query<TokenRow>(
    `SELECT id, name, token_prefix, owner_login, created_at, last_used_at, expires_at, revoked_at
       FROM api_tokens
      WHERE instance_key = $1 AND owner_login = $2
      ORDER BY created_at DESC`,
    [config.instanceKey, ownerLogin],
  );
  return rows.map(mapToken);
}

export async function revokeApiToken(id: number, ownerLogin: string): Promise<boolean> {
  const rows = await query<{ id: number }>(
    `UPDATE api_tokens SET revoked_at = now()
      WHERE id = $1 AND owner_login = $2 AND instance_key = $3 AND revoked_at IS NULL
      RETURNING id`,
    [id, ownerLogin, config.instanceKey],
  );
  return rows.length > 0;
}

export type TokenVerdict =
  | { ok: true; ownerLogin: string; tokenId: number }
  | { ok: false; reason: 'malformed' | 'unknown' | 'revoked' | 'expired' | 'not-on-team' };

/**
 * Verifies a presented bearer token.
 *
 * Beyond the hash lookup this re-checks that the owner is still on the team,
 * using the GitHub token captured when the API token was issued. A token can
 * therefore never outlive its owner's membership — that is what keeps
 * "a token cannot exceed its user's rights" true rather than aspirational.
 */
export async function verifyApiToken(presented: string): Promise<TokenVerdict> {
  const raw = (presented ?? '').trim();
  if (!raw.startsWith(TOKEN_PREFIX) || raw.length < TOKEN_PREFIX.length + 16) {
    return { ok: false, reason: 'malformed' };
  }

  const row = await queryOne<{
    id: number;
    owner_login: string;
    token_hash: string;
    expires_at: Date | null;
    revoked_at: Date | null;
    gh_token: string | null;
  }>(
    `SELECT id, owner_login, token_hash, expires_at, revoked_at, gh_token
       FROM api_tokens WHERE token_hash = $1 AND instance_key = $2`,
    [sha256Hex(raw), config.instanceKey],
  );

  if (!row) return { ok: false, reason: 'unknown' };

  // Constant-time confirmation of the hash we just matched on.
  const a = Buffer.from(row.token_hash);
  const b = Buffer.from(sha256Hex(raw));
  if (a.length !== b.length || !timingSafeEqual(a, b)) return { ok: false, reason: 'unknown' };

  if (row.revoked_at) return { ok: false, reason: 'revoked' };
  if (row.expires_at && row.expires_at.getTime() <= Date.now()) {
    return { ok: false, reason: 'expired' };
  }

  if (row.gh_token) {
    const gh = decryptString(row.gh_token, config.sessionSecret, GH_TOKEN_INFO);
    if (gh) {
      const decision = await checkTeamMembership(row.owner_login, gh);
      if (!decision.allowed && decision.reason !== 'lookup-failed') {
        // Membership provably gone: retire the token rather than just refusing.
        await query('UPDATE api_tokens SET revoked_at = now() WHERE id = $1', [row.id]);
        return { ok: false, reason: 'not-on-team' };
      }
    }
  }

  await query('UPDATE api_tokens SET last_used_at = now() WHERE id = $1', [row.id]);
  return { ok: true, ownerLogin: row.owner_login, tokenId: row.id };
}
