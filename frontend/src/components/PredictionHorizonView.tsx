'use client';

import { useEffect, useState, useCallback } from 'react';
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
import type { PredictionEntry } from '@/types';

interface PredictionHorizonViewProps {
  sensorId: string;
  endpoint?: string;
}

interface PredictionResponse {
  sensor_id: string;
  predictions: PredictionEntry[];
}

interface ChartPoint {
  timestamp: number;
  value: number;
  model: string;
}

const MODEL_STYLES: Record<string, { color: string; dashArray?: string }> = {
  LSTM: { color: 'hsl(192, 40%, 55%)' },
  XGBoost: { color: 'hsl(35, 60%, 55%)', dashArray: '5 5' },
};

function formatTime(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export function PredictionHorizonView({
  sensorId,
  endpoint = 'http://localhost:8000',
}: PredictionHorizonViewProps) {
  const [predictions, setPredictions] = useState<PredictionEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchPredictions = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch(
        `${endpoint}/sensors/${encodeURIComponent(sensorId)}/state/predicted`
      );

      if (!response.ok) {
        if (response.status === 404) {
          setPredictions([]);
          return;
        }
        throw new Error(`Failed to fetch predictions: ${response.status}`);
      }

      const data: PredictionResponse = await response.json();
      setPredictions(data.predictions);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An unexpected error occurred');
    } finally {
      setLoading(false);
    }
  }, [endpoint, sensorId]);

  useEffect(() => {
    fetchPredictions();
  }, [fetchPredictions]);

  // Transform predictions to chart data
  const chartData: ChartPoint[] = predictions.map((p) => ({
    timestamp: new Date(p.timestamp).getTime(),
    value: p.state_vector[0],
    model: p.model_used,
  }));

  // Split chart data by model for separate Line elements
  const models = Array.from(new Set(chartData.map((p) => p.model)));

  // Build per-model datasets: each point has timestamp + value only for its model
  const mergedData = buildMergedChartData(chartData, models);

  // Compute horizon labels per model
  const horizonLabels = models.map((model) => {
    const modelPredictions = predictions.filter((p) => p.model_used === model);
    if (modelPredictions.length === 0) return null;
    const maxHorizon = Math.max(
      ...modelPredictions.map((p) => p.prediction_horizon_seconds)
    );
    return { model, horizonSeconds: maxHorizon };
  }).filter(Boolean) as { model: string; horizonSeconds: number }[];

  // Loading state
  if (loading) {
    return (
      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="text-sm font-medium text-foreground mb-3">
          Prediction Horizon
        </h3>
        <div className="space-y-2 animate-pulse">
          <div className="h-4 w-3/4 bg-muted rounded" />
          <div className="h-[200px] w-full bg-muted rounded" />
          <div className="h-3 w-1/2 bg-muted rounded" />
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="text-sm font-medium text-foreground mb-3">
          Prediction Horizon
        </h3>
        <div className="text-sm text-destructive mb-2">{error}</div>
        <button
          onClick={fetchPredictions}
          className="text-xs font-medium px-3 py-1.5 rounded border border-border bg-secondary text-secondary-foreground hover:bg-accent transition-colors"
        >
          Retry
        </button>
      </div>
    );
  }

  // Empty state
  if (predictions.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="text-sm font-medium text-foreground mb-3">
          Prediction Horizon
        </h3>
        <p className="text-sm text-muted-foreground">
          No predictions available for this sensor.
        </p>
        <button
          onClick={fetchPredictions}
          className="mt-2 text-xs font-medium px-3 py-1.5 rounded border border-border bg-secondary text-secondary-foreground hover:bg-accent transition-colors"
        >
          Refresh
        </button>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      {/* Header with refresh button */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-foreground">
          Prediction Horizon
        </h3>
        <button
          onClick={fetchPredictions}
          className="text-xs font-medium px-3 py-1.5 rounded border border-border bg-secondary text-secondary-foreground hover:bg-accent transition-colors"
          aria-label="Refresh predictions"
        >
          Refresh
        </button>
      </div>

      {/* Chart */}
      <ResponsiveContainer width="100%" height={250}>
        <LineChart
          data={mergedData}
          margin={{ top: 8, right: 16, left: 8, bottom: 8 }}
        >
          <CartesianGrid stroke="hsl(220, 10%, 20%)" strokeDasharray="3 3" />
          <XAxis
            dataKey="timestamp"
            tickFormatter={formatTime}
            stroke="hsl(215, 12%, 58%)"
            tick={{ fontSize: 11 }}
            type="number"
            domain={['dataMin', 'dataMax']}
          />
          <YAxis stroke="hsl(215, 12%, 58%)" tick={{ fontSize: 11 }} />
          <Tooltip
            contentStyle={{
              backgroundColor: 'hsl(220, 13%, 9%)',
              border: '1px solid hsl(220, 12%, 18%)',
              borderRadius: '6px',
              color: 'hsl(210, 20%, 92%)',
            }}
            labelFormatter={(label) => formatTime(Number(label))}
          />
          <Legend />
          {models.map((model) => {
            const style = MODEL_STYLES[model] ?? {
              color: 'hsl(215, 20%, 55%)',
            };
            return (
              <Line
                key={model}
                type="monotone"
                dataKey={model}
                name={model}
                stroke={style.color}
                strokeWidth={1.5}
                strokeDasharray={style.dashArray}
                dot={false}
                isAnimationActive={false}
                connectNulls={false}
              />
            );
          })}
        </LineChart>
      </ResponsiveContainer>

      {/* Horizon duration labels */}
      {horizonLabels.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-3">
          {horizonLabels.map(({ model, horizonSeconds }) => {
            const style = MODEL_STYLES[model] ?? {
              color: 'hsl(215, 20%, 55%)',
            };
            return (
              <span
                key={model}
                className="text-xs text-muted-foreground"
                style={{ color: style.color }}
              >
                {model}: {formatHorizon(horizonSeconds)} horizon
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}

/**
 * Build merged chart data where each object has a timestamp and
 * one key per model (value or undefined if that model has no point at that timestamp).
 */
function buildMergedChartData(
  chartData: ChartPoint[],
  models: string[]
): Record<string, number | undefined>[] {
  // Group points by timestamp
  const byTimestamp = new Map<number, Record<string, number | undefined>>();

  for (const point of chartData) {
    let entry = byTimestamp.get(point.timestamp);
    if (!entry) {
      entry = { timestamp: point.timestamp };
      byTimestamp.set(point.timestamp, entry);
    }
    entry[point.model] = point.value;
  }

  // Sort by timestamp ascending
  const sorted = Array.from(byTimestamp.values()).sort(
    (a, b) => (a.timestamp as number) - (b.timestamp as number)
  );

  // Ensure all model keys exist (undefined if no data at that timestamp)
  for (const entry of sorted) {
    for (const model of models) {
      if (!(model in entry)) {
        entry[model] = undefined;
      }
    }
  }

  return sorted;
}

function formatHorizon(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}
