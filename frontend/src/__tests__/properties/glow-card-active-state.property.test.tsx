/**
 * Feature: digital-twin-v1.4, Property 7: Active State CSS Class Toggle
 *
 * For any glowColor in ['cyan','violet','emerald','none']:
 * - When isActive transitions from false to true, the glow-pulse-{color} class
 *   must be present (unless glowColor is 'none').
 * - When isActive is false, no glow-pulse class is present.
 *
 * **Validates: Requirements 8.2**
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import * as fc from "fast-check";
import { render } from "@testing-library/react";
import React from "react";
import { GlowCard } from "@/components/ui/GlowCard";

// --- Arbitraries ---

const glowColorArb = fc.constantFrom("cyan", "violet", "emerald", "none") as fc.Arbitrary<
  "cyan" | "violet" | "emerald" | "none"
>;

// --- Property 7: Active State CSS Class Toggle ---

describe("Feature: digital-twin-v1.4, Property 7: Active State CSS Class Toggle", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("isActive=true after transition → glow-pulse-{color} class present (unless glowColor='none')", () => {
    fc.assert(
      fc.property(glowColorArb, (glowColor) => {
        // Render initially with isActive=false, then transition to true
        const { container, rerender } = render(
          <GlowCard isActive={false} glowColor={glowColor}>
            <p>content</p>
          </GlowCard>
        );

        // Transition to active
        rerender(
          <GlowCard isActive={true} glowColor={glowColor}>
            <p>content</p>
          </GlowCard>
        );

        const el = container.firstElementChild as HTMLElement;

        if (glowColor === "none") {
          // No glow-pulse class should be present for "none"
          expect(el.className).not.toMatch(/glow-pulse/);
        } else {
          // The glow-pulse-{color} class must be present
          expect(el.className).toContain(`glow-pulse-${glowColor}`);
        }
      }),
      { numRuns: 100 }
    );
  });

  it("isActive=false → no glow-pulse class present for any glowColor", () => {
    fc.assert(
      fc.property(glowColorArb, (glowColor) => {
        const { container } = render(
          <GlowCard isActive={false} glowColor={glowColor}>
            <p>content</p>
          </GlowCard>
        );

        const el = container.firstElementChild as HTMLElement;

        // No glow-pulse class should exist when isActive is false
        expect(el.className).not.toMatch(/glow-pulse/);
      }),
      { numRuns: 100 }
    );
  });

  it("isActive=true → static glow-{color} class present; isActive=false → absent", () => {
    fc.assert(
      fc.property(glowColorArb, (glowColor) => {
        // Render with isActive=true
        const { container: activeContainer } = render(
          <GlowCard isActive={true} glowColor={glowColor}>
            <p>active</p>
          </GlowCard>
        );

        const activeEl = activeContainer.firstElementChild as HTMLElement;

        if (glowColor === "none") {
          // No static glow class for "none"
          expect(activeEl.className).not.toMatch(/glow-cyan|glow-violet|glow-emerald/);
        } else {
          // Static glow class must be present
          expect(activeEl.className).toContain(`glow-${glowColor}`);
        }

        // Render with isActive=false
        const { container: inactiveContainer } = render(
          <GlowCard isActive={false} glowColor={glowColor}>
            <p>inactive</p>
          </GlowCard>
        );

        const inactiveEl = inactiveContainer.firstElementChild as HTMLElement;

        // Static glow class must be absent when inactive
        if (glowColor !== "none") {
          expect(inactiveEl.className).not.toContain(`glow-${glowColor}`);
        }
      }),
      { numRuns: 100 }
    );
  });
});
