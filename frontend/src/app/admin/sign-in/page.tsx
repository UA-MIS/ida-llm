import { notFound, redirect } from "next/navigation";

import { auth } from "@/auth";
import { SignInButton } from "@/components/admin/auth-buttons";
import { adminConfigProblems, adminConsoleEnabled } from "@/lib/admin/env";
import { adminFromSession, safeCallbackUrl } from "@/lib/admin/session";

/**
 * The public face of `/admin`: one button, no data. It is exempt from
 * `requireAdmin()` because it is where `requireAdmin()` sends people.
 */
export const dynamic = "force-dynamic";

export default async function SignInPage({
  searchParams,
}: {
  searchParams: Promise<{ callbackUrl?: string; error?: string }>;
}) {
  if (!adminConsoleEnabled()) notFound();
  const params = await searchParams;
  const callbackUrl = safeCallbackUrl(params.callbackUrl);
  const problems = adminConfigProblems();

  if (!problems.length && adminFromSession(await auth())) redirect(callbackUrl);

  return (
    <main id="admin-main" className="adm-auth">
      <div className="adm-auth-card">
        <span className="brand-mark" aria-hidden="true">
          <span className="brand-dot" />
        </span>
        <h1>Coursework Benchmark admin</h1>
        {problems.length ? (
          <div className="adm-panel adm-panel-error" role="alert">
            <h2 className="adm-panel-title">Sign-in is not set up correctly</h2>
            <p>The admin console is missing some of its settings, so nobody can sign in yet. Please pass this to an operator:</p>
            <ul className="mono">
              {problems.map((p) => (
                <li key={p}>admin console misconfigured: {p}</li>
              ))}
            </ul>
          </div>
        ) : (
          <>
            <p>
              Sign in with your GitHub account. You need to be a member of the UA-MIS organisation&apos;s{" "}
              <strong>ida-llm</strong> team.
            </p>
            <SignInButton callbackUrl={callbackUrl} />
            <p className="adm-fine">You will be sent to GitHub to confirm, then brought back here.</p>
          </>
        )}
      </div>
    </main>
  );
}
