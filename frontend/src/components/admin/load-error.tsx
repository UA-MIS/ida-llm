import Link from "next/link";

/**
 * What an admin page shows when it cannot load its data. Written for staff,
 * not engineers: say what happened, what it means, and what to do next. The
 * technical cause sits behind a disclosure for whoever is on call.
 */

type LoadFailure = { status?: number; error?: { code?: string; message?: string } | null; message?: string };

function explain(err: LoadFailure): { title: string; body: string } {
  const status = err.status ?? -1;
  const code = err.error?.code;
  if (status === 0) {
    return { title: "The admin service could not be reached", body: "The website could not talk to the service that stores its settings. This is usually temporary. Try again in a minute." };
  }
  if (status === 503 || code === "admin_disabled") {
    return { title: "The admin service is not switched on yet", body: "The settings service has not been given its admin key. An operator needs to finish setting it up." };
  }
  if (status === 404 || status === 405) {
    return { title: "This section is not available yet", body: "The settings service does not offer this feature yet. It will appear here once that part has been deployed." };
  }
  if (status === 401 || status === 403) {
    return { title: "The admin service refused the request", body: "The website's admin key was not accepted. An operator needs to check the admin token configuration." };
  }
  return { title: "Something went wrong loading this page", body: "Nothing you did caused this. Try again; if it keeps happening, tell an operator." };
}

export function LoadError({ error, retryHref }: { error: unknown; retryHref: string }) {
  const err = (error ?? {}) as LoadFailure;
  const { title, body } = explain(err);
  return (
    <div className="adm-panel adm-panel-error" role="alert">
      <h2 className="adm-panel-title">{title}</h2>
      <p>{body}</p>
      <p>
        <Link href={retryHref} className="adm-btn adm-btn-secondary">
          Try again
        </Link>
      </p>
      <details className="adm-detail">
        <summary>Technical detail</summary>
        <p className="mono">
          {err.status !== undefined ? `HTTP ${err.status}. ` : ""}
          {err.error?.code ? `${err.error.code}: ` : ""}
          {err.error?.message ?? err.message ?? ""}
        </p>
      </details>
    </div>
  );
}
