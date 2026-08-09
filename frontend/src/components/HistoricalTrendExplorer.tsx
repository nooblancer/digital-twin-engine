'use client';

import { useState, useCallback } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';

interface HistoryDataPoint {
  timestamp: string;
  value: number;
}

interface HistoricalTrendExplorerProps {
  /** Base URL for the API (default: http://localhost:8000) */
  baseUrl?: string;
}

/**
 * Builds the history API URL with properly encoded query parameters.
 */
export function buildHistoryUrl(
  baseUrl: string,
  sensorId: string,
  start: string,
  end: string,
  limit: number,
  offset: number
): string {
  const params = new URLSearchParams({
    start,
    end,
    limit: String(limit),
    offset: String(offset),
  });
  return `${baseUrl}/sensors/${encodeURIComponent(sensorId)}/state/history?${params}`;
}

/**
 * Validates that the start timestamp is strictly before the end timestamp.
 */
export function validateTimeRange(start: string, end: string): boolean {
  return new Date(start) < new Date(end);
}

export function HistoricalTrendExplorer({
  baseUrl = 'http://localhost:8000',
}: HistoricalTrendExplorerProps) {
  const [sensorId, setSensorId] = useState('');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [limit] = useState(100);
  const [offset, setOffset] = useState(0);

  const [data, setData] = useState<HistoryDataPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  const fetchHistory = useCallback(
    async (currentOffset: number) => {
      // Client-side validation
      if (!validateTimeRange(start, end)) {
        setValidationError('Start time must be before end time');
        return;
      }
      setValidationError(null);

      setLoading(true);
      setError(null);

      try {
        const url = buildHistoryUrl(baseUrl, sensorId, start, end, limit, currentOffset);
        const response = await fetch(url);

        if (!response.ok) {
          throw new Error(`Request failed: ${response.status}`);
        }

        const json = await response.json();
        setData(json.results ?? []);
        setOffset(currentOffset);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'An unexpected error occurred');
        setData([]);
      } finally {
        setLoading(false);
      }
    },
    [baseUrl, sensorId, start, end, limit]
  );

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setOffset(0);
    fetchHistory(0);
  };

  const handlePrevious = () => {
    const newOffset = Math.max(0, offset - limit);
    fetchHistory(newOffset);
  };

  const handleNext = () => {
    const newOffset = offset + limit;
    fetchHistory(newOffset);
  };

  const handleRetry = () => {
    fetchHistory(offset);
  };

  const isFormValid = sensorId.trim() !== '' && start !== '' && end !== '';

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="text-sm font-medium text-foreground mb-3">Historical Trend Explorer</h3>

      {/* Query Form */}
      <form onSubmit={handleSubmit} className="space-y-3 mb-4">
        {/* Sensor ID */}
        <div>
          <label htmlFor="hte-sensor-id" className="block text-xs text-muted-foreground mb-1">
            Sensor ID
          </label>
          <input
            id="hte-sensor-id"
            type="text"
            value={sensorId}
            onChange={(e) => setSensorId(e.target.value)}
            placeholder="e.g. sensor-001"
            className="w-full rounded border border-input bg-background px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
          />
        </div>

        {/* Date Range */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor="hte-start" className="block text-xs text-muted-foreground mb-1">
              Start
            </label>
            <input
              id="hte-start"
              type="datetime-local"
              value={start}
              onChange={(e) => setStart(e.target.value)}
              className="w-full rounded border border-input bg-background px-3 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
          <div>
            <label htmlFor="hte-end" className="block text-xs text-muted-foreground mb-1">
              End
            </label>
            <input
              id="hte-end"
              type="datetime-local"
              value={end}
              onChange={(e) => setEnd(e.target.value)}
              className="w-full rounded border border-input bg-background px-3 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
        </div>

        {/* Validation error */}
        {validationError && (
          <p className="text-xs text-red-500" role="alert">
            {validationError}
          </p>
        )}

        {/* Submit */}
        <button
          type="submit"
          disabled={!isFormValid || loading}
          className="w-full rounded bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground disabled:opacity-50 disabled:cursor-not-allowed hover:opacity-90 transition-opacity"
        >
          {loading ? 'Loading...' : 'Query History'}
        </button>
      </form>

      {/* Loading skeleton */}
      {loading && (
        <div className="h-48 w-full rounded bg-muted animate-pulse" aria-label="Loading chart" />
      )}

      {/* Error state with retry */}
      {error && !loading && (
        <div className="rounded border border-destructive/30 bg-destructive/10 p-3 text-center">
          <p className="text-sm text-destructive mb-2">{error}</p>
          <button
            onClick={handleRetry}
            className="rounded bg-destructive px-3 py-1 text-xs font-medium text-destructive-foreground hover:opacity-90 transition-opacity"
          >
            Retry
          </button>
        </div>
      )}

      {/* Chart */}
      {!loading && !error && data.length > 0 && (
        <>
          <div className="h-48 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="hsl(var(--chart-grid))"
                  opacity={0.5}
                />
                <XAxis
                  dataKey="timestamp"
                  tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }}
                  tickFormatter={(value: string) => {
                    const d = new Date(value);
                    return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
                  }}
                />
                <YAxis
                  tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }}
                  width={40}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: 'hsl(var(--card))',
                    border: '1px solid hsl(var(--border))',
                    borderRadius: '6px',
                    fontSize: '12px',
                  }}
                  labelStyle={{ color: 'hsl(var(--foreground))' }}
                />
                <Line
                  type="monotone"
                  dataKey="value"
                  stroke="hsl(var(--chart-predicted))"
                  strokeWidth={1.5}
                  dot={false}
                  activeDot={{ r: 3 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* Pagination controls */}
          <div className="flex items-center justify-between mt-3">
            <button
              onClick={handlePrevious}
              disabled={offset === 0}
              className="rounded border border-border px-3 py-1 text-xs font-medium text-foreground disabled:opacity-50 disabled:cursor-not-allowed hover:bg-accent transition-colors"
            >
              Previous
            </button>
            <span className="text-xs text-muted-foreground">
              Showing {offset + 1}–{offset + data.length}
            </span>
            <button
              onClick={handleNext}
              disabled={data.length < limit}
              className="rounded border border-border px-3 py-1 text-xs font-medium text-foreground disabled:opacity-50 disabled:cursor-not-allowed hover:bg-accent transition-colors"
            >
              Next
            </button>
          </div>
        </>
      )}

      {/* Empty state */}
      {!loading && !error && data.length === 0 && offset === 0 && sensorId && start && end && (
        <p className="text-xs text-muted-foreground text-center py-4">
          No data available for the selected range.
        </p>
      )}
    </div>
  );
}
