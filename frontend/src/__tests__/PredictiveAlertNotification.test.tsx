/**
 * Unit tests for PredictiveAlertNotification component.
 *
 * Tests:
 * - Severity colors (crimson=critical, amber=medium, emerald=low)
 * - Stacking order (critical first)
 * - Auto-dismiss timing (low=10s, medium=30s, critical=persists)
 * - Manual dismiss via button
 * - Polling at configurable interval
 *
 * Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, cleanup, fireEvent } from "@testing-library/react";
import React from "react";

// Mock framer-motion for deterministic test rendering
vi.mock("framer-motion", () => ({
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  motion: {
    div: React.forwardRef(
      (
        { children, ...props }: React.HTMLAttributes<HTMLDivElement> & { children?: React.ReactNode; layout?: boolean },
        ref: React.Ref<HTMLDivElement>
      ) => (
        <div ref={ref} {...props}>
          {children}
        </div>
      )
    ),
  },
}));

// Mock the store
const mockAddPredictiveAlert = vi.fn();
vi.mock("@/store", () => ({
  useStore: (selector: (s: Record<string, unknown>) => unknown) =>
    selector({
      engines: { 1: { engineId: 1, healthIndex: 0.65 } },
      addPredictiveAlert: mockAddPredictiveAlert,
    }),
}));

import { PredictiveAlertNotification } from "@/components/dashboard/PredictiveAlertNotification";
import type { PredictiveAlert, AlertSeverity } from "@/types/mission-control";

// --- Helpers ---

function createAlert(
  severity: AlertSeverity,
  overrides: Partial<PredictiveAlert> = {}
): PredictiveAlert {
  return {
    id: `alert-${severity}-${Date.now()}-${Math.random()}`,
    engineId: 1,
    severity,
    timeToCriticalCycles: severity === "critical" ? 10 : severity === "medium" ? 42 : 80,
    confidenceScore: 0.78,
    suggestedAction: "Schedule inspection",
    timestamp: Date.now(),
    ...overrides,
  };
}

describe("PredictiveAlertNotification", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          engine_id: 1,
          recommendations: [],
        }),
    });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  // --- Severity Colors (Requirement 13.2) ---

  describe("severity colors", () => {
    it("renders critical alerts with crimson (#ef4444) border", () => {
      const alert = createAlert("critical", { id: "critical-1" });
      const { container } = render(
        <PredictiveAlertNotification
          alerts={[alert]}
          onDismiss={() => {}}
          pollInterval={999_999}
        />
      );

      const alertEl = container.querySelector('[role="alert"]');
      expect(alertEl).not.toBeNull();
      const style = alertEl!.getAttribute("style")!;
      // jsdom may render hex as rgb() — accept either form
      expect(
        style.includes("#ef4444") || style.includes("rgb(239, 68, 68)")
      ).toBe(true);
    });

    it("renders medium alerts with amber (#f59e0b) border", () => {
      const alert = createAlert("medium", { id: "medium-1" });
      const { container } = render(
        <PredictiveAlertNotification
          alerts={[alert]}
          onDismiss={() => {}}
          pollInterval={999_999}
        />
      );

      const alertEl = container.querySelector('[role="alert"]');
      expect(alertEl).not.toBeNull();
      const style = alertEl!.getAttribute("style")!;
      expect(
        style.includes("#f59e0b") || style.includes("rgb(245, 158, 11)")
      ).toBe(true);
    });

    it("renders low alerts with emerald (#10b981) border", () => {
      const alert = createAlert("low", { id: "low-1" });
      const { container } = render(
        <PredictiveAlertNotification
          alerts={[alert]}
          onDismiss={() => {}}
          pollInterval={999_999}
        />
      );

      const alertEl = container.querySelector('[role="alert"]');
      expect(alertEl).not.toBeNull();
      const style = alertEl!.getAttribute("style")!;
      expect(
        style.includes("#10b981") || style.includes("rgb(16, 185, 129)")
      ).toBe(true);
    });
  });

  // --- Stacking Order (Requirement 13.4) ---

  describe("stacking order", () => {
    it("renders critical alerts before medium and low", () => {
      const alerts = [
        createAlert("low", { id: "low-1", timestamp: 1000 }),
        createAlert("critical", { id: "critical-1", timestamp: 2000 }),
        createAlert("medium", { id: "medium-1", timestamp: 3000 }),
      ];

      const { container } = render(
        <PredictiveAlertNotification
          alerts={alerts}
          onDismiss={() => {}}
          pollInterval={999_999}
        />
      );

      const alertElements = container.querySelectorAll('[role="alert"]');
      expect(alertElements.length).toBe(3);

      // First rendered should be critical (highest priority)
      expect(alertElements[0].textContent).toContain("Critical");
      expect(alertElements[1].textContent).toContain("Medium");
      expect(alertElements[2].textContent).toContain("Low");
    });

    it("limits visible alerts to max 5", () => {
      const alerts = Array.from({ length: 7 }, (_, i) =>
        createAlert("low", { id: `alert-${i}`, timestamp: i * 1000 })
      );

      const { container } = render(
        <PredictiveAlertNotification
          alerts={alerts}
          onDismiss={() => {}}
          pollInterval={999_999}
        />
      );

      const alertElements = container.querySelectorAll('[role="alert"]');
      expect(alertElements.length).toBe(5);
    });
  });

  // --- Auto-Dismiss Timing (Requirement 13.5) ---

  describe("auto-dismiss timing", () => {
    it("auto-dismisses low severity alerts after 10 seconds", () => {
      const onDismiss = vi.fn();
      const alert = createAlert("low", { id: "low-dismiss" });

      render(
        <PredictiveAlertNotification
          alerts={[alert]}
          onDismiss={onDismiss}
          pollInterval={999_999}
        />
      );

      // Not dismissed before 10s
      act(() => {
        vi.advanceTimersByTime(9_999);
      });
      expect(onDismiss).not.toHaveBeenCalled();

      // Dismissed at 10s
      act(() => {
        vi.advanceTimersByTime(1);
      });
      expect(onDismiss).toHaveBeenCalledWith("low-dismiss");
    });

    it("auto-dismisses medium severity alerts after 30 seconds", () => {
      const onDismiss = vi.fn();
      const alert = createAlert("medium", { id: "medium-dismiss" });

      render(
        <PredictiveAlertNotification
          alerts={[alert]}
          onDismiss={onDismiss}
          pollInterval={999_999}
        />
      );

      // Not dismissed before 30s
      act(() => {
        vi.advanceTimersByTime(29_999);
      });
      expect(onDismiss).not.toHaveBeenCalled();

      // Dismissed at 30s
      act(() => {
        vi.advanceTimersByTime(1);
      });
      expect(onDismiss).toHaveBeenCalledWith("medium-dismiss");
    });

    it("does NOT auto-dismiss critical severity alerts", () => {
      const onDismiss = vi.fn();
      const alert = createAlert("critical", { id: "critical-persist" });

      render(
        <PredictiveAlertNotification
          alerts={[alert]}
          onDismiss={onDismiss}
          pollInterval={999_999}
        />
      );

      // Even after 2 minutes, critical is not dismissed
      act(() => {
        vi.advanceTimersByTime(120_000);
      });
      expect(onDismiss).not.toHaveBeenCalled();
    });
  });

  // --- Manual Dismiss (Requirement 13.5) ---

  describe("manual dismiss", () => {
    it("calls onDismiss when dismiss button is clicked", () => {
      const onDismiss = vi.fn();
      const alert = createAlert("critical", { id: "manual-dismiss-1" });

      render(
        <PredictiveAlertNotification
          alerts={[alert]}
          onDismiss={onDismiss}
          pollInterval={999_999}
        />
      );

      const dismissButton = screen.getByLabelText("Dismiss alert for engine 1");
      fireEvent.click(dismissButton);
      expect(onDismiss).toHaveBeenCalledWith("manual-dismiss-1");
    });
  });

  // --- Polling (Requirement 13.6) ---

  describe("polling", () => {
    it("polls maintenance-recommendations on mount", async () => {
      await act(async () => {
        render(
          <PredictiveAlertNotification
            alerts={[]}
            onDismiss={() => {}}
            pollInterval={30_000}
          />
        );
      });

      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/maintenance-recommendations")
      );
    });

    it("polls at the configured interval", async () => {
      await act(async () => {
        render(
          <PredictiveAlertNotification
            alerts={[]}
            onDismiss={() => {}}
            pollInterval={15_000}
          />
        );
      });

      // Initial poll
      const initialCalls = (global.fetch as ReturnType<typeof vi.fn>).mock.calls.length;

      // Advance by 15s — should poll again
      await act(async () => {
        vi.advanceTimersByTime(15_000);
      });

      expect((global.fetch as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(
        initialCalls
      );
    });

    it("uses default 30s poll interval when not specified", async () => {
      await act(async () => {
        render(
          <PredictiveAlertNotification alerts={[]} onDismiss={() => {}} />
        );
      });

      const initialCalls = (global.fetch as ReturnType<typeof vi.fn>).mock.calls.length;

      // 29s — no additional poll
      await act(async () => {
        vi.advanceTimersByTime(29_000);
      });
      expect((global.fetch as ReturnType<typeof vi.fn>).mock.calls.length).toBe(initialCalls);

      // 1 more second (total 30s) — should poll
      await act(async () => {
        vi.advanceTimersByTime(1_000);
      });
      expect((global.fetch as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(
        initialCalls
      );
    });
  });

  // --- Display Format (Requirement 13.1, 13.3) ---

  describe("display format", () => {
    it("displays message with engine id and cycles to critical (Req 13.1)", () => {
      const alert = createAlert("medium", {
        id: "msg-test",
        engineId: 3,
        timeToCriticalCycles: 42,
      });

      render(
        <PredictiveAlertNotification
          alerts={[alert]}
          onDismiss={() => {}}
          pollInterval={999_999}
        />
      );

      expect(screen.getByText(/Engine 3/)).toBeTruthy();
      expect(screen.getByText("42 cycles")).toBeTruthy();
    });

    it("displays confidence score as percentage (Req 13.3)", () => {
      const alert = createAlert("low", {
        id: "confidence-test",
        confidenceScore: 0.78,
      });

      render(
        <PredictiveAlertNotification
          alerts={[alert]}
          onDismiss={() => {}}
          pollInterval={999_999}
        />
      );

      expect(screen.getByText(/Confidence: 78%/)).toBeTruthy();
    });
  });

  // --- ARIA / Accessibility ---

  describe("accessibility", () => {
    it("has region role with descriptive label", () => {
      render(
        <PredictiveAlertNotification
          alerts={[]}
          onDismiss={() => {}}
          pollInterval={999_999}
        />
      );

      const region = screen.getByRole("region");
      expect(region.getAttribute("aria-label")).toBe("Predictive maintenance alerts");
    });

    it("each alert has role=alert", () => {
      const alert = createAlert("low", { id: "aria-test" });

      const { container } = render(
        <PredictiveAlertNotification
          alerts={[alert]}
          onDismiss={() => {}}
          pollInterval={999_999}
        />
      );

      const alertElements = container.querySelectorAll('[role="alert"]');
      expect(alertElements.length).toBe(1);
    });
  });
});
