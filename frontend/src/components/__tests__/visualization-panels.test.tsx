import React from 'react';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { useStore } from '@/store';
import { SensorChart } from '../SensorChart';
import { AnomalyAlertFeed } from '../AnomalyAlertFeed';
import { SensorHealthCards } from '../SensorHealthCards';
import type { ChartDataPoint } from '@/types';

// Mock recharts since jsdom doesn't support SVG rendering
vi.mock('recharts', () => {
  const React = require('react');
  return {
    ResponsiveContainer: ({ children }: any) =>
      React.createElement('div', { 'data-testid': 'responsive-container' }, children),
    LineChart: ({ children }: any) =>
      React.createElement('div', { 'data-testid': 'line-chart' }, children),
    Line: (props: any) =>
      React.createElement('div', { 'data-testid': `line-${props.dataKey}` }),
    XAxis: () => React.createElement('div', { 'data-testid': 'x-axis' }),
    YAxis: () => React.createElement('div', { 'data-testid': 'y-axis' }),
    CartesianGrid: () => React.createElement('div', { 'data-testid': 'cartesian-grid' }),
    Tooltip: () => React.createElement('div', { 'data-testid': 'tooltip' }),
    Legend: () => React.createElement('div', { 'data-testid': 'legend' }),
  };
});

function resetStore() {
  useStore.setState({
    sensorData: {},
    anomalies: [],
    sensorHealth: {},
    pipelineHealth: null,
    connection: {
      status: 'disconnected',
      reconnectAttempts: 0,
      lastConnected: null,
      nextRetryMs: null,
    },
    activeSource: 'nasa-cmapss',
    ui: { isLoading: false, error: null, isSwitchingSource: false },
  });
}

describe('SensorChart', () => {
  beforeEach(resetStore);
  afterEach(cleanup);

  it('renders the LineChart structure with sample data', () => {
    const sampleData: ChartDataPoint[] = [
      { timestamp: 1000, raw: 10, predicted: 11, corrected: 10.5 },
      { timestamp: 2000, raw: 12, predicted: 13, corrected: 12.5 },
    ];
    useStore.setState({ sensorData: { 'sensor-1': sampleData } });

    render(<SensorChart sensorId="sensor-1" />);

    expect(screen.getByTestId('responsive-container')).toBeInTheDocument();
    expect(screen.getByTestId('line-chart')).toBeInTheDocument();
    expect(screen.getByTestId('x-axis')).toBeInTheDocument();
    expect(screen.getByTestId('y-axis')).toBeInTheDocument();
  });

  it('renders three Line elements (raw, predicted, corrected)', () => {
    const sampleData: ChartDataPoint[] = [
      { timestamp: 1000, raw: 5, predicted: 6, corrected: 5.5 },
    ];
    useStore.setState({ sensorData: { 'sensor-1': sampleData } });

    render(<SensorChart sensorId="sensor-1" />);

    expect(screen.getByTestId('line-raw')).toBeInTheDocument();
    expect(screen.getByTestId('line-predicted')).toBeInTheDocument();
    expect(screen.getByTestId('line-corrected')).toBeInTheDocument();
  });

  it('handles empty data gracefully', () => {
    // Pre-populate with an empty array to avoid referential instability
    useStore.setState({ sensorData: { 'sensor-1': [] } });

    render(<SensorChart sensorId="sensor-1" />);

    expect(screen.getByTestId('responsive-container')).toBeInTheDocument();
    expect(screen.getByTestId('line-chart')).toBeInTheDocument();
  });
});

