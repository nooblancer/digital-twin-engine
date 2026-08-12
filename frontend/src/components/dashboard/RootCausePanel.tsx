"use client";

import * as React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { useStore } from "@/store";
import { PulseIndicator } from "@/components/ui/PulseIndicator";
import type { AnomalyAnalysisResponse, SensorContribution } from "@/types/mission-control";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// --- Types ---

interface RootCausePanelProps {
  engineId: number;
  className?: string;
}

interface RootCausePanelState {
  isLoading: boolean;
  error: string | null;
  anomalyActive: boolean;
  contributions: SensorContribution[];
  timestamp: string | null;
}

// --- Helpers ---

/**
 * Returns bar color based on sigma deviation thresholds.
 * Crimson for σ > 3, amber for σ > 2, cyan otherwise.
 */
function getBarColor(sigma: number): string {
  if (sigma > 3) return "#ef4444"; // crimson
  if (sigma > 2) return "#f59e0b"; // amber
  return "#00d4ff"; // cyan
}

// --- Skeleton Shimmer ---

function SkeletonBar({ widthPct }: { widthPct: number }) {
  return (
    <div className="flex items-center gap-3 py-2">
      <div className="w-32 h-4 rounded bg-white/5 animate-pulse" />
      <div className="flex-1 h-5 rounded-sm bg-white/5 overflow-hidden">
        <div
          className="h-full rounded-sm bg-white/10 animate-pulse"
          style={{ width: `${widthPct}%` }}
        />
      </div>
      <div className="w-10 h-4 rounded bg-white/5 animate-pulse" />
    </div>
  );
}

// --- Main Component ---

/**
 * RootCausePanel — displays anomaly root cause analysis results with ranked
 * sensor contributions rendered as horizontal bar charts.
 *
 * Fetches from GET /engines/{engineId}/anomaly-analysis on anomaly events.
 * Listens to Zustand store anomalies array to trigger refetch.
 *
 * Validates: Requirements 12.1, 12.2, 12.3, 12.4, 12.5
 */
export function RootCausePanel({ engineId, className }: RootCausePanelProps) {
  const [state, setState] = useState<RootCausePanelState>({
    isLoading: true,
    error: null,
    anomalyActive: false,
    contributions: [],
    timestamp: null,
  });

  // Track anomaly count to detect new anomaly events
  const anomalies = useStore((s) => s.anomalies);
  const anomalyCountRef = useRef(anomalies.length);

  // Also read from the mission control slice if analysis already cached
  const cachedAnalysis = useStore((s) => s.anomalyAnalysis[engineId]);
  const setAnomalyAnalysis = useStore((s) => s.setAnomalyAnalysis);

  const fetchAnalysis = useCallback(async () => {
    setState((prev) => ({ ...prev, isLoading: true, error: null }));

    try {
      const response = await fetch(
        `${API_BASE}/api/engines/${engineId}/anomaly-analysis`
      );

      if (!response.ok) {
        const errorText = response.status === 404
          ? `Engine ${engineId} not found`
          : `Failed to fetch analysis (HTTP ${response.status})`;
        setState((prev) => ({
          ...prev,
          isLoading: false,
          error: errorText,
        }));
        return;
      }

      const data: AnomalyAnalysisResponse = await response.json();

      // Update Zustand cache
      setAnomalyAnalysis(engineId, data);

      setState({
        isLoading: false,
        error: null,
        anomalyActive: data.anomaly_active,
        contributions: data.contributions,
        timestamp: data.timestamp,
      });
    } catch (err) {
      setState((prev) => ({
        ...prev,
        isLoading: false,
        error: "Network error. Could not reach the server.",
      }));
    }
  }, [engineId, setAnomalyAnalysis]);

  // Initial fetch
  useEffect(() => {
    fetchAnalysis();
  }, [fetchAnalysis]);

  // Listen for new anomaly events in Zustand store to trigger refetch
  useEffect(() => {
    if (anomalies.length > anomalyCountRef.current) {
      // New anomaly arrived — refetch analysis
      fetchAnalysis();
    }
    anomalyCountRef.current = anomalies.length;
  }, [anomalies.length, fetchAnalysis]);

  // If we have cached data and haven't fetched yet, use it
  useEffect(() => {
    if (cachedAnalysis && state.isLoading) {
      setState({
        isLoading: false,
        error: null,
        anomalyActive: cachedAnalysis.anomaly_active,
        contributions: cachedAnalysis.contributions,
        timestamp: cachedAnalysis.timestamp,
      });
    }
  }, [cachedAnalysis, state.isLoading]);

  // --- Render ---

  return (
    <div
      className={cn(
        "rounded-md bg-mission-surface-1 border border-white/[0.06] p-4",
        className
      )}
      role="region"
      aria-label="Root cause analysis panel"
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-white/80">Root Cause Analysis</h3>
        {state.timestamp && state.anomalyActive && (
          <span className="text-[10px] text-white/40">
            {formatTimestamp(state.timestamp)}
          </span>
        )}
      </div>

      {/* Loading State */}
      {state.isLoading && <LoadingSkeleton />}

      {/* Error State */}
      {!state.isLoading && state.error && (
        <ErrorBanner message={state.error} onRetry={fetchAnalysis} />
      )}

      {/* No Active Anomalies */}
      {!state.isLoading && !state.error && !state.anomalyActive && (
        <NoAnomalyState />
      )}

      {/* Active Anomaly: Ranked Contributions */}
      {!state.isLoading && !state.error && state.anomalyActive && (
        <ContributionList contributions={state.contributions} />
      )}
    </div>
  );
}

