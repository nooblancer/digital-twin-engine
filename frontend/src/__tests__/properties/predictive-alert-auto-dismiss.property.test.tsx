/**
 * Feature: digital-twin-v1.4, Property 10: Auto-Dismiss Timing
 *
 * For any alert severity, the auto-dismiss behavior must follow:
 * - low severity → auto-dismissed after 10 seconds
 * - medium severity → auto-dismissed after 30 seconds
 * - critical severity → persists (never auto-dismissed)
 *
 * Uses fake timers to verify timing behavior deterministically.
 *
 * **Validates: Requirements 13.5**
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import * as fc from "fast-check";
import { render, act, cleanup } from "@testing-library/react";
import React from "react";

// Mock framer-motion to avoid animation complexity in property tests
vi.mock("framer-motion", () => ({
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  motion: {
    div: React.forwardRef(
      (
        { children, ...props }: React.HTMLAttributes<HTMLDivElement> & { children?: React.ReactNode },
        ref: React.Ref<HTMLDivElement>
      ) => (
        <div ref={ref} {...props}>
          {children}
        </div>
      )
    ),
  },
}));

// Mock the store to avoid needing full Zustand setup
vi.mock("@/store", () => ({
  useStore: (selector: (s: Record<string, unknown>) => unknown) =>
    selector({
      engines: {},
      addPredictiveAlert: () => {},
    }),
}));

import { PredictiveAlertNotification } from "@/components/dashboard/PredictiveAlertNotification";
import type { PredictiveAlert, AlertSeverity } from "@/types/mission-control";

// --- Arbitraries ---

const severityArb: fc.Arbitrary<AlertSeverity> = fc.constantFrom(
  "low" as const,
  "medium" as const,
  "critical" as const
);

const alertRecordArb = fc.record({
  severity: severityArb,
});

// --- Helpers ---

function createAlert(severity: AlertSeverity, id?: string): PredictiveAlert {
  return {
    id: id ?? `alert-${severity}-${Math.random().toString(36).slice(2)}`,
    engineId: 1,
    severity,
    timeToCriticalCycles: 50,
    confidenceScore: 0.85,
    suggestedAction: "Schedule inspection",
    timestamp: Date.now(),
  };
}

/** Expected auto-dismiss delay by severity (ms). null = no auto-dismiss. */
const EXPECTED_DISMISS_MS: Record<AlertSeverity, number | null> = {
  low: 10_000,
  medium: 30_000,
  critical: null,
};

// --- Property 10: Auto-Dismiss Timing ---

describe("Feature: digital-twin-v1.4, Property 10: Auto-Dismiss Timing", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("low and medium severity alerts are auto-dismissed at their correct timeout", () => {
    fc.assert(
      fc.property(alertRecordArb, ({ severity }) => {
        const dismissedIds: string[] = [];
        const onDismiss = (id: string) => {
          dismissedIds.push(id);
        };

        const alert = createAlert(severity, `test-${severity}`);
        const alerts = [alert];

        render(
          <PredictiveAlertNotification
            alerts={alerts}
            onDismiss={onDismiss}
            pollInterval={999_999} // disable polling for this test
          />
        );

        const expectedMs = EXPECTED_DISMISS_MS[severity];

        if (expectedMs === null) {
          // Critical: should NEVER auto-dismiss — advance well beyond any timeout
          act(() => {
            vi.advanceTimersByTime(120_000);
          });
          expect(dismissedIds).toEqual([]);
        } else {
          // Should NOT be dismissed just before the timeout
          act(() => {
            vi.advanceTimersByTime(expectedMs - 1);
          });
          expect(dismissedIds).toEqual([]);

          // Should be dismissed at the timeout
          act(() => {
            vi.advanceTimersByTime(1);
          });
          expect(dismissedIds).toEqual([alert.id]);
        }

        cleanup();
      }),
      { numRuns: 50 }
    );
  });

  it("critical alerts persist indefinitely (never auto-dismissed)", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 60_000, max: 600_000 }),
        (elapsedMs) => {
          const dismissedIds: string[] = [];
          const onDismiss = (id: string) => {
            dismissedIds.push(id);
          };

          const alert = createAlert("critical", "critical-persist");

          render(
            <PredictiveAlertNotification
              alerts={[alert]}
              onDismiss={onDismiss}
              pollInterval={999_999}
            />
          );

          // Advance arbitrary large time
          act(() => {
            vi.advanceTimersByTime(elapsedMs);
          });

          // Critical alert should never be auto-dismissed
          expect(dismissedIds).toEqual([]);

          cleanup();
        }
      ),
      { numRuns: 30 }
    );
  });
});
