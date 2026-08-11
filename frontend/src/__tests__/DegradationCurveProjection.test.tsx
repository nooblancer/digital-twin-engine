/**
 * Unit tests for DegradationCurveProjection component.
 *
 * Tests:
 * - Renders historical line when no projection data
 * - Renders both historical and projection when data provided
 * - Shows empty state when no historical data
 * - Renders critical threshold reference line
 * - Renders "Now" separator when projection is present
 *
 * Requirements: 10.1–10.6
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';

// --- Mock Recharts ---
interface MockLineProps {
  dataKey: string;
  stroke?: string;
  strokeWidth?: number;
  name?: string;
  connectNulls?: boolean;
}

interface MockAreaProps {
  dataKey: string;
  fillOpacity?: number;
  fill?: string;
  name?: string;
}

interface MockReferenceLineProps {
  y?: number;
  x?: number;
  stroke?: string;
  strokeDasharray?: string;
  label?: { value?: string } | string;
}

const capturedLines: MockLineProps[] = [];
const capturedAreas: MockAreaProps[] = [];
const capturedReferenceLines: MockReferenceLineProps[] = [];

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="responsive-container">{children}</div>
  ),
  ComposedChart: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="composed-chart">{children}</div>
  ),
  Line: (props: MockLineProps) => {
    capturedLines.push(props);
    return (
      <div
        data-testid={`line-${props.dataKey}`}
        data-stroke={props.stroke}
        data-stroke-width={props.strokeWidth}
        data-name={props.name || ''}
        data-connect-nulls={String(props.connectNulls ?? '')}
      />
    );
  },
  Area: (props: MockAreaProps) => {
    capturedAreas.push(props);
    return (
      <div
        data-testid={`area-${props.dataKey}`}
        data-fill-opacity={props.fillOpacity}
        data-fill={props.fill}
        data-name={props.name || ''}
      />
    );
  },
  ReferenceLine: (props: MockReferenceLineProps) => {
    capturedReferenceLines.push(props);
    const labelValue =
      typeof props.label === 'object' ? props.label?.value : props.label;
    return (
      <div
        data-testid={`reference-line-${labelValue || 'unknown'}`}
        data-y={props.y ?? ''}
        data-x={props.x ?? ''}
        data-stroke={props.stroke}
        data-stroke-dasharray={props.strokeDasharray || ''}
      />
    );
  },
  XAxis: () => <div data-testid="x-axis" />,
  YAxis: () => <div data-testid="y-axis" />,
  CartesianGrid: () => <div data-testid="cartesian-grid" />,
  Tooltip: () => <div data-testid="tooltip" />,
}));

// --- Import component AFTER mocks ---
import { DegradationCurveProjection } from '@/components/visualizations/DegradationCurveProjection';

// --- Test data ---
const historicalData = [
  { cycle: 1, healthIndex: 0.95 },
  { cycle: 2, healthIndex: 0.92 },
  { cycle: 3, healthIndex: 0.88 },
  { cycle: 4, healthIndex: 0.85 },
  { cycle: 5, healthIndex: 0.80 },
];

const projectionPercentiles = {
  5: [0.70, 0.60, 0.50, 0.40, 0.30],
  25: [0.74, 0.66, 0.57, 0.48, 0.38],
  50: [0.78, 0.72, 0.64, 0.55, 0.46],
  75: [0.82, 0.78, 0.71, 0.62, 0.54],
  95: [0.86, 0.84, 0.78, 0.70, 0.62],
};

// --- Tests ---

describe('DegradationCurveProjection', () => {
  beforeEach(() => {
    capturedLines.length = 0;
    capturedAreas.length = 0;
    capturedReferenceLines.length = 0;
  });

  afterEach(() => {
    cleanup();
  });

  it('renders historical line when no projection data', () => {
    render(
      <DegradationCurveProjection
        historicalData={historicalData}
        projectionPercentiles={null}
      />
    );

    // Historical line should be present
    const historicalLine = screen.getByTestId('line-historical');
    expect(historicalLine).toBeInTheDocument();
    expect(historicalLine.getAttribute('data-stroke')).toBe('#10b981');
    expect(historicalLine.getAttribute('data-name')).toBe('Historical Health Index');

    // Projected line should still be rendered (with null data points)
    const projectedLine = screen.getByTestId('line-projected');
    expect(projectedLine).toBeInTheDocument();
  });

  it('does NOT render "Now" separator when projection is null', () => {
    render(
      <DegradationCurveProjection
        historicalData={historicalData}
        projectionPercentiles={null}
      />
    );

    // "Now" reference line should not be present when no projection
    expect(screen.queryByTestId('reference-line-Now')).not.toBeInTheDocument();
  });

  it('renders both historical and projection lines when data provided', () => {
    render(
      <DegradationCurveProjection
        historicalData={historicalData}
        projectionPercentiles={projectionPercentiles}
      />
    );

    // Historical solid emerald line
    const historicalLine = screen.getByTestId('line-historical');
    expect(historicalLine).toBeInTheDocument();
    expect(historicalLine.getAttribute('data-stroke')).toBe('#10b981');

    // Projected gradient line
    const projectedLine = screen.getByTestId('line-projected');
    expect(projectedLine).toBeInTheDocument();
    // The stroke is a gradient url — verify it's a url reference
    expect(projectedLine.getAttribute('data-stroke')).toContain('url(#');

    // Confidence band area (5th-95th)
    const confidenceArea = screen.getByTestId('area-confidenceBand');
    expect(confidenceArea).toBeInTheDocument();
    expect(confidenceArea.getAttribute('data-fill')).toBe('#00d4ff');
    expect(confidenceArea.getAttribute('data-fill-opacity')).toBe('0.1');
  });

  it('renders "Now" vertical separator when projection is present', () => {
    render(
      <DegradationCurveProjection
        historicalData={historicalData}
        projectionPercentiles={projectionPercentiles}
      />
    );

    const nowLine = screen.getByTestId('reference-line-Now');
    expect(nowLine).toBeInTheDocument();
    // Should be at the last historical cycle (5)
    expect(nowLine.getAttribute('data-x')).toBe('5');
  });

  it('renders Critical Threshold reference line at y=0.4', () => {
    render(
      <DegradationCurveProjection
        historicalData={historicalData}
        projectionPercentiles={null}
      />
    );

    const criticalLine = screen.getByTestId('reference-line-Critical Threshold');
    expect(criticalLine).toBeInTheDocument();
    expect(criticalLine.getAttribute('data-y')).toBe('0.4');
    expect(criticalLine.getAttribute('data-stroke')).toBe('#ef4444');
    expect(criticalLine.getAttribute('data-stroke-dasharray')).toBe('6 4');
  });

  it('renders empty state when historical data is empty', () => {
    render(
      <DegradationCurveProjection
        historicalData={[]}
        projectionPercentiles={null}
      />
    );

    expect(
      screen.getByText(/No trajectory data available yet/)
    ).toBeInTheDocument();
    // No chart should render
    expect(screen.queryByTestId('composed-chart')).not.toBeInTheDocument();
  });

  it('renders confidence band Area with correct name', () => {
    render(
      <DegradationCurveProjection
        historicalData={historicalData}
        projectionPercentiles={projectionPercentiles}
      />
    );

    const confidenceArea = screen.getByTestId('area-confidenceBand');
    expect(confidenceArea.getAttribute('data-name')).toBe(
      '90% Confidence Interval'
    );
  });
});