// --- Sub-components ---

function LoadingSkeleton() {
  return (
    <div className="space-y-1" aria-busy="true" aria-label="Loading analysis">
      <SkeletonBar widthPct={85} />
      <SkeletonBar widthPct={60} />
      <SkeletonBar widthPct={45} />
      <SkeletonBar widthPct={30} />
    </div>
  );
}

function ErrorBanner({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div
      className="rounded bg-red-500/10 border border-red-500/30 p-3 flex items-center justify-between"
      role="alert"
    >
      <span className="text-xs text-red-400">{message}</span>
      <button
        onClick={onRetry}
        className="text-xs text-red-300 hover:text-red-200 underline underline-offset-2 ml-3 shrink-0"
        aria-label="Retry fetching analysis"
      >
        Retry
      </button>
    </div>
  );
}

function NoAnomalyState() {
  return (
    <div className="flex items-center gap-2 py-4 justify-center">
      <PulseIndicator status="connected" size="sm" />
      <span className="text-sm text-white/50">No active anomalies</span>
    </div>
  );
}

function ContributionList({ contributions }: { contributions: SensorContribution[] }) {
  if (contributions.length === 0) {
    return (
      <p className="text-xs text-white/40 text-center py-3">
        Anomaly detected but no sensor contributions available.
      </p>
    );
  }

  const maxSigma = Math.max(...contributions.map((c) => c.sigma_deviation), 1);

  return (
    <ul className="space-y-2" role="list" aria-label="Sensor contributions ranked by deviation">
      {contributions.map((contribution) => (
        <ContributionRow
          key={contribution.sensor_name}
          contribution={contribution}
          maxSigma={maxSigma}
        />
      ))}
    </ul>
  );
}

function ContributionRow({
  contribution,
  maxSigma,
}: {
  contribution: SensorContribution;
  maxSigma: number;
}) {
  const widthPct = (contribution.sigma_deviation / maxSigma) * 100;
  const barColor = getBarColor(contribution.sigma_deviation);

  return (
    <li className="flex items-center gap-3" role="listitem">
      {/* Sensor name */}
      <span
        className="w-32 text-xs text-white/60 truncate shrink-0"
        title={contribution.sensor_name}
      >
        {contribution.sensor_name}
      </span>

      {/* Horizontal bar */}
      <div className="flex-1 h-5 rounded-sm bg-white/5 overflow-hidden relative">
        <div
          className="h-full rounded-sm transition-all duration-300 ease-out"
          style={{
            width: `${Math.max(widthPct, 2)}%`,
            backgroundColor: barColor,
            opacity: 0.85,
          }}
          role="meter"
          aria-valuenow={contribution.sigma_deviation}
          aria-valuemin={0}
          aria-valuemax={maxSigma}
          aria-label={`${contribution.sensor_name}: ${contribution.sigma_deviation.toFixed(1)} sigma deviation`}
        />
      </div>

      {/* Sigma value */}
      <span
        className="w-12 text-xs text-right shrink-0"
        style={{ color: barColor }}
      >
        {contribution.sigma_deviation.toFixed(1)}σ
      </span>
    </li>
  );
}

// --- Utilities ---

function formatTimestamp(isoString: string): string {
  try {
    const date = new Date(isoString);
    return date.toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return isoString;
  }
}
