/**
 * Unit tests for RootCausePanel component.
 *
 * Tests:
 * - Displays ranked horizontal bars for sensor contributions
 * - Handles no-anomaly state with green status indicator
 * - Handles loading state with skeleton shimmer
 * - Handles error state with red banner
 * - Retry button re-fetches analysis data
 *
 * Requirements: 12.1, 12.2, 12.3, 12.4, 12.5
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act, fireEvent, cleanup } from "@testing-library/react";
import React from "react";

// Mock framer-motion
vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement> & { children: React.ReactNode }) => (
      <div {...props}>{children}</div>
    ),
    span: ({ children, ...props }: React.HTMLAttributes<HTMLSpanElement> & { children: React.ReactNode }) => (
      <span {...props}>{children}</span>
    ),
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

import { useStore } from "@/store";
import { RootCausePanel } from "@/components/dashboard/RootCausePanel";
import type { AnomalyAnalysisResponse } from "@/types/mission-control";

// --- Test Data ---

const mockAnalysisActive: AnomalyAnalysisResponse = {
  engine_id: 1,
  anomaly_active: true,
  timestamp: "2024-01-15T10:30:00Z",
  contributions: [
    { sensor_name: "hpc_outlet_temp_total", innovation_magnitude: 4.23, sigma_deviation: 4.8 },
    { sensor_name: "physical_core_speed", innovation_magnitude: 2.15, sigma_deviation: 2.9 },
    { sensor_name: "lpc_outlet_temp", innovation_magnitude: 1.05, sigma_deviation: 1.5 },
  ],
};

const mockAnalysisInactive: AnomalyAnalysisResponse = {
  engine_id: 1,
  anomaly_active: false,
  timestamp: null,
  contributions: [],
};

// --- Helpers ---

function setStoreState(partial: Record<string, unknown>) {
  useStore.setState(partial);
}

function mockFetchSuccess(data: AnomalyAnalysisResponse) {
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve(data),
  });
}

function mockFetchError(status: number = 500) {
  global.fetch = vi.fn().mockResolvedValue({
    ok: false,
    status,
    json: () => Promise.resolve({ detail: "Error" }),
  });
}

function mockFetchNetworkError() {
  global.fetch = vi.fn().mockRejectedValue(new Error("Network error"));
}

// --- Tests ---

describe("RootCausePanel", () => {
  beforeEach(() => {
    setStoreState({
      anomalies: [],
      anomalyAnalysis: {},
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  describe("Loading State", () => {
    it("shows loading skeleton on initial render before fetch completes", () => {
      // Use a fetch that never resolves to keep loading state
      global.fetch = vi.fn().mockReturnValue(new Promise(() => {}));

      render(<RootCausePanel engineId={1} />);

      const loadingRegion = screen.getByLabelText("Loading analysis");
      expect(loadingRegion).toBeTruthy();
      expect(loadingRegion.getAttribute("aria-busy")).toBe("true");
    });

    it("shows skeleton bars with shimmer animation class", () => {
      global.fetch = vi.fn().mockReturnValue(new Promise(() => {}));

      const { container } = render(<RootCausePanel engineId={1} />);

      const shimmerBars = container.querySelectorAll(".animate-pulse");
      expect(shimmerBars.length).toBeGreaterThan(0);
    });
  });

  describe("No Active Anomaly State (Req 12.4)", () => {
    it("shows 'No active anomalies' when anomaly_active is false", async () => {
      mockFetchSuccess(mockAnalysisInactive);

      await act(async () => {
        render(<RootCausePanel engineId={1} />);
      });

      await waitFor(() => {
        expect(screen.getByText("No active anomalies")).toBeTruthy();
      });
    });

    it("shows green PulseIndicator (connected status) when no anomaly", async () => {
      mockFetchSuccess(mockAnalysisInactive);

      await act(async () => {
        render(<RootCausePanel engineId={1} />);
      });

      await waitFor(() => {
        const pulse = screen.getByRole("status");
        expect(pulse).toBeTruthy();
        expect(pulse.getAttribute("aria-label")).toBe("Connection connected");
      });
    });
  });

  describe("Ranked Sensor Contributions (Req 12.1, 12.2, 12.3)", () => {
    it("displays sensor names in ranked order", async () => {
      mockFetchSuccess(mockAnalysisActive);

      await act(async () => {
        render(<RootCausePanel engineId={1} />);
      });

      await waitFor(() => {
        expect(screen.getByText("hpc_outlet_temp_total")).toBeTruthy();
        expect(screen.getByText("physical_core_speed")).toBeTruthy();
        expect(screen.getByText("lpc_outlet_temp")).toBeTruthy();
      });
    });

    it("renders contributions as a ranked list with proper role", async () => {
      mockFetchSuccess(mockAnalysisActive);

      await act(async () => {
        render(<RootCausePanel engineId={1} />);
      });

      await waitFor(() => {
        const list = screen.getByRole("list");
        expect(list).toBeTruthy();
        expect(list.getAttribute("aria-label")).toBe("Sensor contributions ranked by deviation");
      });
    });

    it("displays sigma deviation values formatted with 1 decimal", async () => {
      mockFetchSuccess(mockAnalysisActive);

      await act(async () => {
        render(<RootCausePanel engineId={1} />);
      });

      await waitFor(() => {
        expect(screen.getByText("4.8σ")).toBeTruthy();
        expect(screen.getByText("2.9σ")).toBeTruthy();
        expect(screen.getByText("1.5σ")).toBeTruthy();
      });
    });

    it("renders horizontal bars with width proportional to sigma_deviation/max", async () => {
      mockFetchSuccess(mockAnalysisActive);

      const { container } = await act(async () => {
        return render(<RootCausePanel engineId={1} />);
      });

      await waitFor(() => {
        const meters = container.querySelectorAll('[role="meter"]');
        expect(meters.length).toBe(3);

        // First bar (highest sigma 4.8): should be 100% width
        const firstBar = meters[0] as HTMLElement;
        expect(firstBar.style.width).toBe("100%");

        // Second bar (sigma 2.9): should be ~60.4% width (2.9/4.8 * 100)
        const secondBar = meters[1] as HTMLElement;
        const expectedWidth2 = (2.9 / 4.8) * 100;
        expect(parseFloat(secondBar.style.width)).toBeCloseTo(expectedWidth2, 0);

        // Third bar (sigma 1.5): should be ~31.25% width (1.5/4.8 * 100)
        const thirdBar = meters[2] as HTMLElement;
        const expectedWidth3 = (1.5 / 4.8) * 100;
        expect(parseFloat(thirdBar.style.width)).toBeCloseTo(expectedWidth3, 0);
      });
    });

    it("uses crimson color for bars with sigma > 3", async () => {
      mockFetchSuccess(mockAnalysisActive);

      const { container } = await act(async () => {
        return render(<RootCausePanel engineId={1} />);
      });

      await waitFor(() => {
        const meters = container.querySelectorAll('[role="meter"]');
        // sigma 4.8 > 3 -> crimson (#ef4444)
        const firstBar = meters[0] as HTMLElement;
        expect(firstBar.style.backgroundColor).toBe("rgb(239, 68, 68)");
      });
    });

    it("uses amber color for bars with sigma > 2 and <= 3", async () => {
      mockFetchSuccess(mockAnalysisActive);

      const { container } = await act(async () => {
        return render(<RootCausePanel engineId={1} />);
      });

      await waitFor(() => {
        const meters = container.querySelectorAll('[role="meter"]');
        // sigma 2.9 > 2 -> amber (#f59e0b)
        const secondBar = meters[1] as HTMLElement;
        expect(secondBar.style.backgroundColor).toBe("rgb(245, 158, 11)");
      });
    });

    it("uses cyan color for bars with sigma <= 2", async () => {
      mockFetchSuccess(mockAnalysisActive);

      const { container } = await act(async () => {
        return render(<RootCausePanel engineId={1} />);
      });

      await waitFor(() => {
        const meters = container.querySelectorAll('[role="meter"]');
        // sigma 1.5 <= 2 -> cyan (#00d4ff)
        const thirdBar = meters[2] as HTMLElement;
        expect(thirdBar.style.backgroundColor).toBe("rgb(0, 212, 255)");
      });
    });

    it("provides accessible meter attributes for each bar", async () => {
      mockFetchSuccess(mockAnalysisActive);

      const { container } = await act(async () => {
        return render(<RootCausePanel engineId={1} />);
      });

      await waitFor(() => {
        const meters = container.querySelectorAll('[role="meter"]');
        const firstBar = meters[0];
        expect(firstBar.getAttribute("aria-valuenow")).toBe("4.8");
        expect(firstBar.getAttribute("aria-valuemin")).toBe("0");
        expect(firstBar.getAttribute("aria-label")).toContain("hpc_outlet_temp_total");
        expect(firstBar.getAttribute("aria-label")).toContain("4.8");
      });
    });
  });

  describe("Error State (Req 12.5)", () => {
    it("shows error banner when fetch fails with HTTP error", async () => {
      mockFetchError(500);

      await act(async () => {
        render(<RootCausePanel engineId={1} />);
      });

      await waitFor(() => {
        const alert = screen.getByRole("alert");
        expect(alert).toBeTruthy();
        expect(alert.textContent).toContain("Failed to fetch analysis");
      });
    });

    it("shows 'Engine not found' message for 404 responses", async () => {
      mockFetchError(404);

      await act(async () => {
        render(<RootCausePanel engineId={99} />);
      });

      await waitFor(() => {
        const alert = screen.getByRole("alert");
        expect(alert.textContent).toContain("Engine 99 not found");
      });
    });

    it("shows network error message when fetch throws", async () => {
      mockFetchNetworkError();

      await act(async () => {
        render(<RootCausePanel engineId={1} />);
      });

      await waitFor(() => {
        const alert = screen.getByRole("alert");
        expect(alert.textContent).toContain("Network error");
      });
    });

    it("renders retry button in error state", async () => {
      mockFetchError(500);

      await act(async () => {
        render(<RootCausePanel engineId={1} />);
      });

      await waitFor(() => {
        const retryBtn = screen.getByLabelText("Retry fetching analysis");
        expect(retryBtn).toBeTruthy();
      });
    });
  });

  describe("Retry Behavior (Req 12.5)", () => {
    it("retries fetch when retry button is clicked", async () => {
      // First call fails, second succeeds
      global.fetch = vi
        .fn()
        .mockResolvedValueOnce({ ok: false, status: 500 })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve(mockAnalysisActive),
        });

      await act(async () => {
        render(<RootCausePanel engineId={1} />);
      });

      // Wait for error state
      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
      });

      // Click retry
      await act(async () => {
        fireEvent.click(screen.getByLabelText("Retry fetching analysis"));
      });

      // Should now show the contributions after successful retry
      await waitFor(() => {
        expect(screen.getByText("hpc_outlet_temp_total")).toBeTruthy();
      });

      expect(global.fetch).toHaveBeenCalledTimes(2);
    });

    it("shows loading state during retry", async () => {
      // First fails immediately, second hangs (never resolves)
      global.fetch = vi
        .fn()
        .mockResolvedValueOnce({ ok: false, status: 500 })
        .mockReturnValueOnce(new Promise(() => {}));

      await act(async () => {
        render(<RootCausePanel engineId={1} />);
      });

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
      });

      // Click retry — should go back to loading
      await act(async () => {
        fireEvent.click(screen.getByLabelText("Retry fetching analysis"));
      });

      expect(screen.getByLabelText("Loading analysis")).toBeTruthy();
    });
  });

  describe("Anomaly Event Refetch (Req 12.1)", () => {
    it("refetches when a new anomaly is added to the store", async () => {
      mockFetchSuccess(mockAnalysisInactive);

      await act(async () => {
        render(<RootCausePanel engineId={1} />);
      });

      await waitFor(() => {
        expect(screen.getByText("No active anomalies")).toBeTruthy();
      });

      // Now update fetch to return active analysis and add an anomaly to the store
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockAnalysisActive),
      });

      await act(async () => {
        useStore.getState().addAnomaly({
          id: "anom-1",
          sensor_id: "hpc_outlet_temp_total",
          timestamp: Date.now(),
          severity: "high",
          message: "HPC outlet temp anomaly detected",
        });
      });

      // Should refetch and show contributions now
      await waitFor(() => {
        expect(screen.getByText("hpc_outlet_temp_total")).toBeTruthy();
      });
    });
  });

  describe("Panel Structure", () => {
    it("renders with region role and accessible label", async () => {
      mockFetchSuccess(mockAnalysisInactive);

      await act(async () => {
        render(<RootCausePanel engineId={1} />);
      });

      const region = screen.getByRole("region");
      expect(region.getAttribute("aria-label")).toBe("Root cause analysis panel");
    });

    it("displays 'Root Cause Analysis' header", async () => {
      mockFetchSuccess(mockAnalysisInactive);

      await act(async () => {
        render(<RootCausePanel engineId={1} />);
      });

      expect(screen.getByText("Root Cause Analysis")).toBeTruthy();
    });

    it("calls correct API endpoint with engineId", async () => {
      mockFetchSuccess(mockAnalysisInactive);

      await act(async () => {
        render(<RootCausePanel engineId={42} />);
      });

      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/engines/42/anomaly-analysis")
      );
    });

    it("merges custom className", async () => {
      mockFetchSuccess(mockAnalysisInactive);

      const { container } = await act(async () => {
        return render(<RootCausePanel engineId={1} className="mt-4" />);
      });

      const region = container.querySelector('[role="region"]');
      expect(region!.className).toContain("mt-4");
    });
  });
});
