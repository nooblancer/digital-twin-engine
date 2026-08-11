'use client';

import { useMemo } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { useStore } from '@/store';

interface PredictionComparisonProps {
  sensorId: string;
}

/**
 * Data point shape for the merged chart data.
 * Combines correction history fields with observed sensor readings.
 */
interface ChartPoint {
  timestamp: number;
  raw_prediction: number | null;
  corrected_value: number | null;
  observed: number | null;
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
 * PredictionComparison chart — "Prediction vs Reality Overlay"
 *
 * Renders three line series on a single time-axis chart:
 * - Raw ML Prediction (amber dashed) — what the model predicted before correction
 * - Corrected Value (emerald solid) — what the EnKF produced after correction
 * - Observed Sensor (cyan dotted) — what the sensor actually read (ground truth)
 *
 * Data sources:
 * - raw_prediction + corrected_value from correctionHistory[sensorId] (Zustand correction metrics slice)
 * - observed from sensorData[sensorId] raw field (main Zustand store)
 *
 * Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6
 */
export function PredictionComparison({ sensorId }: PredictionComparisonProps) {
  const correctionHistory = useStore(
    (state) => state.correctionHistory[sensorId] ?? []
  );
  const sensorData = useStore((state) => state.sensorData[sensorId] ?? []);

  const chartData: ChartPoint[] = useMemo(() => {
    // Build a lookup map of observed (raw) sensor values by timestamp
    // Use a tolerance of 2 seconds for matching timestamps between sources
    const MATCH_TOLERANCE_MS = 2000;

    const observedByTimestamp = new Map<number, number>();
    for (const point of sensorData) {
      if (point.raw != null) {
        observedByTimestamp.set(point.timestamp, point.raw);
      }
    }

    return correctionHistory.map((point) => {
      // Find the closest observed value within tolerance
      let observed: number | null = null;

      // Try exact match first
      if (observedByTimestamp.has(point.timestamp)) {
        observed = observedByTimestamp.get(point.timestamp)!;
      } else {
        // Scan for nearest within tolerance
        const entries = Array.from(observedByTimestamp.entries());
        for (let i = 0; i < entries.length; i++) {
          const [ts, val] = entries[i];
          if (Math.abs(ts - point.timestamp) <= MATCH_TOLERANCE_MS) {
            observed = val;
            break;
          }
        }
      }

      return {
        timestamp: point.timestamp,
        raw_prediction: point.raw_prediction,
        corrected_value: point.corrected_value,
        observed,
      };
    });
  }, [correctionHistory, sensorData]);

  return (
    <div className="w-full">
      <ResponsiveContainer width="100%" height={280}>
        <LineChart
          data={chartData}
          margin={{ top: 8, right: 16, left: 8, bottom: 8 }}
        >
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
          {/* Raw ML Prediction — amber dashed */}
          <Line
            type="monotone"
            dataKey="raw_prediction"
            name="Raw Prediction"
            stroke="hsl(38, 92%, 50%)"
            strokeWidth={1.5}
            strokeDasharray="6 3"
            dot={false}
            isAnimationActive={false}
            connectNulls
          />
          {/* EnKF Corrected Value — emerald solid */}
          <Line
            type="monotone"
            dataKey="corrected_value"
            name="Corrected (EnKF)"
            stroke="hsl(160, 84%, 39%)"
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
            connectNulls
          />
          {/* Observed Sensor Reading — cyan dotted */}
          <Line
            type="monotone"
            dataKey="observed"
            name="Observed Sensor"
            stroke="hsl(192, 91%, 56%)"
            strokeWidth={1.5}
            strokeDasharray="2 3"
            dot={false}
            isAnimationActive={false}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