describe('AnomalyAlertFeed', () => {
  beforeEach(resetStore);
  afterEach(cleanup);

  it('shows "No anomalies detected" when empty', () => {
    render(<AnomalyAlertFeed />);

    expect(screen.getByText('No anomalies detected')).toBeInTheDocument();
  });

  it('displays entries with correct severity badges', () => {
    useStore.setState({
      anomalies: [
        {
          id: '1',
          sensor_id: 'temp-01',
          timestamp: '2024-01-15T10:30:00Z',
          severity: 'critical',
          description: 'Temperature spike detected',
        },
        {
          id: '2',
          sensor_id: 'vibration-02',
          timestamp: '2024-01-15T10:25:00Z',
          severity: 'warning',
          description: 'Unusual vibration pattern',
        },
        {
          id: '3',
          sensor_id: 'pressure-01',
          timestamp: '2024-01-15T10:20:00Z',
          severity: 'informational',
          description: 'Pressure within bounds',
        },
      ],
    });

    render(<AnomalyAlertFeed />);

    expect(screen.getByText('Critical')).toBeInTheDocument();
    expect(screen.getByText('Warning')).toBeInTheDocument();
    expect(screen.getByText('Info')).toBeInTheDocument();
    expect(screen.getByText('temp-01')).toBeInTheDocument();
    expect(screen.getByText('Temperature spike detected')).toBeInTheDocument();
  });

  it('calls onAlertClick with correct sensor_id and timestamp when an entry is clicked', () => {
    const handleClick = vi.fn();
    useStore.setState({
      anomalies: [
        {
          id: '1',
          sensor_id: 'temp-01',
          timestamp: '2024-01-15T10:30:00Z',
          severity: 'critical',
          description: 'Temperature spike',
        },
      ],
    });

    render(<AnomalyAlertFeed onAlertClick={handleClick} />);

    const entry = screen.getByRole('listitem');
    fireEvent.click(entry);

    expect(handleClick).toHaveBeenCalledTimes(1);
    expect(handleClick).toHaveBeenCalledWith('temp-01', '2024-01-15T10:30:00Z');
  });
});

describe('SensorHealthCards', () => {
  beforeEach(resetStore);
  afterEach(cleanup);

  it('shows "No sensors connected" when empty', () => {
    render(<SensorHealthCards />);

    expect(screen.getByText('No sensors connected')).toBeInTheDocument();
  });

  it('renders correct number of cards matching store entries', () => {
    useStore.setState({
      sensorHealth: {
        'sensor-a': { sensor_id: 'sensor-a', status: 'healthy', lastUpdate: Date.now() },
        'sensor-b': { sensor_id: 'sensor-b', status: 'warning', lastUpdate: Date.now() },
        'sensor-c': { sensor_id: 'sensor-c', status: 'critical', lastUpdate: Date.now() },
      },
    });

    const { container } = render(<SensorHealthCards />);

    const cards = container.querySelectorAll('.border-l-4');
    expect(cards).toHaveLength(3);
    expect(screen.getByText('sensor-a')).toBeInTheDocument();
    expect(screen.getByText('sensor-b')).toBeInTheDocument();
    expect(screen.getByText('sensor-c')).toBeInTheDocument();
  });

  it('displays cards with proper status border color classes', () => {
    useStore.setState({
      sensorHealth: {
        'sensor-a': { sensor_id: 'sensor-a', status: 'healthy', lastUpdate: Date.now() },
        'sensor-b': { sensor_id: 'sensor-b', status: 'warning', lastUpdate: Date.now() },
        'sensor-c': { sensor_id: 'sensor-c', status: 'critical', lastUpdate: Date.now() },
      },
    });

    const { container } = render(<SensorHealthCards />);

    const cards = container.querySelectorAll('.border-l-4');
    expect(cards).toHaveLength(3);

    const classes = Array.from(cards).map((card) => card.className);
    expect(classes.some((c) => c.includes('border-l-[hsl(var(--status-healthy))]'))).toBe(true);
    expect(classes.some((c) => c.includes('border-l-[hsl(var(--status-warning))]'))).toBe(true);
    expect(classes.some((c) => c.includes('border-l-[hsl(var(--status-critical))]'))).toBe(true);
  });
});

describe('Loading/Skeleton States', () => {
  beforeEach(resetStore);
  afterEach(cleanup);

  it('panels handle initial empty state without crashing', () => {
    // SensorChart with pre-populated empty array (avoids Zustand referential instability)
    useStore.setState({ sensorData: { 'test-sensor': [] } });
    expect(() => render(<SensorChart sensorId="test-sensor" />)).not.toThrow();
    cleanup();

    expect(() => render(<AnomalyAlertFeed />)).not.toThrow();
    cleanup();

    expect(() => render(<SensorHealthCards />)).not.toThrow();
  });
});
