/**
 * The trust tell components, RENDERED.
 *
 * ⚠ QA-24. `ConfidenceTell` used to render `<span className="confidence"
 * aria-label={...}>` with no role. A bare `<span>` is `role="generic"` in the
 * accessibility tree, and `role="generic"` is one of the ARIA roles that
 * PROHIBITS an author-supplied accessible name — conforming assistive
 * technology drops `aria-label` on a generic element rather than announcing
 * it, so the confidence reason was silently unreachable by screen reader
 * despite being right there in the markup. `score-bar.tsx`'s `.scorebar-track`
 * already used the fix (`role="img"`), which is why that one worked.
 */

import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ConfidenceTell } from "@/components/trust-badges";

afterEach(cleanup);

describe("ConfidenceTell", () => {
  it("exposes its label and reason with a role that actually permits an accessible name", () => {
    const { container } = render(
      <ConfidenceTell confidence="low" label="Low confidence" reason="Only four samples." />,
    );
    const meter = container.querySelector(".confidence")!;
    expect(meter, "no .confidence element rendered").not.toBeNull();

    // role="generic" (the default for a bare <span>) prohibits aria-label from
    // being exposed at all — the element must carry a role that permits one.
    expect(meter.getAttribute("role"), "no role, or an implicit generic role").not.toBeNull();
    expect(meter.getAttribute("role")).not.toBe("generic");

    const label = meter.getAttribute("aria-label") ?? "";
    expect(label).toContain("Low confidence");
    expect(label).toContain("Only four samples.");
  });
});
