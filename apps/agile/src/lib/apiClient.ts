/**
 * The browser's entry point to the API.
 *
 * The UI calls the SAME public endpoints an external agent calls — there is no
 * privileged internal route — so anything the board can do is reachable with a
 * token, and the two can never drift apart.
 */
export const API_BASE = '/api/v1';

export interface ApiFailure {
  code: string;
  message: string;
  fields?: Record<string, string[]>;
}

export class ApiError extends Error {
  constructor(
    readonly failure: ApiFailure,
    readonly status: number,
  ) {
    super(failure.message);
    this.name = 'ApiError';
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init.body && !(init.body instanceof FormData) ? { 'content-type': 'application/json' } : {}),
      ...(init.headers ?? {}),
    },
  });

  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    // Fall through to a generic error below.
  }

  if (!res.ok) {
    const failure = (body as { error?: ApiFailure } | null)?.error;
    throw new ApiError(
      failure ?? { code: 'unexpected', message: `Request failed (HTTP ${res.status}).` },
      res.status,
    );
  }
  return body as T;
}
