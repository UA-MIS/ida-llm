"use client";

/**
 * A button that asks before doing something destructive. Uses the native
 * `<dialog>` (focus trap, Escape to cancel, no library). For the most
 * dangerous actions, `typeToConfirm` makes the person type a word first.
 */

import { useRef, useState } from "react";

export function ConfirmButton({
  label,
  title,
  body,
  confirmLabel,
  typeToConfirm,
  danger = true,
  small = false,
  disabled = false,
  onConfirm,
}: {
  label: string;
  title: string;
  body: React.ReactNode;
  confirmLabel: string;
  typeToConfirm?: string;
  danger?: boolean;
  small?: boolean;
  disabled?: boolean;
  /** Return an error message to keep the dialog open and show it; nothing on success. */
  onConfirm: () => Promise<string | void>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<string | null>(null);

  const open = () => {
    setTyped("");
    setError(null);
    const d = dialog.current;
    if (!d) return;
    if (typeof d.showModal === "function") d.showModal();
    else d.setAttribute("open", ""); // very old browsers and jsdom
  };
  const close = () => {
    const d = dialog.current;
    if (!d) return;
    if (typeof d.close === "function") d.close();
    else d.removeAttribute("open");
  };
  const ready = !typeToConfirm || typed.trim() === typeToConfirm;

  return (
    <>
      <button
        type="button"
        className={`adm-btn ${danger ? "adm-btn-danger" : "adm-btn-secondary"} ${small ? "adm-btn-small" : ""}`}
        onClick={open}
        disabled={disabled}
      >
        {label}
      </button>
      <dialog ref={dialog} className="adm-dialog" aria-labelledby="adm-confirm-title">
        <h2 id="adm-confirm-title">{title}</h2>
        <div>{body}</div>
        {typeToConfirm ? (
          <div className="adm-field" style={{ marginTop: "0.75rem" }}>
            <label className="adm-label" htmlFor="adm-confirm-typed">
              Type <span className="mono">{typeToConfirm}</span> to confirm
            </label>
            <input id="adm-confirm-typed" className="adm-input" value={typed} autoComplete="off" onChange={(e) => setTyped(e.target.value)} />
          </div>
        ) : null}
        {error ? (
          <p className="adm-field-error" role="alert">
            {error}
          </p>
        ) : null}
        <div className="adm-actions">
          <button
            type="button"
            className={`adm-btn ${danger ? "adm-btn-danger-solid" : "adm-btn-primary"}`}
            disabled={busy || !ready}
            onClick={async () => {
              setBusy(true);
              const problem = await onConfirm();
              setBusy(false);
              if (problem) setError(problem);
              else close();
            }}
          >
            {busy ? "Working…" : confirmLabel}
          </button>
          <button type="button" className="adm-btn adm-btn-quiet" onClick={close} disabled={busy}>
            Cancel
          </button>
        </div>
      </dialog>
    </>
  );
}
