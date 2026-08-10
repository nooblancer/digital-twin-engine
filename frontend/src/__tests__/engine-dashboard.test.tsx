/**
 * Unit tests for Engine Dashboard page
 * Tests RUL indicator rendering, critical emphasis, trajectory chart data binding,
 * and engine selector dropdown behavior.
 *
 * Validates: Requirements 6.1, 6.2, 6.4, 6.6
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

// Mock Recharts to avoid SVG rendering issues in jsdom
vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="responsive-container">{children}</div>
  ),
  LineChart: ({ data }: { data: unknown[] }) => (
    <div data-testid="line-chart" data-points={JSON.stringify(data)} />
  ),
  Line: ({ dataKey }: { dataKey: string }) => (
    <div data-testid={`line-${dataKey}`} />
  ),
  XAxis: () => <div data-testid="x-axis" />,
  YAxis: () => <div data-testid="y-axis" />,
  CartesianGrid: () => <div data-testid="cartesian-grid" />,
  Tooltip: () => <div data-testid="tooltip" />,
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
    it('displays the RUL value and "cycles remaining" text', () => {
      useStore.setState({
        engines: { 1: createEngineState({ rul: 80 }) },
      });

      render(<EngineDashboardPage />);

      expect(screen.getByTestId('rul-value')).toHaveTextContent('80');
      expect(screen.getByText('cycles remaining')).toBeInTheDocument();
    });

    it('displays default RUL of 125 when no engine data exists', () => {
      render(<EngineDashboardPage />);

      expect(screen.getByTestId('rul-value')).toHaveTextContent('125');
    });
  });

  describe('Critical RUL Emphasis (Requirement 6.4)', () => {
    it('applies critical styling when RUL < 30', () => {
      useStore.setState({
        engines: { 1: createEngineState({ rul: 15 }) },
      });

      render(<EngineDashboardPage />);

      const rulValue = screen.getByTestId('rul-value');
      expect(rulValue).toHaveTextContent('15');
      // Critical RUL uses text-7xl and text-destructive classes
      expect(rulValue.className).toContain('text-7xl');
      expect(rulValue.className).toContain('text-destructive');
    });

    it('applies critical styling at the boundary (RUL = 29)', () => {
      useStore.setState({
        engines: { 1: createEngineState({ rul: 29 }) },
      });

      render(<EngineDashboardPage />);

      const rulValue = screen.getByTestId('rul-value');
      expect(rulValue.className).toContain('text-7xl');
      expect(rulValue.className).toContain('text-destructive');
    });

    it('applies normal styling when RUL >= 30', () => {
      useStore.setState({
        engines: { 1: createEngineState({ rul: 30 }) },
      });

      render(<EngineDashboardPage />);

      const rulValue = screen.getByTestId('rul-value');
      expect(rulValue.className).toContain('text-5xl');
      expect(rulValue.className).not.toContain('text-destructive');
    });

    it('applies normal styling when RUL is high (100)', () => {
      useStore.setState({
        engines: { 1: createEngineState({ rul: 100 }) },
      });

      render(<EngineDashboardPage />);

      const rulValue = screen.getByTestId('rul-value');
      expect(rulValue.className).toContain('text-5xl');
      expect(rulValue.className).not.toContain('text-7xl');
    });

    it('shows critical warning message when RUL < 30', () => {
      useStore.setState({
        engines: { 1: createEngineState({ rul: 10 }) },
      });

      render(<EngineDashboardPage />);

      expect(
        screen.getByText(/Critical — Immediate maintenance attention required/)
      ).toBeInTheDocument();
    });

    it('does not show critical warning when RUL >= 30', () => {
      useStore.setState({
        engines: { 1: createEngineState({ rul: 50 }) },
      });

      render(<EngineDashboardPage />);

      expect(
        screen.queryByText(/Critical — Immediate maintenance attention required/)
      ).not.toBeInTheDocument();
    });
  });

  describe('Trajectory Chart Data Binding (Requirement 6.2)', () => {
    it('renders the line chart with trajectory data', () => {
      const trajectory = [
        { cycle: 1, healthIndex: 0.98 },
        { cycle: 2, healthIndex: 0.96 },
        { cycle: 3, healthIndex: 0.94 },
      ];

      useStore.setState({
        engines: { 1: createEngineState({ trajectory }) },
      });

      render(<EngineDashboardPage />);

      const chart = screen.getByTestId('line-chart');
      const dataPoints = JSON.parse(chart.getAttribute('data-points')!);
      expect(dataPoints).toEqual(trajectory);
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
