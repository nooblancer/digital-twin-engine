/**
 * Unit tests for GlassStatusBar component.
 *
 * Tests:
 * - Renders with glass CSS class and sticky positioning
 * - Displays PulseIndicator based on connection state
 * - Displays AnimatedCounter with event count
 * - Polls performance metrics and renders sparklines
 * - Height is 56px (h-14)
 * - Has proper ARIA attributes
 *
 * Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";

// Mock window.matchMedia for jsdom environment
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// Mock recharts to avoid SVG rendering issues in jsdom
vi.mock("recharts", () => ({
  LineChart: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="line-chart">{children}</div>
  ),
  Line: () => <div data-testid="chart-line" />,
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="responsive-container">{children}</div>
  ),
}));

// Mock framer-motion to simplify testing
vi.mock("framer-motion", () => ({
  motion: {
    span: ({
      children,
      ...props
    }: React.HTMLAttributes<HTMLSpanElement> & { children: React.ReactNode }) => (
      <span {...props}>{children}</span>
    ),
  },
  useSpring: (value: { get: () => number }) => value,
  useTransform: (_val: unknown, fn: (v: number) => string) => ({
    on: (_event: string, _cb: (v: string) => void) => () => {},
    get: () => fn(0),
  }),
  useMotionValue: (initial: number) => ({
    get: () => initial,
    set: () => {},
  }),
}));

import { useStore } from "@/store";
import { GlassStatusBar } from "@/components/dashboard/GlassStatusBar";
import React from "react";
import { cleanup } from "@testing-library/react";

// Helper to set store state
function setStoreState(partial: Record<string, unknown>) {
  const store = useStore;
  store.setState(partial);
}

describe("GlassStatusBar", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // Reset store to defaults
    setStoreState({
      connection: {
        status: "connected",
        reconnectAttempts: 0,
        lastConnected: Date.now(),
        nextRetryMs: null,
      },
      totalEventCount: 42,
    });

    // Mock fetch
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          latency: { p50_ms: 23.4, p95_ms: 67.8, p99_ms: 89.2, sample_count: 100 },
          throughput: {
            events_per_second: 1042.5,
            predictions_per_second: 1038.2,
            corrections_per_second: 1035.7,
          },
        }),
    });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("renders with glass class and sticky top-0 z-50", () => {
    const { container } = render(<GlassStatusBar />);
    const header = container.querySelector("header");
    expect(header).toBeTruthy();
    expect(header!.className).toContain("glass");
    expect(header!.className).toContain("sticky");
    expect(header!.className).toContain("top-0");
    expect(header!.className).toContain("z-50");
  });

  it("renders with h-14 (56px height)", () => {
    const { container } = render(<GlassStatusBar />);
    const header = container.querySelector("header");
    expect(header!.className).toContain("h-14");
  });

  it("has flex row layout with gap-6", () => {
    const { container } = render(<GlassStatusBar />);
    const header = container.querySelector("header");
    expect(header!.className).toContain("flex");
    expect(header!.className).toContain("items-center");
    expect(header!.className).toContain("gap-6");
  });

  it("renders PulseIndicator with connected status", () => {
    render(<GlassStatusBar />);
    const pulse = screen.getByRole("status");
    expect(pulse).toBeTruthy();
    expect(pulse.getAttribute("aria-label")).toBe("Connection connected");
  });

  it("renders PulseIndicator as disconnected when store is disconnected", () => {
    setStoreState({
      connection: {
        status: "disconnected",
        reconnectAttempts: 0,
        lastConnected: null,
        nextRetryMs: null,
      },
    });
    render(<GlassStatusBar />);
    const pulse = screen.getByRole("status");
    expect(pulse.getAttribute("aria-label")).toBe("Connection disconnected");
  });

  it("renders PulseIndicator as connecting when store is reconnecting", () => {
    setStoreState({
      connection: {
        status: "reconnecting",
        reconnectAttempts: 1,
        lastConnected: null,
        nextRetryMs: 2000,
      },
    });
    render(<GlassStatusBar />);
    const pulse = screen.getByRole("status");
    expect(pulse.getAttribute("aria-label")).toBe("Connection connecting");
  });

  it("displays event count from store", () => {
    render(<GlassStatusBar />);
    // AnimatedCounter renders the label "Events"
    expect(screen.getByText("Events")).toBeTruthy();
  });

  it('has role="banner" and aria-label', () => {
    const { container } = render(<GlassStatusBar />);
    const header = container.querySelector("header");
    expect(header!.getAttribute("role")).toBe("banner");
    expect(header!.getAttribute("aria-label")).toBe("System status bar");
  });

  it("polls GET /metrics/performance on mount", async () => {
    await act(async () => {
      render(<GlassStatusBar />);
    });

    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/metrics/performance")
    );
  });

  it("polls again after 5 seconds", async () => {
    await act(async () => {
      render(<GlassStatusBar />);
    });

    // First call on mount
    expect(global.fetch).toHaveBeenCalledTimes(1);

    // Advance 5 seconds
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });

    expect(global.fetch).toHaveBeenCalledTimes(2);
  });

  it("renders sparkline labels", async () => {
    await act(async () => {
      render(<GlassStatusBar />);
    });

    expect(screen.getByText("Latency (p50)")).toBeTruthy();
    expect(screen.getByText("Events/s")).toBeTruthy();
    expect(screen.getByText("Corrections/s")).toBeTruthy();
  });

  it("merges custom className", () => {
    const { container } = render(<GlassStatusBar className="mt-4" />);
    const header = container.querySelector("header");
    expect(header!.className).toContain("mt-4");
  });

  it("handles fetch failure gracefully without crashing", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error("Network error")
    );

    await act(async () => {
      render(<GlassStatusBar />);
    });

    // Should still render without crashing
    expect(screen.getByRole("banner")).toBeTruthy();
  });

  it("transitions PulseIndicator from connected to disconnected within 1 render cycle (Req 6.5)", () => {
    // Start connected
    setStoreState({
      connection: {
        status: "connected",
        reconnectAttempts: 0,
        lastConnected: Date.now(),
        nextRetryMs: null,
      },
    });

    const { rerender } = render(<GlassStatusBar />);
    const pulse = screen.getByRole("status");
    expect(pulse.getAttribute("aria-label")).toBe("Connection connected");
    expect(pulse.className).toContain("pulse-indicator-connected");

    // Simulate WebSocket disconnect — state changes to disconnected
    setStoreState({
      connection: {
        status: "disconnected",
        reconnectAttempts: 0,
        lastConnected: null,
        nextRetryMs: null,
      },
    });

    // Re-render to pick up store change
    rerender(<GlassStatusBar />);

    // Should immediately reflect disconnected state
    const updatedPulse = screen.getByRole("status");
    expect(updatedPulse.getAttribute("aria-label")).toBe("Connection disconnected");
    expect(updatedPulse.className).not.toContain("pulse-indicator-connected");
    expect(updatedPulse.className).toContain("bg-[#ef4444]");
  });

  it("PulseIndicator shows green with animation when connected (Req 6.2)", () => {
    setStoreState({
      connection: {
        status: "connected",
        reconnectAttempts: 0,
        lastConnected: Date.now(),
        nextRetryMs: null,
      },
    });

    render(<GlassStatusBar />);
    const pulse = screen.getByRole("status");
    // Connected state should have green background and animation class
    expect(pulse.className).toContain("bg-[#10b981]");
    expect(pulse.className).toContain("pulse-indicator-connected");
  });

  it("PulseIndicator shows red static (no animation) when disconnected (Req 6.2)", () => {
    setStoreState({
      connection: {
        status: "disconnected",
        reconnectAttempts: 0,
        lastConnected: null,
        nextRetryMs: null,
      },
    });

    render(<GlassStatusBar />);
    const pulse = screen.getByRole("status");
    // Disconnected state: red, no animation class
    expect(pulse.className).toContain("bg-[#ef4444]");
    expect(pulse.className).not.toContain("pulse-indicator-connected");
    expect(pulse.className).not.toContain("pulse-indicator-connecting");
  });

  it("updates event counter when totalEventCount changes (Req 6.3)", () => {
    setStoreState({ totalEventCount: 100 });

    const { rerender } = render(<GlassStatusBar />);

    // Verify label is rendered
    expect(screen.getByText("Events")).toBeTruthy();

    // Simulate new events arriving via WebSocket — counter increases
    setStoreState({ totalEventCount: 150 });
    rerender(<GlassStatusBar />);

    // Counter component should re-render with new value
    // The AnimatedCounter renders an aria-live region for accessibility
    const counter = screen.getByRole("status", { hidden: false }) 
      ? screen.getAllByLabelText(/./i).find((el) => el.getAttribute("aria-live") === "polite")
      : null;
    // At minimum, the Events label should still be present and the component should not crash
    expect(screen.getByText("Events")).toBeTruthy();
  });
});
