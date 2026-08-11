/**
 * Unit tests for visualization components.
 *
 * Tests:
 * - PredictionComparison renders 3 lines with correct colors and legend
 * - ConfidenceBandChart renders 3 Area components with correct opacity ordering
 * - InnovationMeter shows correct color for small/medium/large values
 * - KalmanGainIndicator shows two bars with distinct colors
 * - AccuracyScoreboard displays "Collecting data..." when metrics are null
 * - AccuracyScoreboard shows green for positive improvement, amber for negative
 *
 * Requirements: 7.1–7.6, 8.1–8.6, 9.1–9.6, 10.1–10.5, 11.1–11.7
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';

// --- Mock Recharts ---
// Capture props to verify colors, dataKeys, and opacity ordering

interface MockLineProps {
  dataKey: string;
  stroke?: string;
  strokeDasharray?: string;
  name?: string;
}

interface MockAreaProps {
  dataKey: string;
  fillOpacity?: number;
  fill?: string;
  name?: string;
}

const capturedLines: MockLineProps[] = [];
const capturedAreas: MockAreaProps[] = [];

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="responsive-container">{children}</div>
  ),
  LineChart: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="line-chart">{children}</div>
  ),
  ComposedChart: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="composed-chart">{children}</div>
  ),
  Line: (props: MockLineProps) => {
    capturedLines.push(props);
    return <div data-testid={`line-${props.dataKey}`} data-stroke={props.stroke} data-dasharray={props.strokeDasharray || ''} data-name={props.name || ''} />;
  },
  Area: (props: MockAreaProps) => {
    capturedAreas.push(props);
    return <div data-testid={`area-${props.dataKey}`} data-fill-opacity={props.fillOpacity} data-fill={props.fill} data-name={props.name || ''} />;
  },
  XAxis: () => <div data-testid="x-axis" />,
  YAxis: () => <div data-testid="y-axis" />,
  CartesianGrid: () => <div data-testid="cartesian-grid" />,
  Tooltip: () => <div data-testid="tooltip" />,
  Legend: () => <div data-testid="legend" />,
}));

// --- Mock framer-motion ---
vi.mock('framer-motion', () => ({
  motion: {
    div: ({ children, style, animate, className, ...rest }: Record<string, unknown>) => (
      <div
        data-testid="motion-div"
        className={className as string}
        style={{ ...(style as object), ...(animate as object) }}
        {...rest}
      >
        {children as React.ReactNode}
      </div>
    ),
  },
}));

// --- Mock store ---
let mockStoreState: Record<string, unknown> = {};

vi.mock('@/store', () => ({
  useStore: (selector: (state: Record<string, unknown>) => unknown) => selector(mockStoreState),
}));

// --- Mock fetch for AccuracyScoreboard ---
const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

// --- Import components AFTER mocks ---
import { PredictionComparison } from '@/components/visualizations/PredictionComparison';
import { ConfidenceBandChart } from '@/components/visualizations/ConfidenceBandChart';
import { InnovationMeter, getBarColor, getBarWidth } from '@/components/visualizations/InnovationMeter';
import { KalmanGainIndicator } from '@/components/visualizations/KalmanGainIndicator';
import { AccuracyScoreboard } from '@/components/visualizations/AccuracyScoreboard';

// --- Tests ---

describe('PredictionComparison', () => {
  beforeEach(() => {
    capturedLines.length = 0;
    capturedAreas.length = 0;
    mockStoreState = {
      correctionHistory: {
        'sensor-001': [
          { timestamp: 1000, raw_prediction: 10, corrected_value: 11, ensemble_spread: 0.5, kalman_gain: 0.4, innovation_magnitude: 1.2, confidence_band_95: null },
          { timestamp: 2000, raw_prediction: 12, corrected_value: 13, ensemble_spread: 0.4, kalman_gain: 0.5, innovation_magnitude: 0.8, confidence_band_95: null },
        ],
      },
      sensorData: {
        'sensor-001': [
          { timestamp: 1000, raw: 10.5, corrected: 11.0 },
          { timestamp: 2000, raw: 12.5, corrected: 13.0 },
        ],
      },
    };
  });

  afterEach(() => {
    cleanup();
  });

  it('renders 3 Line components for raw_prediction, corrected_value, and observed', () => {
    render(<PredictionComparison sensorId="sensor-001" />);

    const rawLine = screen.getByTestId('line-raw_prediction');
    const correctedLine = screen.getByTestId('line-corrected_value');
    const observedLine = screen.getByTestId('line-observed');

    expect(rawLine).toBeInTheDocument();
    expect(correctedLine).toBeInTheDocument();
    expect(observedLine).toBeInTheDocument();
  });

  it('renders raw_prediction with amber color and dashed stroke', () => {
    render(<PredictionComparison sensorId="sensor-001" />);

    const rawLine = screen.getByTestId('line-raw_prediction');
    // amber: hsl(38, 92%, 50%)
    expect(rawLine.getAttribute('data-stroke')).toBe('hsl(38, 92%, 50%)');
    expect(rawLine.getAttribute('data-dasharray')).toBe('6 3');
  });

  it('renders corrected_value with emerald color and solid stroke', () => {
    render(<PredictionComparison sensorId="sensor-001" />);

    const correctedLine = screen.getByTestId('line-corrected_value');
    // emerald: hsl(160, 84%, 39%)
    expect(correctedLine.getAttribute('data-stroke')).toBe('hsl(160, 84%, 39%)');
    expect(correctedLine.getAttribute('data-dasharray')).toBe('');
  });

  it('renders observed sensor with cyan color and dotted stroke', () => {
    render(<PredictionComparison sensorId="sensor-001" />);

    const observedLine = screen.getByTestId('line-observed');
    // cyan: hsl(192, 91%, 56%)
    expect(observedLine.getAttribute('data-stroke')).toBe('hsl(192, 91%, 56%)');
    expect(observedLine.getAttribute('data-dasharray')).toBe('2 3');
  });

  it('renders a Legend component', () => {
    render(<PredictionComparison sensorId="sensor-001" />);
    expect(screen.getByTestId('legend')).toBeInTheDocument();
  });

  it('renders correct series names for the legend', () => {
    render(<PredictionComparison sensorId="sensor-001" />);

    const rawLine = screen.getByTestId('line-raw_prediction');
    const correctedLine = screen.getByTestId('line-corrected_value');
    const observedLine = screen.getByTestId('line-observed');

    expect(rawLine.getAttribute('data-name')).toBe('Raw Prediction');
    expect(correctedLine.getAttribute('data-name')).toBe('Corrected (EnKF)');
    expect(observedLine.getAttribute('data-name')).toBe('Observed Sensor');
  });
});

describe('ConfidenceBandChart', () => {
  beforeEach(() => {
    capturedLines.length = 0;
    capturedAreas.length = 0;
    mockStoreState = {
      correctionHistory: {
        'sensor-002': [
          { timestamp: 1000, corrected_value: 50, ensemble_spread: 2.0, raw_prediction: 48, kalman_gain: 0.6, innovation_magnitude: 1.0, confidence_band_95: [46, 54] },
          { timestamp: 2000, corrected_value: 52, ensemble_spread: 1.5, raw_prediction: 50, kalman_gain: 0.5, innovation_magnitude: 0.7, confidence_band_95: [49, 55] },
        ],
      },
    };
  });

  afterEach(() => {
    cleanup();
  });

  it('renders 3 Area components for confidence bands', () => {
    render(<ConfidenceBandChart sensorId="sensor-002" />);

    expect(screen.getByTestId('area-band95')).toBeInTheDocument();
    expect(screen.getByTestId('area-band75')).toBeInTheDocument();
    expect(screen.getByTestId('area-band50')).toBeInTheDocument();
  });

  it('renders Areas with correct opacity ordering (0.1, 0.2, 0.35)', () => {
    render(<ConfidenceBandChart sensorId="sensor-002" />);

    const band95 = screen.getByTestId('area-band95');
    const band75 = screen.getByTestId('area-band75');
    const band50 = screen.getByTestId('area-band50');

    expect(band95.getAttribute('data-fill-opacity')).toBe('0.1');
    expect(band75.getAttribute('data-fill-opacity')).toBe('0.2');
    expect(band50.getAttribute('data-fill-opacity')).toBe('0.35');
  });

  it('renders Areas with increasing opacity from outer to inner band', () => {
    render(<ConfidenceBandChart sensorId="sensor-002" />);

    const band95Opacity = parseFloat(screen.getByTestId('area-band95').getAttribute('data-fill-opacity')!);
    const band75Opacity = parseFloat(screen.getByTestId('area-band75').getAttribute('data-fill-opacity')!);
    const band50Opacity = parseFloat(screen.getByTestId('area-band50').getAttribute('data-fill-opacity')!);

    expect(band95Opacity).toBeLessThan(band75Opacity);
    expect(band75Opacity).toBeLessThan(band50Opacity);
  });

  it('renders a center line for the corrected state', () => {
    render(<ConfidenceBandChart sensorId="sensor-002" />);
    expect(screen.getByTestId('line-mean')).toBeInTheDocument();
  });
});

describe('InnovationMeter', () => {
  afterEach(() => {
    cleanup();
  });

  describe('getBarColor helper', () => {
    it('returns green for small values (< 33%)', () => {
      expect(getBarColor(0.0)).toBe('#10b981');
      expect(getBarColor(0.1)).toBe('#10b981');
      expect(getBarColor(0.32)).toBe('#10b981');
    });

    it('returns amber for medium values (33%–66%)', () => {
      expect(getBarColor(0.33)).toBe('#f59e0b');
      expect(getBarColor(0.5)).toBe('#f59e0b');
      expect(getBarColor(0.65)).toBe('#f59e0b');
    });

    it('returns red for large values (> 66%)', () => {
      expect(getBarColor(0.66)).toBe('#ef4444');
      expect(getBarColor(0.8)).toBe('#ef4444');
      expect(getBarColor(1.0)).toBe('#ef4444');
    });
  });

  describe('getBarWidth helper', () => {
    it('returns 0 when magnitude is null', () => {
      expect(getBarWidth(null, 5.0)).toBe(0);
    });

    it('returns 0 when magnitude is 0 or negative', () => {
      expect(getBarWidth(0, 5.0)).toBe(0);
      expect(getBarWidth(-1, 5.0)).toBe(0);
    });

    it('returns proportional width for values below threshold', () => {
      expect(getBarWidth(2.5, 5.0)).toBe(50);
      expect(getBarWidth(1.0, 5.0)).toBe(20);
    });

    it('clamps to 100% when magnitude exceeds threshold', () => {
      expect(getBarWidth(10.0, 5.0)).toBe(100);
      expect(getBarWidth(100.0, 5.0)).toBe(100);
    });
  });

  describe('component rendering', () => {
    it('shows green bar color for small innovation (< 33% of threshold)', () => {
      // magnitude = 1.0, threshold = 5.0 → normalized = 0.2 → green
      mockStoreState = { latestInnovation: { 'sensor-003': 1.0 } };
      render(<InnovationMeter sensorId="sensor-003" maxThreshold={5.0} />);

      const motionDivs = screen.getAllByTestId('motion-div');
      const barDiv = motionDivs[0];
      // jsdom converts hex to rgb in style
      expect(barDiv.style.backgroundColor).toBe('rgb(16, 185, 129)');
    });

    it('shows amber bar color for medium innovation (33%–66% of threshold)', () => {
      // magnitude = 2.5, threshold = 5.0 → normalized = 0.5 → amber
      mockStoreState = { latestInnovation: { 'sensor-003': 2.5 } };
      render(<InnovationMeter sensorId="sensor-003" maxThreshold={5.0} />);

      const motionDivs = screen.getAllByTestId('motion-div');
      const barDiv = motionDivs[0];
      expect(barDiv.style.backgroundColor).toBe('rgb(245, 158, 11)');
    });

    it('shows red bar color for large innovation (> 66% of threshold)', () => {
      // magnitude = 4.0, threshold = 5.0 → normalized = 0.8 → red
      mockStoreState = { latestInnovation: { 'sensor-003': 4.0 } };
      render(<InnovationMeter sensorId="sensor-003" maxThreshold={5.0} />);

      const motionDivs = screen.getAllByTestId('motion-div');
      const barDiv = motionDivs[0];
      expect(barDiv.style.backgroundColor).toBe('rgb(239, 68, 68)');
    });

    it('displays the numeric value alongside the bar', () => {
      mockStoreState = { latestInnovation: { 'sensor-003': 2.345 } };
      render(<InnovationMeter sensorId="sensor-003" maxThreshold={5.0} />);

      expect(screen.getByText('2.345')).toBeInTheDocument();
    });

    it('displays "—" when no data is available', () => {
      mockStoreState = { latestInnovation: {} };
      render(<InnovationMeter sensorId="sensor-003" />);

      expect(screen.getByText('—')).toBeInTheDocument();
    });
  });
});

describe('KalmanGainIndicator', () => {
  afterEach(() => {
    cleanup();
  });

  it('renders two progress bars with distinct colors (violet and emerald)', () => {
    mockStoreState = { latestKalmanGain: { 'sensor-004': 0.6 } };
    render(<KalmanGainIndicator sensorId="sensor-004" />);

    const motionDivs = screen.getAllByTestId('motion-div');
    // Should have 2 bars: sensor trust (violet) and model trust (emerald)
    expect(motionDivs.length).toBe(2);

    const sensorBar = motionDivs[0];
    const modelBar = motionDivs[1];

    expect(sensorBar.style.backgroundColor).toBe('rgb(124, 58, 237)');
    expect(modelBar.style.backgroundColor).toBe('rgb(16, 185, 129)');
  });

  it('displays "Trusting Sensor" and "Trusting Model" labels', () => {
    mockStoreState = { latestKalmanGain: { 'sensor-004': 0.7 } };
    render(<KalmanGainIndicator sensorId="sensor-004" />);

    expect(screen.getByText('Trusting Sensor')).toBeInTheDocument();
    expect(screen.getByText('Trusting Model')).toBeInTheDocument();
  });

  it('shows correct percentage labels for sensor and model trust', () => {
    mockStoreState = { latestKalmanGain: { 'sensor-004': 0.6 } };
    render(<KalmanGainIndicator sensorId="sensor-004" />);

    // sensor trust = 0.6 * 100 = 60.0%
    expect(screen.getByText('60.0%')).toBeInTheDocument();
    // model trust = (1 - 0.6) * 100 = 40.0%
    expect(screen.getByText('40.0%')).toBeInTheDocument();
  });

  it('shows "Waiting for data…" when kalman gain is null', () => {
    mockStoreState = { latestKalmanGain: {} };
    render(<KalmanGainIndicator sensorId="sensor-004" />);

    expect(screen.getByText('Waiting for data…')).toBeInTheDocument();
  });
});

describe('AccuracyScoreboard', () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it('displays "Collecting data..." when API returns null metrics', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        raw_rmse: null,
        raw_mae: null,
        raw_r_squared: null,
        corrected_rmse: null,
        corrected_mae: null,
        corrected_r_squared: null,
        improvement_percentage: null,
        sample_count: 0,
      }),
    });

    render(<AccuracyScoreboard pollingIntervalMs={5000} />);

    await waitFor(() => {
      expect(screen.getByText('Collecting data...')).toBeInTheDocument();
    });
  });

  it('shows green color for positive improvement percentage', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        raw_rmse: 0.1234,
        raw_mae: 0.09,
        raw_r_squared: 0.85,
        corrected_rmse: 0.0678,
        corrected_mae: 0.05,
        corrected_r_squared: 0.95,
        improvement_percentage: 45.2,
        sample_count: 150,
      }),
    });

    render(<AccuracyScoreboard pollingIntervalMs={5000} />);

    await waitFor(() => {
      const improvementEl = screen.getByText('+45.2%');
      expect(improvementEl).toBeInTheDocument();
      // Green class: text-emerald-400
      expect(improvementEl.className).toContain('text-emerald-400');
    });
  });

  it('shows amber/red color for negative improvement percentage', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        raw_rmse: 0.1234,
        raw_mae: 0.09,
        raw_r_squared: 0.85,
        corrected_rmse: 0.15,
        corrected_mae: 0.12,
        corrected_r_squared: 0.7,
        improvement_percentage: -8.5,
        sample_count: 50,
      }),
    });

    render(<AccuracyScoreboard pollingIntervalMs={5000} />);

    await waitFor(() => {
      const improvementEl = screen.getByText('-8.5%');
      expect(improvementEl).toBeInTheDocument();
      // Red class for negative: text-red-400
      expect(improvementEl.className).toContain('text-red-400');
    });
  });

  it('displays raw and corrected RMSE values', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        raw_rmse: 0.1234,
        raw_mae: 0.09,
        raw_r_squared: 0.85,
        corrected_rmse: 0.0678,
        corrected_mae: 0.05,
        corrected_r_squared: 0.95,
        improvement_percentage: 45.0,
        sample_count: 200,
      }),
    });

    render(<AccuracyScoreboard pollingIntervalMs={5000} />);

    await waitFor(() => {
      expect(screen.getByText('0.1234')).toBeInTheDocument();
      expect(screen.getByText('0.0678')).toBeInTheDocument();
    });
  });

  it('displays sample count', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        raw_rmse: 0.1,
        raw_mae: 0.08,
        raw_r_squared: 0.9,
        corrected_rmse: 0.05,
        corrected_mae: 0.04,
        corrected_r_squared: 0.95,
        improvement_percentage: 50.0,
        sample_count: 1247,
      }),
    });

    render(<AccuracyScoreboard pollingIntervalMs={5000} />);

    await waitFor(() => {
      expect(screen.getByText(/1,247 samples/)).toBeInTheDocument();
    });
  });
});
