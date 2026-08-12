/**
 * Tests for the Insufficient-Data UX across simulation components.
 *
 * Tests:
 * - Progress indicator shown when cycleCount < 20
 * - Slider is disabled (has `disabled` attribute) when insufficient data
 * - Auto-enables and triggers simulation when cycleCount transitions to >= 20
 * - No red error box for 404 insufficient-data responses
 * - RULCountdown shows "Calibrating..." message
 * - MonteCarloFanChart shows calm empty state message
 *
 * Requirements: 16.1, 16.2, 16.3, 16.4, 16.5
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, act, waitFor } from '@testing-library/react';

// --- Mock fetch globally ---
const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

// --- Mock framer-motion for RULCountdown ---
vi.mock('framer-motion', () => ({
  motion: {
    p: ({ children, className, ...rest }: Record<string, unknown>) => (
      <p data-testid="motion-p" className={className as string} {...rest}>
        {children as React.ReactNode}
      </p>
    ),
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// --- Mock Recharts for MonteCarloFanChart ---
vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="responsive-container">{children}</div>
  ),
  AreaChart: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="area-chart">{children}</div>
  ),
  Area: (props: Record<string, unknown>) => (
    <div data-testid={`area-${props.dataKey}`} />
  ),
  XAxis: () => <div data-testid="x-axis" />,
  YAxis: () => <div data-testid="y-axis" />,
  CartesianGrid: () => <div data-testid="cartesian-grid" />,
  Tooltip: () => <div data-testid="tooltip" />,
  ReferenceLine: () => <div data-testid="reference-line" />,
}));

// --- Import components AFTER mocks ---
import { WhatIfStressSlider } from '@/components/visualizations/WhatIfStressSlider';
import { RULCountdown } from '@/components/visualizations/RULCountdown';
import { MonteCarloFanChart } from '@/components/visualizations/MonteCarloFanChart';

// --- Helpers ---
const makeSnapshotResponse = (cycleCount: number) => ({
  ok: true,
  status: 200,
  json: async () => ({ health: { cycle_count: cycleCount } }),
});

const mockSimulationOk = {
  ok: true,
  status: 200,
  json: async () => ({
    percentiles: {
      5: Array(50).fill(0.3),
      25: Array(50).fill(0.5),
      50: Array(50).fill(0.6),
      75: Array(50).fill(0.7),
      95: Array(50).fill(0.85),
    },
    failure_probability_by_cycle: Array(50).fill(0.1),
    expected_rul: 42,
    confidence_interval_90: [35, 50],
  }),
  text: async () => '{}',
};

describe('Insufficient-Data UX', () => {
  const mockOnSimulationResult = vi.fn();

  beforeEach(() => {
    mockFetch.mockReset();
    mockOnSimulationResult.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  describe('WhatIfStressSlider — progress indicator (Req 16.1)', () => {
    it('shows progress indicator when cycleCount < 20', async () => {
      mockFetch.mockImplementation(async (url: string) => {
        if (url.includes('/snapshot')) {
          return makeSnapshotResponse(8);
        }
        return mockSimulationOk;
      });

      await act(async () => {
        render(
          <WhatIfStressSlider
            engineId={1}
            onSimulationResult={mockOnSimulationResult}
          />
        );
      });

      // The insufficient-data indicator should be visible
      expect(screen.getByTestId('insufficient-data-indicator')).toBeInTheDocument();

      // Should contain the cycle count text
      const indicator = screen.getByTestId('insufficient-data-indicator');
      expect(indicator.textContent).toContain('8');
      expect(indicator.textContent).toContain('20');
      expect(indicator.textContent).toContain('cycles needed');
    });
  });

  describe('WhatIfStressSlider — slider disabled (Req 16.2)', () => {
    it('slider has disabled attribute when insufficient data', async () => {
      mockFetch.mockImplementation(async (url: string) => {
        if (url.includes('/snapshot')) {
          return makeSnapshotResponse(10);
        }
        return mockSimulationOk;
      });

      await act(async () => {
        render(
          <WhatIfStressSlider
            engineId={1}
            onSimulationResult={mockOnSimulationResult}
          />
        );
      });

      const slider = screen.getByRole('slider');
      expect(slider).toBeDisabled();
      expect(slider).toHaveAttribute('disabled');
    });
  });

  describe('WhatIfStressSlider — auto-enable on transition (Req 16.5)', () => {
    it('auto-enables and triggers simulation when cycleCount transitions to >= 20', async () => {
      vi.useFakeTimers();

      // Start with insufficient data
      let cycleCount = 12;
      mockFetch.mockImplementation(async (url: string) => {
        if (url.includes('/snapshot')) {
          return makeSnapshotResponse(cycleCount);
        }
        return mockSimulationOk;
      });

      await act(async () => {
        render(
          <WhatIfStressSlider
            engineId={1}
            onSimulationResult={mockOnSimulationResult}
          />
        );
      });

      // Flush initial mount
      await act(async () => {
        vi.advanceTimersByTime(1);
      });

      // Slider should be disabled
      expect(screen.getByRole('slider')).toBeDisabled();
      expect(screen.getByTestId('insufficient-data-indicator')).toBeInTheDocument();

      // Transition: cycle count passes threshold
      cycleCount = 22;

      // Advance past the 5s polling interval
      await act(async () => {
        vi.advanceTimersByTime(5000);
      });

      // Slider should now be enabled
      expect(screen.getByRole('slider')).not.toBeDisabled();

      // The insufficient-data indicator should be gone
      expect(screen.queryByTestId('insufficient-data-indicator')).not.toBeInTheDocument();

      // Should have auto-triggered a simulation fetch
      const simulationCalls = mockFetch.mock.calls.filter(
        (call) => !call[0].includes('/snapshot')
      );
      expect(simulationCalls.length).toBeGreaterThanOrEqual(1);

      vi.useRealTimers();
    });
  });

  describe('WhatIfStressSlider — no red error for 404 (Req 16.1, 16.5)', () => {
    it('does not show red error box for 404 insufficient-data responses', async () => {
      mockFetch.mockImplementation(async (url: string) => {
        if (url.includes('/snapshot')) {
          return makeSnapshotResponse(5);
        }
        // Simulate a 404 insufficient-data response from the simulation API
        return {
          ok: false,
          status: 404,
          text: async () =>
            'Insufficient trajectory data to compute degradation rate for engine 1 (need at least 20 cycles)',
          json: async () => ({}),
        };
      });

      await act(async () => {
        render(
          <WhatIfStressSlider
            engineId={1}
            onSimulationResult={mockOnSimulationResult}
          />
        );
      });

      // Should NOT have any red-styled error box
      const errorElements = document.querySelectorAll('.text-red-400');
      expect(errorElements.length).toBe(0);

      // No element with red background styling
      const redBgElements = document.querySelectorAll('[class*="bg-red"]');
      expect(redBgElements.length).toBe(0);

      // Should show the calm progress indicator instead
      expect(screen.getByTestId('insufficient-data-indicator')).toBeInTheDocument();
    });
  });

  describe('RULCountdown — Calibrating message (Req 16.4)', () => {
    it('shows "Calibrating..." message when expectedRul is null and cycleCount < 20', () => {
      render(
        <RULCountdown expectedRul={null} confidenceInterval90={null} cycleCount={7} />
      );

      // Should show "--" as the RUL value
      expect(screen.getByText('--')).toBeInTheDocument();

      // Should show calibrating message with cycle count
      expect(screen.getByText('Calibrating... (7/20 cycles)')).toBeInTheDocument();
    });

    it('shows "Awaiting data" when cycleCount is not provided', () => {
      render(
        <RULCountdown expectedRul={null} confidenceInterval90={null} />
      );

      expect(screen.getByText('--')).toBeInTheDocument();
      expect(screen.getByText('Awaiting data')).toBeInTheDocument();
    });

    it('shows "Calibrating..." with boundary value cycleCount=19', () => {
      render(
        <RULCountdown expectedRul={null} confidenceInterval90={null} cycleCount={19} />
      );

      expect(screen.getByText('Calibrating... (19/20 cycles)')).toBeInTheDocument();
    });

    it('shows "Awaiting data" when cycleCount >= 20 but no RUL yet', () => {
      render(
        <RULCountdown expectedRul={null} confidenceInterval90={null} cycleCount={25} />
      );

      // cycleCount >= 20 means calibration is done, so should show "Awaiting data"
      expect(screen.getByText('Awaiting data')).toBeInTheDocument();
    });
  });

  describe('MonteCarloFanChart — calm empty state (Req 16.3)', () => {
    it('shows calm message when insufficientData is true', () => {
      render(
        <MonteCarloFanChart percentiles={null} insufficientData={true} />
      );

      expect(
        screen.getByText(
          'Simulation will become available once the engine accumulates 20 cycles of data.'
        )
      ).toBeInTheDocument();
    });

    it('does not use red styling for insufficient data state', () => {
      const { container } = render(
        <MonteCarloFanChart percentiles={null} insufficientData={true} />
      );

      // No red text classes
      const redElements = container.querySelectorAll('[class*="text-red"]');
      expect(redElements.length).toBe(0);

      // No red background classes
      const redBgElements = container.querySelectorAll('[class*="bg-red"]');
      expect(redBgElements.length).toBe(0);
    });

    it('shows default empty message when insufficientData is false', () => {
      render(
        <MonteCarloFanChart percentiles={null} insufficientData={false} />
      );

      expect(
        screen.getByText(
          'No simulation data available. Adjust the stress slider to generate a projection.'
        )
      ).toBeInTheDocument();
    });
  });
});
