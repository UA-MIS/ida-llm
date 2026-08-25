/**
 * Per-principal token bucket.
 *
 * Deliberately generous: this exists to stop a runaway loop, not to fight a
 * scripted burst — an agent seeding a sprint's worth of stories should never
 * hit it. State is in-memory on purpose; it is not durable data, and losing it
 * when a pod restarts is harmless.
 */
const CAPACITY = Number(process.env.RATE_LIMIT_BURST ?? 240);
const REFILL_PER_SECOND = Number(process.env.RATE_LIMIT_PER_SECOND ?? 8);

interface Bucket {
  tokens: number;
  updatedAt: number;
}

const buckets = new Map<string, Bucket>();

export function resetRateLimits(): void {
  buckets.clear();
}

export interface RateVerdict {
  allowed: boolean;
  remaining: number;
  retryAfterSeconds: number;
}

export function consume(key: string, now: number = Date.now(), cost = 1): RateVerdict {
  const bucket = buckets.get(key) ?? { tokens: CAPACITY, updatedAt: now };
  const elapsedSeconds = Math.max(0, (now - bucket.updatedAt) / 1000);
  const tokens = Math.min(CAPACITY, bucket.tokens + elapsedSeconds * REFILL_PER_SECOND);

  if (tokens < cost) {
    buckets.set(key, { tokens, updatedAt: now });
    return {
      allowed: false,
      remaining: 0,
      retryAfterSeconds: Math.max(1, Math.ceil((cost - tokens) / REFILL_PER_SECOND)),
    };
  }

  buckets.set(key, { tokens: tokens - cost, updatedAt: now });
  return { allowed: true, remaining: Math.floor(tokens - cost), retryAfterSeconds: 0 };
}
