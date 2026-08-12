"use client";

import * as React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { AnimatedCounter } from "@/components/ui/AnimatedCounter";
import { usePrefersReducedMotion } from "@/lib/animations";
import type { FleetStatsResponse } from "@/types/fleet";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const DEFAULT_POLL_INTERVAL_MS = 30000;

interface FleetStatsBarProps {
  pollingIntervalMs?: number; // default 30000
}

/**
 * SkeletonBar — pulsing gray placeholder for loading states.
 */
function SkeletonBar({ width }: { width: string }) {
  return (
    <div
      className={cn("h-5 rounded bg-white/10 animate-pulse", width)}
      aria-label="Loading..."
      aria-busy="true"
    />
  );
}

/**
 * FleetStatsBar — displays fleet-wide statistics with animated value transitions.
 *
 * Shows:
 * - Engine status counts (nominal, degraded, critical) with color coding
 * - Average fleet health as a percentage (1 decimal place)
 * - Predicted maintenance events within the configured horizon
 *
 * Polls GET /api/fleet/stats every 30s (configurable via prop).
 * Uses AnimatedCounter for smooth numeric transitions.
 * Never shows stale data from a previous session (clears state on mount).
 *
 * Validates: Requirements 12.5
 */
export function FleetStatsBar({
  pollingIntervalMs = DEFAULT_POLL_INTERVAL_MS,
}: FleetStatsBarProps) {
  const [stats, setStats] = useState<FleetStatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const prefersReducedMotion = usePrefersReducedMotion();

  // Clear state on mount to never show stale data from previous session
  useEffect(() => {
    setStats(null);
    setLoading(true);
    setError(null);
  }, []);

  const fetchStats = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/api/fleet/stats`);
      if (!response.ok) {
        setError(`Failed to fetch fleet stats (${response.status})`);
        return;
      }

      const data: FleetStatsResponse = await response.json();
      setStats(data);
      setError(null);
    } catch {
      setError("Unable to reach fleet stats API");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Initial fetch
    fetchStats();

    // Poll at configured interval
    intervalRef.current = setInterval(fetchStats, pollingIntervalMs);

    return () => {
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [fetchStats, pollingIntervalMs]);

  // Loading skeleton state
  if (loading && stats === null) {
    return (
      <div
        className="flex items-center gap-6 px-4 py-3 rounded-lg bg-white/5 border border-white/10"
        role="status"
        aria-label="Loading fleet statistics"
        aria-busy="true"
      >
        <SkeletonBar width="w-40" />
        <SkeletonBar width="w-28" />
        <SkeletonBar width="w-48" />
      </div>
    );
  }

  // Error state
  if (error && stats === null) {
    return (
      <div
        className="flex items-center gap-2 px-4 py-3 rounded-lg bg-white/5 border border-red-500/30"
        role="alert"
      >
        <span className="text-red-400 text-sm">{error}</span>
      </div>
    );
  }

  if (!stats) return null;

  const healthPercent = stats.average_fleet_health_index !== null
    ? stats.average_fleet_health_index * 100
    : null;

  return (
    <div
      className="flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 rounded-lg bg-white/5 border border-white/10"
      role="region"
      aria-label="Fleet statistics"
    >
      {/* Engine status counts */}
      <div className="flex items-center gap-4 text-sm" role="group" aria-label="Engine status counts">
        <span className="flex items-center gap-1.5" aria-label={`${stats.nominal_count} nominal engines`}>
          <AnimatedCounter
            value={stats.nominal_count}
            className="inline-flex"
            format={(v) => Math.round(v).toString()}
          />
          <span className="text-emerald-400" style={{ color: "#10b981" }}>
            nominal
          </span>
        </span>

        <span className="flex items-center gap-1.5" aria-label={`${stats.degraded_count} degraded engines`}>
          <AnimatedCounter
            value={stats.degraded_count}
            className="inline-flex"
            format={(v) => Math.round(v).toString()}
          />
          <span className="text-amber-400" style={{ color: "#f59e0b" }}>
            degraded
          </span>
        </span>

        <span className="flex items-center gap-1.5" aria-label={`${stats.critical_count} critical engines`}>
          <AnimatedCounter
            value={stats.critical_count}
            className="inline-flex"
            format={(v) => Math.round(v).toString()}
          />
          <span className="text-red-400" style={{ color: "#ef4444" }}>
            critical
          </span>
        </span>
      </div>

      {/* Average fleet health */}
      {healthPercent !== null && (
        <div className="flex items-center gap-1.5 text-sm border-l border-white/10 pl-6">
          <span className="text-white/60">Avg Health:</span>
          <AnimatedCounter
            value={healthPercent}
            className="inline-flex"
            format={(v) => `${v.toFixed(1)}%`}
          />
        </div>
      )}

      {/* Predicted maintenance events */}
      <div className="flex items-center gap-1.5 text-sm border-l border-white/10 pl-6">
        <AnimatedCounter
          value={stats.predicted_maintenance_events}
          className="inline-flex"
          format={(v) => Math.round(v).toString()}
        />
        <span className="text-white/60">
          maintenance events predicted in next {stats.horizon_cycles} cycles
        </span>
      </div>
    </div>
  );
}
