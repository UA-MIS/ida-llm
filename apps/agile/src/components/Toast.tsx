'use client';

import { createContext, useCallback, useContext, useEffect, useState } from 'react';

/**
 * Minimal toast system. Errors from optimistic actions surface here instead of
 * a banner that shifts the layout, so a failed drag explains itself without the
 * board jumping under the cursor.
 */
export interface ToastMessage {
  id: number;
  text: string;
  tone: 'ok' | 'error' | 'info';
  /** Optional follow-up action, e.g. "Undo" or "Open branch". */
  action?: { label: string; href?: string; onClick?: () => void };
}

const ToastContext = createContext<{
  push: (t: Omit<ToastMessage, 'id'>) => void;
}>({ push: () => {} });

export function useToast() {
  return useContext(ToastContext);
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const push = useCallback((t: Omit<ToastMessage, 'id'>) => {
    setToasts((prev) => [...prev, { ...t, id: Date.now() + Math.floor(performance.now() % 1000) }]);
  }, []);

  return (
    <ToastContext.Provider value={{ push }}>
      {children}
      <div className="toast-wrap" role="status" aria-live="polite">
        {toasts.map((t) => (
          <Toast key={t.id} toast={t} onDone={() => setToasts((p) => p.filter((x) => x.id !== t.id))} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function Toast({ toast, onDone }: { toast: ToastMessage; onDone: () => void }) {
  useEffect(() => {
    // Errors linger; successes get out of the way.
    const ms = toast.tone === 'error' ? 8000 : 3500;
    const timer = setTimeout(onDone, ms);
    return () => clearTimeout(timer);
  }, [toast.tone, onDone]);

  return (
    <div className={`toast toast-${toast.tone}`}>
      <span style={{ flex: 1 }}>{toast.text}</span>
      {toast.action ? (
        toast.action.href ? (
          <a className="btn btn-sm" href={toast.action.href} target="_blank" rel="noopener noreferrer">
            {toast.action.label}
          </a>
        ) : (
          <button className="btn btn-sm" onClick={toast.action.onClick}>
            {toast.action.label}
          </button>
        )
      ) : null}
      <button className="btn btn-sm btn-ghost" onClick={onDone} aria-label="Dismiss">
        &#10005;
      </button>
    </div>
  );
}
