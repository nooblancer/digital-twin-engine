/**
 * Unit tests for EnhancedLineChart component.
 *
 * Tests:
 * - Gradient defs rendered (linearGradient elements for each series)
 * - Glow dot on last point (larger dot with radial glow)
 * - Custom tooltip content (sensor name, value, deviation)
 * - Performance: max 200 data points visible per series
 *
 * Requirements: 9.1, 9.2, 9.4, 9.5
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { cloneElement } from 'react';

// --- Mock Recharts ---
// We need to capture props passed to Area, Line, and defs content to verify
// gradient definitions, glow dot behavior, and tooltip wiring.

interface MockLineProps {
  dataKey: string;
  stroke?: string;
  strokeWidth?: number;
  dot?: boolean | object;
  activeDot?: unknown;
  isAnimationActive?: boolean;
  name?: string;
  type?: string;
}

interface MockAreaProps {
  dataKey: string;
  fill?: string;
  stroke?: string;
  fillOpacity?: number;
  isAnimationActive?: boolean;
  type?: string;
}

interface MockTooltipProps {
  content?: unknown;
  cursor?: unknown;
}

const capturedLines: MockLineProps[] = [];
const capturedAreas: MockAreaProps[] = [];
let capturedTooltip: MockTooltipProps | null = null;
let capturedDefsChildren: React.ReactNode = null;

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="responsive-container">{children}</div>
  ),
  ComposedChart: ({ children, data }: { children: React.ReactNode; data?: unknown[] }) => (
    <div data-testid="composed-chart" data-point-count={Array.isArray(data) ? data.length : 0}>
      {children}
    </div>
  ),
  Line: (props: MockLineProps) => {
    capturedLines.push(props);
    return (
      <div
        data-testid={`line-${props.dataKey}`}
        data-stroke={props.stroke}
        data-stroke-width={props.strokeWidth}
        data-dot={String(props.dot)}
        data-animation-active={String(props.isAnimationActive)}
        data-name={props.name || ''}
      />
    );
  },
  Area: (props: MockAreaProps) => {
    capturedAreas.push(props);
    return (
      <div
        data-testid={`area-${props.dataKey}`}
        data-fill={props.fill}
        data-stroke={props.stroke || 'none'}
        data-animation-active={String(props.isAnimationActive)}
      />
    );
  },
  XAxis: () => <div data-testid="x-axis" />,
  YAxis: () => <div data-testid="y-axis" />,
  CartesianGrid: () => <div data-testid="cartesian-grid" />,
  Tooltip: (props: MockTooltipProps) => {
    capturedTooltip = props;
    return <div data-testid="tooltip" />;
  },
}));

// --- Import component AFTER mocks ---
import { EnhancedLineChart } from '@/components/visualizations/EnhancedLineChart';
import type { SeriesConfig, EnhancedLineChartProps } from '@/components/visualizations/EnhancedLineChart';

// --- Test data helpers ---

function makeSampleData(count: number): Array<Record<string, number>> {
  return Array.from({ length: count }, (_, i) => ({
    timestamp: Date.now() - (count - i) * 1000,
    temperature: 400 + i * 0.5,
    pressure: 30 + i * 0.1,
  }));
}

const defaultSeries: SeriesConfig[] = [
  { dataKey: 'temperature', color: '#00d4ff', name: 'Temperature' },
  { dataKey: 'pressure', color: '#7c3aed', name: 'Pressure' },
];

// --- Tests ---

describe('EnhancedLineChart', () => {
  beforeEach(() => {
    capturedLines.length = 0;
    capturedAreas.length = 0;
    capturedTooltip = null;
    capturedDefsChildren = null;
  });

  afterEach(() => {
    cleanup();
  });

  describe('Gradient defs rendering (Requirement 9.1)', () => {
    it('renders linearGradient elements in defs for each series when gradientFill=true', () => {
      const data = makeSampleData(10);
      const { container } = render(
        <EnhancedLineChart data={data} series={defaultSeries} gradientFill={true} />
      );

      // The component renders <defs> with <linearGradient> elements
      const gradients = container.querySelectorAll('linearGradient');
      expect(gradients.length).toBe(2); // one per series
    });

    it('each gradient has two stops: color at 0.3 opacity → transparent', () => {
      const data = makeSampleData(10);
      const { container } = render(
        <EnhancedLineChart data={data} series={defaultSeries} gradientFill={true} />
      );

      const gradients = container.querySelectorAll('linearGradient');
      gradients.forEach((grad) => {
        const stops = grad.querySelectorAll('stop');
        expect(stops.length).toBe(2);
        // First stop: 0% offset, 0.3 opacity
        expect(stops[0].getAttribute('offset')).toBe('0%');
        expect(stops[0].getAttribute('stop-opacity')).toBe('0.3');
        // Second stop: 100% offset, 0 opacity
        expect(stops[1].getAttribute('offset')).toBe('100%');
        expect(stops[1].getAttribute('stop-opacity')).toBe('0');
      });
    });

    it('gradient IDs reference the correct series colors', () => {
      const data = makeSampleData(10);
      const { container } = render(
        <EnhancedLineChart data={data} series={defaultSeries} gradientFill={true} />
      );

      const gradients = container.querySelectorAll('linearGradient');
      // First gradient should reference cyan (#00d4ff)
      const stops0 = gradients[0].querySelectorAll('stop');
      expect(stops0[0].getAttribute('stop-color')).toBe('#00d4ff');
      // Second gradient should reference violet (#7c3aed)
      const stops1 = gradients[1].querySelectorAll('stop');
      expect(stops1[0].getAttribute('stop-color')).toBe('#7c3aed');
    });

    it('renders Area components with gradient fill URL reference', () => {
      const data = makeSampleData(10);
      render(
        <EnhancedLineChart data={data} series={defaultSeries} gradientFill={true} />
      );

      // Each series should have an Area with fill="url(#gradient-id)"
      expect(capturedAreas.length).toBe(2);
      capturedAreas.forEach((area) => {
        expect(area.fill).toMatch(/^url\(#enhanced-gradient-/);
      });
    });

    it('does NOT render gradient areas when gradientFill=false', () => {
      const data = makeSampleData(10);
      const { container } = render(
        <EnhancedLineChart data={data} series={defaultSeries} gradientFill={false} />
      );

      // No linearGradient elements
      const gradients = container.querySelectorAll('linearGradient');
      expect(gradients.length).toBe(0);
      // No Area components
      expect(capturedAreas.length).toBe(0);
    });
  });

  describe('Glow dot on last point (Requirement 9.2)', () => {
    it('passes an activeDot renderer function when showGlowDot=true', () => {
      const data = makeSampleData(5);
      render(
        <EnhancedLineChart data={data} series={defaultSeries} showGlowDot={true} />
      );

      // Each Line should have an activeDot that is a function
      expect(capturedLines.length).toBe(2);
      capturedLines.forEach((line) => {
        expect(typeof line.activeDot).toBe('function');
      });
    });

    it('does NOT pass activeDot renderer when showGlowDot=false', () => {
      const data = makeSampleData(5);
      render(
        <EnhancedLineChart data={data} series={defaultSeries} showGlowDot={false} />
      );

      capturedLines.forEach((line) => {
        expect(line.activeDot).toBeUndefined();
      });
    });

    it('glow dot renderer returns larger circles for last data point', () => {
      const data = makeSampleData(5);
      render(
        <EnhancedLineChart data={data} series={defaultSeries} showGlowDot={true} />
      );

      // Get the activeDot function from the first line
      const activeDotFn = capturedLines[0].activeDot as (props: Record<string, unknown>) => React.ReactNode;

      // Simulate rendering the LAST point (index = data.length - 1)
      const { container: dotContainer } = render(
        <svg>{activeDotFn({ cx: 100, cy: 50, index: 4 }) as React.ReactElement}</svg>
      );

      const circles = dotContainer.querySelectorAll('circle');
      // Should render 2 circles for glow effect (outer glow + inner dot)
      expect(circles.length).toBe(2);
      // Outer glow circle has larger radius (r=8)
      expect(circles[0].getAttribute('r')).toBe('8');
      expect(circles[0].getAttribute('opacity')).toBe('0.2');
      // Inner dot (r=5)
      expect(circles[1].getAttribute('r')).toBe('5');
    });

    it('glow dot renderer returns null for non-last data points', () => {
      const data = makeSampleData(5);
      render(
        <EnhancedLineChart data={data} series={defaultSeries} showGlowDot={true} />
      );

      const activeDotFn = capturedLines[0].activeDot as (props: Record<string, unknown>) => React.ReactNode;

      // Simulate rendering a NON-last point (index = 2)
      const result = activeDotFn({ cx: 100, cy: 50, index: 2 });
      expect(result).toBeNull();
    });
  });

  describe('Custom tooltip content (Requirement 9.4)', () => {
    it('passes a custom tooltip content element to Recharts Tooltip', () => {
      const data = makeSampleData(5);
      render(
        <EnhancedLineChart data={data} series={defaultSeries} />
      );

      expect(capturedTooltip).not.toBeNull();
      expect(capturedTooltip!.content).toBeDefined();
    });

    it('custom tooltip renders sensor name, value, and timestamp', () => {
      const data = makeSampleData(5);
      render(
        <EnhancedLineChart data={data} series={defaultSeries} />
      );

      // The content is a React element (<ChartTooltip seriesNames={...} />).
      // We clone it with additional props to simulate Recharts passing data.
      const tooltipElement = capturedTooltip!.content as React.ReactElement;

      const mockPayload = [
        {
          name: 'Temperature',
          value: 425.5,
          dataKey: 'temperature',
          color: '#00d4ff',
          payload: { timestamp: Date.now() - 5000, temperature: 425.5 },
        },
      ];

      const { getByText } = render(
        cloneElement(tooltipElement, {
          active: true,
          payload: mockPayload,
          label: Date.now() - 5000,
        })
      );

      // Should show sensor name
      expect(getByText('Temperature')).toBeInTheDocument();
      // Should show value formatted
      expect(getByText('Value: 425.50')).toBeInTheDocument();
    });

    it('custom tooltip shows deviation from baseline when available', () => {
      const data = makeSampleData(5);
      render(
        <EnhancedLineChart data={data} series={defaultSeries} />
      );

      const tooltipElement = capturedTooltip!.content as React.ReactElement;

      const mockPayload = [
        {
          name: 'Temperature',
          value: 430.0,
          dataKey: 'temperature',
          color: '#00d4ff',
          payload: {
            timestamp: Date.now(),
            temperature: 430.0,
            temperature_baseline: 400.0,  // baseline value
          },
        },
      ];

      const { getByText } = render(
        cloneElement(tooltipElement, {
          active: true,
          payload: mockPayload,
          label: Date.now(),
        })
      );

      // Deviation = 430.0 - 400.0 = +30.00
      expect(getByText(/Δ \+30\.00/)).toBeInTheDocument();
    });

    it('custom tooltip does NOT render when inactive', () => {
      const data = makeSampleData(5);
      render(
        <EnhancedLineChart data={data} series={defaultSeries} />
      );

      const tooltipElement = capturedTooltip!.content as React.ReactElement;

      const { container } = render(
        cloneElement(tooltipElement, {
          active: false,
          payload: [],
          label: 0,
        })
      );

      // Should render nothing (null) — only the wrapper div from render
      expect(container.innerHTML).toBe('');
    });
  });

  describe('Performance: max 200 points visible (Requirement 9.5)', () => {
    it('limits visible data to 200 points when data exceeds limit', () => {
      const data = makeSampleData(300);
      render(
        <EnhancedLineChart data={data} series={defaultSeries} />
      );

      // ComposedChart should receive only 200 points
      const chart = screen.getByTestId('composed-chart');
      expect(chart.getAttribute('data-point-count')).toBe('200');
    });

    it('passes all data when below 200 point limit', () => {
      const data = makeSampleData(50);
      render(
        <EnhancedLineChart data={data} series={defaultSeries} />
      );

      const chart = screen.getByTestId('composed-chart');
      expect(chart.getAttribute('data-point-count')).toBe('50');
    });

    it('disables animation when data exceeds 150 points', () => {
      const data = makeSampleData(180);
      render(
        <EnhancedLineChart data={data} series={defaultSeries} gradientFill={true} />
      );

      // Lines should have animation disabled
      capturedLines.forEach((line) => {
        expect(line.isAnimationActive).toBe(false);
      });
      // Areas should have animation disabled
      capturedAreas.forEach((area) => {
        expect(area.isAnimationActive).toBe(false);
      });
    });

    it('enables animation when data is 150 points or fewer', () => {
      const data = makeSampleData(100);
      render(
        <EnhancedLineChart data={data} series={defaultSeries} gradientFill={true} />
      );

      capturedLines.forEach((line) => {
        expect(line.isAnimationActive).toBe(true);
      });
      capturedAreas.forEach((area) => {
        expect(area.isAnimationActive).toBe(true);
      });
    });
  });

  describe('Line rendering', () => {
    it('renders one Line per series with correct stroke colors', () => {
      const data = makeSampleData(10);
      render(
        <EnhancedLineChart data={data} series={defaultSeries} />
      );

      expect(capturedLines.length).toBe(2);
      expect(capturedLines[0].stroke).toBe('#00d4ff');
      expect(capturedLines[1].stroke).toBe('#7c3aed');
    });

    it('renders Lines with dot=false for performance', () => {
      const data = makeSampleData(10);
      render(
        <EnhancedLineChart data={data} series={defaultSeries} />
      );

      capturedLines.forEach((line) => {
        expect(line.dot).toBe(false);
      });
    });
  });
});
