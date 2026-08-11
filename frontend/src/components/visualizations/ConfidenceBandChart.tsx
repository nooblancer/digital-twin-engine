'use client';

import {
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { useStore } from '@/store';

interface ConfidenceBandChartProps {
  sensorId: string;
  height?: number;
}

interface BandDataPoint {
  timestamp: number;
  mean: number;
  band95: [number, number];
  band75: [number, number];
  band50: [number, number];
}

function formatTimestamp(timestamp: number): string {
  const now = Date.now();
  const secondsAgo = Math.round((now - timestamp) / 1000);
  if (secondsAgo <= 0) return 'now';
  if (secondsAgo < 60) return `${secondsAgo}s ago`;
  const minutesAgo = Math.round(secondsAgo / 60);
  return `${minutesAgo}m ago`;
}

/**
 * Compute confidence bands for a single data point.
 * The ensemble_spread from the store IS the ensemble std.
 * Bands: 95% (±1.96×std), 75% (±1.15×std), 50% (±0.674×std)
 */
export function computeBands(correctedValue: number, ensembleSpread: number): Omit<BandDataPoint, 'timestamp'> {
  const mean = correctedValue;
  const std = ensembleSpread;
  return {
    mean,
    band95: [mean - 1.96 * std, mean + 1.96 * std],
    band75: [mean - 1.15 * std, mean + 1.15 * std],
    band50: [mean - 0.674 * std, mean + 0.674 * std],
  };
}

export function ConfidenceBandChart({ sensorId, height = 250 }: ConfidenceBandChartProps) {
  const correctionHistory = useStore(
    (state) => state.correctionHistory[sensorId] ?? []
  );

  const chartData = correctionHistory.map((point) => {
    const bands = computeBands(point.corrected_value, point.ensemble_spread);
    return {
      timestamp: point.timestamp,
      mean: bands.mean,
      band95: bands.band95,
      band75: bands.band75,
      band50: bands.band50,
    };
  });

  return (
    <div className="w-full">
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={chartData} margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
          <CartesianGrid
            stroke="hsl(220, 10%, 20%)"
            strokeDasharray="3 3"
          />
          <XAxis
            dataKey="timestamp"
            tickFormatter={formatTimestamp}
            stroke="hsl(215, 12%, 58%)"
            tick={{ fontSize: 11 }}
          />
          <YAxis
            stroke="hsl(215, 12%, 58%)"
            tick={{ fontSize: 11 }}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: 'hsl(220, 13%, 9%)',
              border: '1px solid hsl(220, 12%, 18%)',
              borderRadius: '6px',
              color: 'hsl(210, 20%, 92%)',
            }}
            labelFormatter={(label) => formatTimestamp(Number(label))}
          />
          <Legend />

          {/* 95% confidence band — widest, faintest */}
          <Area
            type="monotone"
            dataKey="band95"
            name="95% CI"
            stroke="none"
            fill="#00d4ff"
            fillOpacity={0.1}
            isAnimationActive={false}
          />

          {/* 75% confidence band — middle opacity */}
          <Area
            type="monotone"
            dataKey="band75"
            name="75% CI"
            stroke="none"
            fill="#00d4ff"
            fillOpacity={0.2}
            isAnimationActive={false}
          />

          {/* 50% confidence band — most opaque */}
          <Area
            type="monotone"
            dataKey="band50"
            name="50% CI"
            stroke="none"
            fill="#00d4ff"
            fillOpacity={0.35}
            isAnimationActive={false}
          />

          {/* Corrected state center line */}
          <Line
            type="monotone"
            dataKey="mean"
            name="Corrected State"
            stroke="#10b981"
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
