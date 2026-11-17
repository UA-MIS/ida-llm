import type { NextRequest } from "next/server";

import { handlers } from "@/auth";
import { adminConsoleEnabled } from "@/lib/admin/env";

/**
 * Auth.js endpoints (`/api/auth/signin/dex`, `/api/auth/callback/dex`, …).
 *
 * With `ADMIN_CONSOLE_ENABLED` unset (base, preview) every one of them is a
 * plain 404, exactly as if the console did not exist.
 */
export const dynamic = "force-dynamic";

const notFound = () => new Response("Not Found", { status: 404 });

export async function GET(request: NextRequest): Promise<Response> {
  return adminConsoleEnabled() ? handlers.GET(request) : notFound();
}

export async function POST(request: NextRequest): Promise<Response> {
  return adminConsoleEnabled() ? handlers.POST(request) : notFound();
}
