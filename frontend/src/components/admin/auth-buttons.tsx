"use client";

/**
 * Sign-in and sign-out buttons. Client components because Auth.js requires a
 * CSRF-tokened POST to start or end a session, and this project uses no
 * Server Actions (design AD-3). `next-auth/react` does the POST; these hold no
 * data and receive only a same-site callback path.
 */

import { signIn, signOut } from "next-auth/react";
import { useState } from "react";

export function SignInButton({ callbackUrl }: { callbackUrl: string }) {
  const [busy, setBusy] = useState(false);
  return (
    <button
      type="button"
      className="adm-btn adm-btn-primary adm-signin-btn"
      disabled={busy}
      onClick={() => {
        setBusy(true);
        void signIn("dex", { callbackUrl }).catch(() => setBusy(false));
      }}
    >
      {busy ? "Opening GitHub…" : "Sign in with GitHub (UA-MIS)"}
    </button>
  );
}

export function SignOutButton() {
  const [busy, setBusy] = useState(false);
  return (
    <button
      type="button"
      className="adm-btn adm-btn-quiet"
      disabled={busy}
      onClick={() => {
        setBusy(true);
        void signOut({ callbackUrl: "/admin/sign-in" }).catch(() => setBusy(false));
      }}
    >
      Sign out
    </button>
  );
}
