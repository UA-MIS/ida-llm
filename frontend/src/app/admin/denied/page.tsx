import Link from "next/link";
import { notFound } from "next/navigation";

import { DEFAULT_ADMIN_GROUPS, adminConsoleEnabled, adminEnv } from "@/lib/admin/env";

/**
 * Where a non-member, or a failed sign-in, lands. No data and no session:
 * a denied person never received a cookie. The `login` shown comes from the
 * query string, so it is validated as a GitHub login before it is printed.
 */
export const dynamic = "force-dynamic";

const LOGIN = /^[A-Za-z0-9-]{1,39}$/;

function groups(): string[] {
  try {
    return adminEnv().ADMIN_GROUPS;
  } catch {
    return DEFAULT_ADMIN_GROUPS;
  }
}

export default async function DeniedPage({
  searchParams,
}: {
  searchParams: Promise<{ login?: string; error?: string }>;
}) {
  if (!adminConsoleEnabled()) notFound();
  const params = await searchParams;
  const login = typeof params.login === "string" && LOGIN.test(params.login) ? params.login : null;
  const team = groups().join(" or ");

  let title: string;
  let body: React.ReactNode;
  if (login) {
    title = "You don't have admin access";
    body = (
      <p>
        You are signed in to GitHub as <strong>@{login}</strong>, but that account is not in the <strong>{team}</strong>{" "}
        team. Ask a team maintainer to add you, then sign in again.
      </p>
    );
  } else if (params.error === "Configuration") {
    title = "Sign-in is not set up correctly";
    body = <p>The sign-in service rejected the website&apos;s settings. Please let an operator know.</p>;
  } else if (params.error === "AccessDenied" || !params.error) {
    title = "You don't have admin access";
    body = (
      <p>
        Your GitHub account is not in the <strong>{team}</strong> team, or GitHub did not share your team membership.
        Ask a team maintainer to add you, then sign in again.
      </p>
    );
  } else {
    title = "Sign-in did not finish";
    body = <p>Something interrupted the sign-in. This is usually temporary, so please try again.</p>;
  }

  return (
    <main id="admin-main" className="adm-auth">
      <div className="adm-auth-card">
        <h1>{title}</h1>
        {body}
        <p>
          <Link href="/admin/sign-in" className="adm-btn adm-btn-secondary">
            Back to sign in
          </Link>
        </p>
      </div>
    </main>
  );
}
