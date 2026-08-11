'use client';

import { useEffect, useState, useCallback } from 'react';

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface AccuracyMetrics {
  raw_rmse: number | null;
  raw_mae: number | null;
  raw_r_squared: number | null;
  corrected_rmse: number | null;
  corrected_mae: number | null;
  corrected_r_squared: number | null;
  improvement_percentage: number | null;
  sample_count: number;
}

interface AccuracyScoreboardProps {
  pollingIntervalMs?: number;
}

export function AccuracyScoreboard({
  pollingIntervalMs = 5000,
}: AccuracyScoreboardProps) {
  const [metrics, setMetrics] = useState<AccuracyMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchMetrics = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/metrics/accuracy`);
      if (!response.ok) {
        setError(`API error: ${response.status}`);
        return;
      }
      const data: AccuracyMetrics = await response.json();
      setMetrics(data);
      setError(null);
    } catch (err) {
      setError('Failed to fetch metrics');
    }
  }, []);

  useEffect(() => {
    // Fetch immediately on mount
    fetchMetrics();

    // Set up polling interval
    const intervalId = setInterval(fetchMetrics, pollingIntervalMs);

    return () => {
      clearInterval(intervalId);
    };
  }, [fetchMetrics, pollingIntervalMs]);

  // Determine if we have valid metrics (all null means insufficient samples)
  const hasData =
    metrics !== null && metrics.improvement_percentage !== null;

  // Color for improvement percentage
  function getImprovementColor(value: number): string {
    if (value > 0) return 'text-emerald-400';
    if (value === 0) return 'text-amber-400';
    return 'text-red-400';
  }

  function getImprovementBgGlow(value: number): string {
    if (value > 0) return 'shadow-[0_0_20px_rgba(16,185,129,0.15)]';
    if (value === 0) return 'shadow-[0_0_20px_rgba(245,158,11,0.15)]';
    return 'shadow-[0_0_20px_rgba(239,68,68,0.15)]';
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-500/20 bg-[#12141a] p-4">
        <p className="text-sm text-red-400">{error}</p>
      </div>
    );
  }

  if (!hasData) {
    return (
      <div className="rounded-lg border border-white/[0.06] bg-[#12141a] p-6">
        <h3 className="mb-3 text-sm font-medium uppercase tracking-wider text-[hsl(215,12%,58%)]">
          Accuracy Scoreboard
        </h3>
        <p className="text-center text-sm text-[hsl(215,12%,58%)]">
          Collecting data...
        </p>
      </div>
    );
  }

  const improvement = metrics!.improvement_percentage!;

  return (
    <div
      className={`rounded-lg border border-white/[0.06] bg-[#12141a] p-6 ${getImprovementBgGlow(improvement)}`}
    >
      <h3 className="mb-4 text-sm font-medium uppercase tracking-wider text-[hsl(215,12%,58%)]">
        Accuracy Scoreboard
      </h3>

      {/* Improvement percentage — prominently displayed */}
      <div className="mb-5 text-center">
        <span
          className={`text-4xl font-bold tabular-nums ${getImprovementColor(improvement)}`}
        >
          {improvement > 0 ? '+' : ''}
          {improvement.toFixed(1)}%
        </span>
        <p className="mt-1 text-xs text-[hsl(215,12%,58%)]">
          {improvement > 0
            ? 'RMSE Improvement'
            : 'RMSE Degradation'}
        </p>
      </div>

      {/* Raw vs Corrected RMSE comparison */}
      <div className="grid grid-cols-2 gap-4">
        <div className="rounded-md bg-[#1a1d27] px-3 py-2">
          <p className="text-xs text-[hsl(215,12%,58%)]">Raw RMSE</p>
          <p className="text-lg font-semibold tabular-nums text-[hsl(210,20%,92%)]">
            {metrics!.raw_rmse!.toFixed(4)}
          </p>
        </div>
        <div className="rounded-md bg-[#1a1d27] px-3 py-2">
          <p className="text-xs text-[hsl(215,12%,58%)]">Corrected RMSE</p>
          <p className="text-lg font-semibold tabular-nums text-emerald-400">
            {metrics!.corrected_rmse!.toFixed(4)}
          </p>
        </div>
      </div>

      {/* Sample count for statistical confidence */}
      <p className="mt-4 text-center text-xs text-[hsl(215,12%,58%)]">
        Based on {metrics!.sample_count.toLocaleString()} samples
      </p>
    </div>
  );
}
