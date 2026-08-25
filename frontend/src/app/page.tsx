/**
 * SCAFFOLDING. A deliberately minimal landing page whose only job is to make the
 * deploy path provable end to end: it renders, the container serves it, the
 * readiness probe passes, and the Ingress routes to it. Replace it wholesale.
 *
 * It does NOT call the API. The api Deployment has no public Ingress (internal
 * only, by design), so a browser cannot reach it directly -- server components or
 * route handlers talk to `http://ida-llm-api` in-cluster. Wiring that up is the
 * project's own first task.
 */
export default function Home() {
  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: "3rem", lineHeight: 1.6 }}>
      <h1>IDA-LLM</h1>
      <p>LLM benchmark harness and results platform.</p>
      <p style={{ color: "#666" }}>
        Scaffolding. The deploy path is live; the application is not written yet.
      </p>
    </main>
  );
}
