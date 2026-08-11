/**
 * Unit tests for Engine Dashboard page
 * Tests RUL indicator rendering, critical emphasis, trajectory chart data binding,
 * and engine selector dropdown behavior.
 *
 * Validates: Requirements 6.1, 6.2, 6.4, 6.6
 *
 * Updated for v1.3 integration: RULCountdown and DegradationCurveProjection components.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { useStore } from '@/store';
import type { EngineState } from '@/types/digital-twin';

// --- Mocks ---

const mockPush = vi.fn();

vi.mock('next/navigation', () => ({
  useParams: () => ({ id: '1' }),
  useRouter: () => ({ push: mockPush }),
}));

// Mock useWebSocket hook
vi.mock('@/hooks/useWebSocket', () => ({
  useWebSocket: () => {},
  default: () => {},
}));

// Mock framer-motion (used by RULCountdown)
vi.mock('framer-motion', () => ({
  motion: {
    p: ({ children, className, ...rest }: Record<string, unknown>) => (
      <p data-testid="rul-countdown-value" className={className as string}>
        {children as React.ReactNode}
      </p>
    ),
    div: ({ children, className, ...rest }: Record<string, unknown>) => (
      <div className={className as string}>{children as React.ReactNode}</div>
    ),
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// Mock Recharts to avoid SVG rendering issues in jsdom
vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="responsive-container">{children}</div>
  ),
  ComposedChart: ({ data, children }: { data: unknown[]; children: React.ReactNode }) => (
    <div data-testid="composed-chart" data-points={JSON.stringify(data)}>
      {children}
    </div>
  ),
  LineChart: ({ data }: { data: unknown[] }) => (
    <div data-testid="line-chart" data-points={JSON.stringify(data)} />
  ),
  Line: ({ dataKey }: { dataKey: string }) => (
    <div data-testid={`line-${dataKey}`} />
  ),
  Area: ({ dataKey }: { dataKey: string }) => (
    <div data-testid={`area-${dataKey}`} />
  ),
  XAxis: () => <div data-testid="x-axis" />,
  YAxis: () => <div data-testid="y-axis" />,
  CartesianGrid: () => <div data-testid="cartesian-grid" />,
  Tooltip: () => <div data-testid="tooltip" />,
  ReferenceLine: () => <div data-testid="reference-line" />,
}));

// Mock heavy child components that aren't under test
vi.mock('@/components/EngineSchematic', () => ({
  EngineSchematic: () => <div data-testid="engine-schematic" />,
}));

vi.mock('@/components/visualizations/PredictionComparison', () => ({
  PredictionComparison: () => <div data-testid="prediction-comparison" />,
}));

vi.mock('@/components/visualizations/ConfidenceBandChart', () => ({
  ConfidenceBandChart: () => <div data-testid="confidence-band-chart" />,
}));

vi.mock('@/components/visualizations/KalmanGainIndicator', () => ({
  KalmanGainIndicator: () => <div data-testid="kalman-gain-indicator" />,
}));

vi.mock('@/components/visualizations/InnovationMeter', () => ({
  InnovationMeter: () => <div data-testid="innovation-meter" />,
}));

vi.mock('@/components/visualizations/FaultInjectionPanel', () => ({
  FaultInjectionPanel: () => <div data-testid="fault-injection-panel" />,
}));

vi.mock('@/components/visualizations/WhatIfStressSlider', () => ({
  WhatIfStressSlider: () => <div data-testid="what-if-stress-slider" />,
}));

vi.mock('@/components/visualizations/MonteCarloFanChart', () => ({
  MonteCarloFanChart: () => <div data-testid="monte-carlo-fan-chart" />,
}));

// Import the component after mocks are set up
import EngineDashboardPage from '@/app/engine/[id]/page';

// --- Helpers ---

function createEngineState(overrides: Partial<EngineState> = {}): EngineState {
  return {
    engineId: 1,
    rul: 80,
    healthIndex: 0.85,
    isProvisional: false,
    isUrgent: false,
    subsystems: [],
    trajectory: [],
    degradationRate: null,
    lastUpdateCycle: 50,
    ...overrides,
  };
}

describe('Engine Dashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useStore.setState({ engines: {}, selectedEngineId: null });
  });

  afterEach(() => {
    cleanup();
  });

  describe('RUL Indicator (Requirement 6.1)', () => {
    it('displays the RUL value and "cycles remaining" text when RUL is critical', () => {
      // The page passes rul to RULCountdown only when isCriticalRUL (rul < 30)
      useStore.setState({
        engines: { 1: createEngineState({ rul: 15 }) },
      });

      render(<EngineDashboardPage />);

      // RULCountdown renders the value in a motion.p (mocked as data-testid="rul-countdown-value")
      expect(screen.getByTestId('rul-countdown-value')).toHaveTextContent('15');
      expect(screen.getByText('cycles remaining')).toBeInTheDocument();
    });

    it('displays awaiting data state when RUL >= 30 (no simulation result)', () => {
      // When rul >= 30 and no simulation result, page passes expectedRul=null
      // RULCountdown shows "--" and "Awaiting data"
      useStore.setState({
        engines: { 1: createEngineState({ rul: 80 }) },
      });

      render(<EngineDashboardPage />);

      expect(screen.getByText('--')).toBeInTheDocument();
      expect(screen.getByText('Awaiting data')).toBeInTheDocument();
    });
  });

  describe('Critical RUL Emphasis (Requirement 6.4)', () => {
    it('applies red color class when RUL < 20', () => {
      useStore.setState({
        engines: { 1: createEngineState({ rul: 15 }) },
      });

      render(<EngineDashboardPage />);

      const rulValue = screen.getByTestId('rul-countdown-value');
      expect(rulValue).toHaveTextContent('15');
      // RULCountdown uses text-red-500 for rul < 20
      expect(rulValue.className).toContain('text-red-500');
    });

    it('applies amber color class when RUL is between 20 and 40', () => {
      useStore.setState({
        engines: { 1: createEngineState({ rul: 25 }) },
      });

      render(<EngineDashboardPage />);

      const rulValue = screen.getByTestId('rul-countdown-value');
      expect(rulValue).toHaveTextContent('25');
      // RULCountdown uses text-amber-500 for 20 <= rul <= 40
      expect(rulValue.className).toContain('text-amber-500');
    });

    it('applies amber color at boundary (RUL = 29)', () => {
      useStore.setState({
        engines: { 1: createEngineState({ rul: 29 }) },
      });

      render(<EngineDashboardPage />);

      const rulValue = screen.getByTestId('rul-countdown-value');
      expect(rulValue).toHaveTextContent('29');
      // 20 <= 29 <= 40 → amber
      expect(rulValue.className).toContain('text-amber-500');
    });

    it('shows awaiting data state when RUL >= 30 (no simulation active)', () => {
      // When rul >= 30 and no simulation, expectedRul is null → shows "--"
      useStore.setState({
        engines: { 1: createEngineState({ rul: 30 }) },
      });

      render(<EngineDashboardPage />);

      expect(screen.getByText('--')).toBeInTheDocument();
    });

    it('shows awaiting data state when RUL is high (100)', () => {
      // Same as above: rul >= 30, no simulation → null → "--"
      useStore.setState({
        engines: { 1: createEngineState({ rul: 100 }) },
      });

      render(<EngineDashboardPage />);

      expect(screen.getByText('--')).toBeInTheDocument();
    });

    it('shows red border glow when RUL < 20 (critical state)', () => {
      useStore.setState({
        engines: { 1: createEngineState({ rul: 10 }) },
      });

      render(<EngineDashboardPage />);

      const rulValue = screen.getByTestId('rul-countdown-value');
      expect(rulValue).toHaveTextContent('10');
      expect(rulValue.className).toContain('text-red-500');
    });

    it('does not show RUL number when RUL >= 30 and no simulation result', () => {
      useStore.setState({
        engines: { 1: createEngineState({ rul: 50 }) },
      });

      render(<EngineDashboardPage />);

      // With rul >= 30 and no simulation, expectedRul is null
      // The component renders "--" instead of a number
      expect(screen.getByText('--')).toBeInTheDocument();
      expect(screen.queryByTestId('rul-countdown-value')).not.toBeInTheDocument();
    });
  });

  describe('Trajectory Chart Data Binding (Requirement 6.2)', () => {
    it('renders the degradation curve chart with trajectory data', () => {
      const trajectory = [
        { cycle: 1, healthIndex: 0.98 },
        { cycle: 2, healthIndex: 0.96 },
        { cycle: 3, healthIndex: 0.94 },
      ];

      useStore.setState({
        engines: { 1: createEngineState({ trajectory }) },
      });

      render(<EngineDashboardPage />);

      // DegradationCurveProjection uses ComposedChart
      const chart = screen.getByTestId('composed-chart');
      const dataPoints = JSON.parse(chart.getAttribute('data-points')!);
      // Chart data is transformed: historical points have { cycle, historical, projected: null, confidenceBand: null }
      expect(dataPoints).toHaveLength(3);
      expect(dataPoints[0].cycle).toBe(1);
      expect(dataPoints[0].historical).toBe(0.98);
      expect(dataPoints[2].cycle).toBe(3);
      expect(dataPoints[2].historical).toBe(0.94);
    });

    it('shows empty state message when no trajectory data exists', () => {
      useStore.setState({
        engines: { 1: createEngineState({ trajectory: [] }) },
      });

      render(<EngineDashboardPage />);

      expect(
        screen.getByText(/No trajectory data available yet/)
      ).toBeInTheDocument();
    });

    it('displays degradation rate when available', () => {
      useStore.setState({
        engines: {
          1: createEngineState({
            degradationRate: 0.0123,
            trajectory: [{ cycle: 1, healthIndex: 0.9 }],
          }),
        },
      });

      render(<EngineDashboardPage />);

      expect(screen.getByTestId('degradation-rate')).toHaveTextContent('0.0123');
    });

    it('shows unavailable message when degradation rate is null', () => {
      useStore.setState({
        engines: { 1: createEngineState({ degradationRate: null }) },
      });

      render(<EngineDashboardPage />);

      expect(
        screen.getByText(/Degradation rate unavailable/)
      ).toBeInTheDocument();
    });
  });

  describe('Engine Selector Dropdown (Requirement 6.6)', () => {
    it('renders a dropdown with all available engines', () => {
      useStore.setState({
        engines: {
          1: createEngineState({ engineId: 1 }),
          3: createEngineState({ engineId: 3 }),
          5: createEngineState({ engineId: 5 }),
        },
      });

      render(<EngineDashboardPage />);

      const selector = screen.getByLabelText('Engine Unit:') as HTMLSelectElement;
      const options = Array.from(selector.querySelectorAll('option'));

      expect(options).toHaveLength(3);
      expect(options[0]).toHaveTextContent('Engine 1');
      expect(options[1]).toHaveTextContent('Engine 3');
      expect(options[2]).toHaveTextContent('Engine 5');
    });

    it('has the current engine selected', () => {
      useStore.setState({
        engines: {
          1: createEngineState({ engineId: 1 }),
          2: createEngineState({ engineId: 2 }),
        },
      });

      render(<EngineDashboardPage />);

      const selector = screen.getByLabelText('Engine Unit:') as HTMLSelectElement;
      expect(selector.value).toBe('1');
    });

    it('navigates to a new engine route on selection change', () => {
      useStore.setState({
        engines: {
          1: createEngineState({ engineId: 1 }),
          2: createEngineState({ engineId: 2 }),
          3: createEngineState({ engineId: 3 }),
        },
      });

      render(<EngineDashboardPage />);

      const selector = screen.getByLabelText('Engine Unit:') as HTMLSelectElement;
      fireEvent.change(selector, { target: { value: '3' } });

      expect(mockPush).toHaveBeenCalledWith('/engine/3');
    });

    it('shows a default option when no engines are in the store', () => {
      render(<EngineDashboardPage />);

      const selector = screen.getByLabelText('Engine Unit:') as HTMLSelectElement;
      const options = Array.from(selector.querySelectorAll('option'));

      expect(options).toHaveLength(1);
      expect(options[0]).toHaveTextContent('Engine 1');
    });
  });
});
