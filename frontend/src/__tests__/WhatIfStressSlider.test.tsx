/**
 * Unit tests for WhatIfStressSlider component.
 *
 * Tests:
 * - Debounce: rapid slider changes only trigger one API call after 300ms
 * - Loading state renders while waiting for response
 * - Insufficient data: shows progress indicator instead of red error
 * - Auto-triggers simulation when data becomes ready
 *
 * Requirements: 8.1–8.7, 16.1, 16.2, 16.5, 16.6
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, act, waitFor } from '@testing-library/react';
import { WhatIfStressSlider } from '@/components/visualizations/WhatIfStressSlider';

// --- Mock fetch globally ---
const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

describe('WhatIfStressSlider', () => {
  const mockOnSimulationResult = vi.fn();
  const defaultProps = {
    engineId: 1,
    onSimulationResult: mockOnSimulationResult,
    horizonCycles: 50,
  };

  const mockSimulationResponse = {
    percentiles: {
      5: Array(50).fill(0.3),
      25: Array(50).fill(0.5),
      50: Array(50).fill(0.6),
      75: Array(50).fill(0.7),
      95: Array(50).fill(0.85),
    },
    failure_probability_by_cycle: Array(50).fill(0.1),
    expected_rul: 42,
    confidence_interval_90: [35, 50] as [number, number],
  };

  const makeSnapshotResponse = (cycleCount: number) => ({
    ok: true,
    status: 200,
    json: async () => ({ health: { cycle_count: cycleCount } }),
  });

  const mockSimulationOk = {
    ok: true,
    status: 200,
    json: async () => mockSimulationResponse,
    text: async () => JSON.stringify(mockSimulationResponse),
  };

  beforeEach(() => {
    mockFetch.mockReset();
    mockOnSimulationResult.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it('triggers only one API call after 300ms debounce when slider changes rapidly', async () => {
    vi.useFakeTimers();

    // Mock: snapshot says data is ready, then simulation calls succeed
    mockFetch.mockImplementation(async (url: string) => {
      if (url.includes('/snapshot')) {
        return makeSnapshotResponse(25);
      }
      return mockSimulationOk;
    });

    await act(async () => {
      render(<WhatIfStressSlider {...defaultProps} />);
    });

    // Flush initial snapshot fetch + auto-trigger
    await act(async () => {
      vi.advanceTimersByTime(1);
    });

    // Count calls so far: 1 snapshot + 1 auto-triggered simulation
    const initialCallCount = mockFetch.mock.calls.length;

    // Simulate rapid slider changes (5 changes in quick succession)
    const slider = screen.getByRole('slider');

    act(() => { fireEvent.change(slider, { target: { value: '1.1' } }); });
    act(() => { fireEvent.change(slider, { target: { value: '1.2' } }); });
    act(() => { fireEvent.change(slider, { target: { value: '1.3' } }); });
    act(() => { fireEvent.change(slider, { target: { value: '1.4' } }); });
    act(() => { fireEvent.change(slider, { target: { value: '1.5' } }); });

    // Before debounce fires, no new fetch calls should have been made
    expect(mockFetch.mock.calls.length).toBe(initialCallCount);

    // Advance time past the 300ms debounce
    await act(async () => {
      vi.advanceTimersByTime(300);
    });

    // Only ONE additional call should have been made (for the last value: 1.5)
    expect(mockFetch.mock.calls.length).toBe(initialCallCount + 1);

    // Verify the call was made with the LAST slider value (1.5)
    const lastCall = mockFetch.mock.calls[mockFetch.mock.calls.length - 1];
    const body = JSON.parse(lastCall[1].body);
    expect(body.stress_factor).toBe(1.5);

    vi.useRealTimers();
  });

  it('renders loading indicator while simulation is in progress', async () => {
    let resolveSimulation: ((value: unknown) => void) | null = null;

    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/snapshot')) {
        return Promise.resolve(makeSnapshotResponse(25));
      }
      // Simulation call — return a pending promise
      return new Promise((resolve) => {
        resolveSimulation = resolve;
      });
    });

    await act(async () => {
      render(<WhatIfStressSlider {...defaultProps} />);
    });

    // Snapshot resolved, auto-trigger sent a simulation request that is pending
    // The loading indicator should be visible
    await waitFor(() => {
      expect(screen.getByTestId('loading-indicator')).toBeInTheDocument();
    });
    expect(screen.getByText('Simulating…')).toBeInTheDocument();

    // Resolve the simulation
    await act(async () => {
      resolveSimulation!(mockSimulationOk);
    });

    // Loading indicator should be gone
    await waitFor(() => {
      expect(screen.queryByTestId('loading-indicator')).not.toBeInTheDocument();
    });
  });

  it('shows progress indicator when cycle count is insufficient (Req 16.1)', async () => {
    mockFetch.mockImplementation(async (url: string) => {
      if (url.includes('/snapshot')) {
        return makeSnapshotResponse(5);
      }
      return mockSimulationOk;
    });

    await act(async () => {
      render(<WhatIfStressSlider {...defaultProps} />);
    });

    // Should show the insufficient-data indicator with cycle count
    expect(screen.getByTestId('insufficient-data-indicator')).toBeInTheDocument();
    expect(screen.getByText(/Collecting data/)).toBeInTheDocument();
    // Verify the full text content to avoid tick-mark conflicts
    const indicatorText = screen.getByTestId('insufficient-data-indicator').textContent;
    expect(indicatorText).toContain('5');
    expect(indicatorText).toContain('20');
    expect(indicatorText).toContain('cycles needed');
  });

  it('disables slider when insufficient data (Req 16.2)', async () => {
    mockFetch.mockImplementation(async (url: string) => {
      if (url.includes('/snapshot')) {
        return makeSnapshotResponse(5);
      }
      return mockSimulationOk;
    });

    await act(async () => {
      render(<WhatIfStressSlider {...defaultProps} />);
    });

    const slider = screen.getByRole('slider');
    expect(slider).toBeDisabled();
    // Verify cursor-not-allowed styling is applied
    expect(slider.className).toContain('cursor-not-allowed');
  });

  it('auto-triggers simulation when data transitions to ready (Req 16.5)', async () => {
    vi.useFakeTimers();

    // Start with insufficient data
    let cycleCount = 5;
    mockFetch.mockImplementation(async (url: string) => {
      if (url.includes('/snapshot')) {
        return makeSnapshotResponse(cycleCount);
      }
      return mockSimulationOk;
    });

    await act(async () => {
      render(<WhatIfStressSlider {...defaultProps} />);
    });

    // Flush initial mount
    await act(async () => {
      vi.advanceTimersByTime(1);
    });

    // Should be in insufficient state
    expect(screen.getByTestId('insufficient-data-indicator')).toBeInTheDocument();
    expect(screen.getByRole('slider')).toBeDisabled();

    // Transition to ready
    cycleCount = 25;

    // Advance past the 5s polling interval
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });

    // Slider should now be enabled (data is ready)
    expect(screen.getByRole('slider')).not.toBeDisabled();

    // Should have triggered a simulation fetch (auto-trigger)
    const simulationCalls = mockFetch.mock.calls.filter(
      (call) => !call[0].includes('/snapshot')
    );
    expect(simulationCalls.length).toBeGreaterThanOrEqual(1);

    vi.useRealTimers();
  });

  it('does NOT show red error for 404 insufficient-data responses (Req 16.6)', async () => {
    // Snapshot says insufficient data
    mockFetch.mockImplementation(async (url: string) => {
      if (url.includes('/snapshot')) {
        return makeSnapshotResponse(5);
      }
      return {
        ok: false,
        status: 404,
        text: async () => 'Insufficient trajectory data to compute degradation rate for engine 1 (need at least 20 cycles)',
        json: async () => ({}),
      };
    });

    await act(async () => {
      render(<WhatIfStressSlider {...defaultProps} />);
    });

    // Should NOT display any red error styling
    const errorElement = screen.queryByText(/Simulation failed/);
    expect(errorElement).not.toBeInTheDocument();

    // Should show the progress indicator instead
    expect(screen.getByTestId('insufficient-data-indicator')).toBeInTheDocument();
  });

  it('shows error state for actual unexpected errors (500s)', async () => {
    mockFetch.mockImplementation(async (url: string) => {
      if (url.includes('/snapshot')) {
        // Snapshot returns server error
        return {
          ok: false,
          status: 500,
          json: async () => ({}),
          text: async () => 'Internal Server Error',
        };
      }
      return mockSimulationOk;
    });

    await act(async () => {
      render(<WhatIfStressSlider {...defaultProps} />);
    });

    // Should show the error state
    await waitFor(() => {
      expect(screen.getByText(/Failed to fetch engine status/)).toBeInTheDocument();
    });
  });

  it('fetches cycle count from /api/engines/{id}/snapshot (Req 16.6)', async () => {
    mockFetch.mockImplementation(async (url: string) => {
      if (url.includes('/snapshot')) {
        return makeSnapshotResponse(25);
      }
      return mockSimulationOk;
    });

    await act(async () => {
      render(<WhatIfStressSlider {...defaultProps} />);
    });

    // Verify snapshot was called with correct URL
    const snapshotCalls = mockFetch.mock.calls.filter((call) =>
      call[0].includes('/api/engines/1/snapshot')
    );
    expect(snapshotCalls.length).toBeGreaterThanOrEqual(1);
  });
});
