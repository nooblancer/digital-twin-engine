"use client";

import * as React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { LineChart, Line, ResponsiveContainer } from "recharts";
import { cn } from "@/lib/utils";
import { useStore } from "@/store";
import { PulseIndicator } from "@/components/ui/PulseIndicator";
import { AnimatedCounter } from "@/components/ui/AnimatedCounter";
import type { PerformanceMetrics } from "@/types/mission-control";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const POLL_INTERVAL_MS = 5000;
const MAX_SPARKLINE_POINTS = 20;

type SparklineColor = "cyan" | "violet" | "emerald";

interface SparklineData {
  label: string;
  values: number[];
  color: SparklineColor;
}

const colorMap: Record<SparklineColor, string> = {
  cyan: "#00d4ff",
  violet: "#7c3aed",
  emerald: "#10b981",
};

interface GlassStatusBarProps {
  className?: string;
}

/**
 * MiniSparkline — renders a tiny line chart for status bar metrics.
 */
function MiniSparkline({ label, values, color }: SparklineData) {
  const data = values.map((v, i) => ({ idx: i, value: v }));

  return (
    <div className="flex flex-col items-center gap-0.5">
      <div className="w-[80px] h-[24px]">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
            <Line
              type="monotone"
              dataKey="value"
              stroke={colorMap[color]}
              strokeWidth={1.5}
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <span className="text-[10px] text-white/50 leading-none">{label}</span>
    </div>
  );
}

/**
 * GlassStatusBar — Glassmorphism header bar showing real-time system status.
 *
 * Displays:
 * - PulseIndicator for WebSocket connection state
 * - AnimatedCounter for total event count
 * - Mini sparklines for latency (p50), throughput (events/s), and corrections/s
 *
 * Polls GET /metrics/performance every 5 seconds to feed sparkline history.
 *
 * Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5
 */
export function GlassStatusBar({ className }: GlassStatusBarProps) {
  const connectionStatus = useStore((s) => s.connection.status);
  const totalEventCount = useStore((s) => s.totalEventCount);
  const setPerformanceMetrics = useStore((s) => s.setPerformanceMetrics);

  // Sparkline data history (rolling window of last 20 values)
  const [latencyHistory, setLatencyHistory] = useState<number[]>([]);
  const [throughputHistory, setThroughputHistory] = useState<number[]>([]);
  const [correctionsHistory, setCorrectionsHistory] = useState<number[]>([]);

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchPerformanceMetrics = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/api/metrics/performance`);
      if (!response.ok) return;

      const metrics: PerformanceMetrics = await response.json();

      // Push to Zustand for other components
      setPerformanceMetrics(metrics);

      // Append to sparkline history (rolling window)
      setLatencyHistory((prev) => {
        const next = [...prev, metrics.latency.p50_ms];
        return next.length > MAX_SPARKLINE_POINTS
          ? next.slice(next.length - MAX_SPARKLINE_POINTS)
          : next;
      });

      setThroughputHistory((prev) => {
        const next = [...prev, metrics.throughput.events_per_second];
        return next.length > MAX_SPARKLINE_POINTS
          ? next.slice(next.length - MAX_SPARKLINE_POINTS)
          : next;
      });

      setCorrectionsHistory((prev) => {
        const next = [...prev, metrics.throughput.corrections_per_second];
        return next.length > MAX_SPARKLINE_POINTS
          ? next.slice(next.length - MAX_SPARKLINE_POINTS)
          : next;
      });
    } catch {
      // Silently ignore fetch failures — sparklines just stop updating
    }
  }, [setPerformanceMetrics]);

  useEffect(() => {
    // Initial fetch
    fetchPerformanceMetrics();

    // Poll every 5 seconds
    intervalRef.current = setInterval(fetchPerformanceMetrics, POLL_INTERVAL_MS);

    return () => {
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [fetchPerformanceMetrics]);

  // Derive PulseIndicator status from connection state
  const pulseStatus =
    connectionStatus === "connected"
      ? "connected"
      : connectionStatus === "connecting" || connectionStatus === "reconnecting"
        ? "connecting"
        : "disconnected";

  const sparklines: SparklineData[] = [
    { label: "Latency (p50)", values: latencyHistory, color: "cyan" },
    { label: "Events/s", values: throughputHistory, color: "emerald" },
    { label: "Corrections/s", values: correctionsHistory, color: "violet" },
  ];

  return (
    <header
      className={cn(
        "glass sticky top-0 z-50 h-14 px-6 flex items-center gap-6",
        className
      )}
      role="banner"
      aria-label="System status bar"
    >
      {/* Connection status */}
      <div className="flex items-center gap-2">
        <PulseIndicator status={pulseStatus} size="md" />
        <span className="text-xs text-white/60 hidden sm:inline">
          {pulseStatus === "connected"
            ? "Live"
            : pulseStatus === "connecting"
              ? "Connecting…"
              : "Offline"}
        </span>
      </div>

      {/* Event counter */}
      <AnimatedCounter value={totalEventCount} label="Events" />

      {/* Sparklines */}
      <div className="flex items-center gap-4 ml-auto">
        {sparklines.map((s) => (
          <MiniSparkline key={s.label} {...s} />
        ))}
      </div>
    </header>
  );
}
