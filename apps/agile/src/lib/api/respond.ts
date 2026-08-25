import { z } from 'zod';

/**
 * One JSON error shape for the whole API, so a machine client can branch on
 * `code` and a human (or an LLM) gets a message that says what to do next.
 */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    /** Field-level detail for validation failures: { field: [messages] }. */
    fields?: Record<string, string[]>;
  };
}

export function apiError(
  code: string,
  message: string,
  status: number,
  fields?: Record<string, string[]>,
): Response {
  const body: ApiErrorBody = { error: { code, message, ...(fields ? { fields } : {}) } };
  return Response.json(body, { status });
}

export function validationError(err: z.ZodError): Response {
  const fields: Record<string, string[]> = {};
  for (const issue of err.issues) {
    const key = issue.path.length ? issue.path.join('.') : '_';
    (fields[key] ??= []).push(issue.message);
  }
  const first = Object.entries(fields)[0];
  const hint = first ? ` (${first[0]}: ${first[1]![0]})` : '';
  return apiError('validation_failed', `The request body is not valid${hint}.`, 422, fields);
}

export function ok<T>(data: T, status = 200, headers?: Record<string, string>): Response {
  return Response.json(data, { status, headers });
}

/** Parses a JSON body, returning a 400 Response instead of throwing. */
export async function readJson(request: Request): Promise<{ ok: true; value: unknown } | { ok: false; response: Response }> {
  try {
    return { ok: true, value: await request.json() };
  } catch {
    return {
      ok: false,
      response: apiError('invalid_json', 'Request body must be valid JSON.', 400),
    };
  }
}

export function parseId(raw: string): number | null {
  const n = Number(raw);
  return Number.isInteger(n) && n > 0 ? n : null;
}
