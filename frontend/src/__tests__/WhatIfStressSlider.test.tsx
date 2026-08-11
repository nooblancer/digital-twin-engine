/**
 * Unit tests for WhatIfStressSlider component.
 *
 * Tests:
 * - Debounce: rapid slider changes only trigger one API call after 300ms
 * - Loading state renders while waiting for response
 *
 * Requirements: 8.1–8.7
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

  beforeEach(() => {
    vi.useFakeTimers();
    mockFetch.mockReset();
    mockOnSimulationResult.mockReset();

    // Default: resolve with valid simulation data
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => mockSimulationResponse,
    });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('triggers only one API call after 300ms debounce when slider changes rapidly', async () => {
    render(<WhatIfStressSlider {...defaultProps} />);

    // Initial mount triggers one fetch for stress_factor=1.0
    // Wait for the mount call to be made
    await act(async () => {
      await Promise.resolve();
    });

    const initialCallCount = mockFetch.mock.calls.length;
    expect(initialCallCount).toBe(1); // Mount call

    // Simulate rapid slider changes (5 changes in quick succession)
    const slider = screen.getByRole('slider');

    act(() => {
      fireEvent.change(slider, { target: { value: '1.1' } });
    });
    act(() => {
      fireEvent.change(slider, { target: { value: '1.2' } });
    });
    act(() => {
      fireEvent.change(slider, { target: { value: '1.3' } });
    });
    act(() => {
      fireEvent.change(slider, { target: { value: '1.4' } });
    });
    act(() => {
      fireEvent.change(slider, { target: { value: '1.5' } });
    });

    // Before debounce fires, no new fetch calls should have been made
    expect(mockFetch.mock.calls.length).toBe(initialCallCount);

    // Advance time past the 300ms debounce
    await act(async () => {
      vi.advanceTimersByTime(300);
      await Promise.resolve();
    });

    // Only ONE additional call should have been made (for the last value: 1.5)
    expect(mockFetch.mock.calls.length).toBe(initialCallCount + 1);

    // Verify the call was made with the LAST slider value (1.5)
    const lastCall = mockFetch.mock.calls[mockFetch.mock.calls.length - 1];
    const body = JSON.parse(lastCall[1].body);
    expect(body.stress_factor).toBe(1.5);
  });

  it('renders loading indicator while waiting for API response', async () => {
    // Use real timers for this test since we need the async fetch to proceed naturally
    vi.useRealTimers();

    // Create a promise that we control to keep the fetch pending
    let resolveFetch: (value: unknown) => void;
    const pendingFetch = new Promise((resolve) => {
      resolveFetch = resolve;
    });

    mockFetch.mockReturnValue(pendingFetch);

    render(<WhatIfStressSlider {...defaultProps} />);

    // The component triggers a fetch on mount — loading should appear
    await waitFor(() => {
      expect(screen.getByTestId('loading-indicator')).toBeInTheDocument();
    });

    expect(screen.getByText('Simulating…')).toBeInTheDocument();

    // Resolve the fetch to clear loading state
    await act(async () => {
      resolveFetch!({
        ok: true,
        json: async () => mockSimulationResponse,
      });
    });

    // Loading indicator should be gone
    await waitFor(() => {
      expect(screen.queryByTestId('loading-indicator')).not.toBeInTheDocument();
    });
  });
});
