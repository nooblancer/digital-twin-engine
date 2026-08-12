/**
 * Unit tests for MonteCarloFanChart component.
 *
 * Tests:
 * - Renders correct number of Area components when percentiles provided
 * - Renders empty state when percentiles is null
 *
 * Requirements: 9.1–9.8
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';

// --- Mock Recharts ---
// Capture Area component instances to verify count and props

interface MockAreaProps {
  dataKey: string;
  fillOpacity?: number;
  fill?: string;
  stroke?: string;
  name?: string;
}

const capturedAreas: MockAreaProps[] = [];

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="responsive-container">{children}</div>
  ),
  AreaChart: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="area-chart">{children}</div>
  ),
  Area: (props: MockAreaProps) => {
    capturedAreas.push(props);
    return (
      <div
        data-testid={`area-${props.dataKey}`}
        data-fill-opacity={props.fillOpacity}
        data-fill={props.fill}
        data-stroke={props.stroke}
        data-name={props.name || ''}
      />
    );
  },
  XAxis: () => <div data-testid="x-axis" />,
  YAxis: () => <div data-testid="y-axis" />,
  CartesianGrid: () => <div data-testid="cartesian-grid" />,
  Tooltip: () => <div data-testid="tooltip" />,
  ReferenceLine: (props: { y?: number; strokeDasharray?: string }) => (
    <div data-testid="reference-line" data-y={props.y} data-dash={props.strokeDasharray} />
  ),
}));

// --- Import component AFTER mocks ---
import { MonteCarloFanChart } from '@/components/visualizations/MonteCarloFanChart';

describe('MonteCarloFanChart', () => {
  const mockPercentiles = {
    5: [0.9, 0.85, 0.8, 0.75, 0.7],
    25: [0.92, 0.88, 0.84, 0.8, 0.76],
    50: [0.95, 0.91, 0.87, 0.83, 0.79],
    75: [0.97, 0.94, 0.91, 0.88, 0.84],
    95: [0.99, 0.96, 0.94, 0.92, 0.89],
  };

  afterEach(() => {
    capturedAreas.length = 0;
    cleanup();
  });

  it('renders 3 Area components when percentiles are provided', () => {
    render(<MonteCarloFanChart percentiles={mockPercentiles} />);

    // The component renders 3 Area components:
    // 1. band95 (5th-95th)
    // 2. band75 (25th-75th)
    // 3. median (50th percentile line)
    expect(screen.getByTestId('area-band95')).toBeInTheDocument();
    expect(screen.getByTestId('area-band75')).toBeInTheDocument();
    expect(screen.getByTestId('area-median')).toBeInTheDocument();

    // Verify exactly 3 Area components were rendered
    expect(capturedAreas).toHaveLength(3);
  });

  it('renders Areas with correct opacity values for bands', () => {
    render(<MonteCarloFanChart percentiles={mockPercentiles} />);

    const band95 = screen.getByTestId('area-band95');
    const band75 = screen.getByTestId('area-band75');
    const median = screen.getByTestId('area-median');

    // 5th-95th: gradient fill with 0.3 opacity
    expect(band95.getAttribute('data-fill-opacity')).toBe('0.3');
    // 25th-75th: moderate (0.2)
    expect(band75.getAttribute('data-fill-opacity')).toBe('0.2');
    // Median line: gradient fill underneath
    expect(median.getAttribute('data-fill-opacity')).toBe('0.2');
  });

  it('renders median with emerald stroke color', () => {
    render(<MonteCarloFanChart percentiles={mockPercentiles} />);

    const median = screen.getByTestId('area-median');
    expect(median.getAttribute('data-stroke')).toBe('#10b981');
  });

  it('renders empty state message when percentiles is null', () => {
    render(<MonteCarloFanChart percentiles={null} />);

    expect(
      screen.getByText(
        'No simulation data available. Adjust the stress slider to generate a projection.'
      )
    ).toBeInTheDocument();

    // Should NOT render any chart areas
    expect(screen.queryByTestId('area-band95')).not.toBeInTheDocument();
    expect(screen.queryByTestId('area-band75')).not.toBeInTheDocument();
    expect(screen.queryByTestId('area-median')).not.toBeInTheDocument();
    expect(capturedAreas).toHaveLength(0);
  });

  it('does not render chart container when percentiles is null', () => {
    render(<MonteCarloFanChart percentiles={null} />);

    expect(screen.queryByTestId('responsive-container')).not.toBeInTheDocument();
    expect(screen.queryByTestId('area-chart')).not.toBeInTheDocument();
  });

  it('renders Critical Threshold reference line at y=0.4', () => {
    render(<MonteCarloFanChart percentiles={mockPercentiles} />);

    const refLine = screen.getByTestId('reference-line');
    expect(refLine).toBeInTheDocument();
    expect(refLine.getAttribute('data-y')).toBe('0.4');
    expect(refLine.getAttribute('data-dash')).toBe('6 4');
  });
});
