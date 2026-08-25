"use client";

import { useState } from "react";

import { getTranscript } from "@/lib/api";
import type { SampleTranscript } from "@/lib/types";

/**
 * Lazy transcript viewer.
 *
 * Fetched on demand rather than with the run detail, because a run can have
 * hundreds of samples and the transcripts live in object storage, not Postgres
 * -- pulling them all eagerly would turn one page load into hundreds of MinIO
 * round trips.
 *
 * This is the evidence half of D-3: every score on the page above is one click
 * away from the exact exchange that produced it.
 */
export function Transcript({
  runId,
  sampleId,
}: {
  runId: string;
  sampleId: string;
}) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<SampleTranscript | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function toggle() {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    if (data || loading) return;
    setLoading(true);
    setError(null);
    try {
      setData(await getTranscript(runId, sampleId));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <button
        onClick={toggle}
        style={{
          background: "none",
          border: "none",
          color: "var(--accent)",
          cursor: "pointer",
          padding: 0,
          font: "inherit",
          fontSize: "0.85rem",
        }}
      >
        {open ? "▾" : "▸"} transcript
      </button>

      {open ? (
        <div style={{ marginTop: "0.5rem" }}>
          {loading ? <p className="muted">Loading…</p> : null}
          {error ? (
            <p style={{ color: "var(--fail)" }} className="mono">
              {error}
            </p>
          ) : null}
          {data ? (
            <>
              {data.messages.map((message, index) => (
                <div key={index} style={{ marginBottom: "0.5rem" }}>
                  <div className="muted" style={{ fontSize: "0.75rem" }}>
                    {message.role}
                  </div>
                  <pre>{message.content}</pre>
                </div>
              ))}
              <div className="muted" style={{ fontSize: "0.75rem" }}>
                completion
              </div>
              <pre>{data.completion}</pre>
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
