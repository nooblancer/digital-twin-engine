"use client";

import * as React from "react";
import { useState, useEffect, useRef, useCallback } from "react";
import { PulseIndicator } from "@/components/ui/PulseIndicator";
import { GlowCard } from "@/components/ui/GlowCard";
import { AnimatedCounter } from "@/components/ui/AnimatedCounter";
import { usePrefersReducedMotion } from "@/lib/animations";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ConnectionStatus = "connected" | "disconnected" | "connecting";

interface TelemetryPoint {
  timestamp: number;
  value: number;
}

interface DemoState {
  /** Rolling window of recent sensor values for sparkline */
  sensorHistory: TelemetryPoint[];
  /** Current health index (0–1) */
  healthIndex: number;
  /** Whether a correction event occurred recently */
  correctionActive: boolean;
  /** Timestamp of last received message */
  lastMessageAt: number | null;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const WS_URL =
  process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000/ws/telemetry";

/** Maximum number of sparkline points to retain */
const MAX_SPARKLINE_POINTS = 30;

/** Max backoff delay (8 seconds as specified) */
const MAX_BACKOFF_MS = 8000;

/** Timeout before showing static placeholder if never connected */
const NEVER_CONNECTED_TIMEOUT_MS = 10_000;

/** Duration to keep correction indicator active after an event */
const CORRECTION_ACTIVE_DURATION_MS = 2000;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Computes exponential backoff: 1s, 2s, 4s, 8s max
 */
function computeBackoff(attempt: number): number {
  return Math.min(1000 * Math.pow(2, attempt), MAX_BACKOFF_MS);
}

// ---------------------------------------------------------------------------
// MiniSparkline — simple SVG sparkline for last-N sensor values
// ---------------------------------------------------------------------------

interface MiniSparklineProps {
  data: TelemetryPoint[];
  width?: number;
  height?: number;
  className?: string;
}

function MiniSparkline({
  data,
  width = 200,
  height = 60,
  className,
}: MiniSparklineProps) {
  if (data.length < 2) {
    return (
      <div
        className={className}
        style={{ width, height }}
        aria-hidden="true"
      >
        <svg width={width} height={height}>
          <line
            x1={0}
            y1={height / 2}
            x2={width}
            y2={height / 2}
            stroke="rgba(0, 212, 255, 0.3)"
            strokeWidth={1}
            strokeDasharray="4 4"
          />
        </svg>
      </div>
    );
  }

  const values = data.map((d) => d.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const padding = 4;
  const chartWidth = width - padding * 2;
  const chartHeight = height - padding * 2;

  const points = values.map((v, i) => {
    const x = padding + (i / (values.length - 1)) * chartWidth;
    const y = padding + chartHeight - ((v - min) / range) * chartHeight;
    return `${x},${y}`;
  });

  const pathD = `M ${points.join(" L ")}`;

  // Area fill path
  const firstX = padding;
  const lastX = padding + chartWidth;
  const areaD = `${pathD} L ${lastX},${height - padding} L ${firstX},${height - padding} Z`;

  return (
    <div className={className} style={{ width, height }} aria-hidden="true">
      <svg width={width} height={height}>
        <defs>
          <linearGradient id="sparkline-gradient" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stopColor="rgba(0, 212, 255, 0.2)" />
            <stop offset="100%" stopColor="rgba(0, 212, 255, 0)" />
          </linearGradient>
        </defs>
        <path d={areaD} fill="url(#sparkline-gradient)" />
        <path
          d={pathD}
          fill="none"
          stroke="#00d4ff"
          strokeWidth={1.5}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {/* Glow dot on the last point */}
        {values.length > 0 && (
          <circle
            cx={padding + chartWidth}
            cy={
              padding +
              chartHeight -
              ((values[values.length - 1] - min) / range) * chartHeight
            }
            r={3}
            fill="#00d4ff"
            opacity={0.9}
          />
        )}
      </svg>
    </div>
  );
}

// ---------------------------------------------------------------------------
// LiveDemoPreview Component
// ---------------------------------------------------------------------------

/**
 * LiveDemoPreview — A compact mini-dashboard that establishes its own
 * independent WebSocket connection to display real-time telemetry data
 * on the landing page.
 *
 * Features:
 * - Connects only when visible (Intersection Observer)
 * - Disconnects when scrolled out of view
 * - Exponential backoff retry (1s, 2s, 4s, 8s max)
 * - Static placeholder after 10s timeout if never connects
 * - Respects prefers-reduced-motion
 * - Full accessibility: ARIA landmark, aria-label, aria-live
 */
export function LiveDemoPreview() {
  const containerRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const correctionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const neverConnectedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptRef = useRef(0);
  const unmountedRef = useRef(false);
  const hasEverConnectedRef = useRef(false);

  const [isVisible, setIsVisible] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("disconnected");
  const [showStaticFallback, setShowStaticFallback] = useState(false);
  const [demoState, setDemoState] = useState<DemoState>({
    sensorHistory: [],
    healthIndex: 0.92,
    correctionActive: false,
    lastMessageAt: null,
  });

  const prefersReducedMotion = usePrefersReducedMotion();

  // -------------------------------------------------------------------------
  // Intersection Observer — track visibility
  // -------------------------------------------------------------------------
  useEffect(() => {
    const node = containerRef.current;
    if (!node) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        setIsVisible(entry.isIntersecting);
      },
      { threshold: 0.1 }
    );

    observer.observe(node);
    return () => {
      observer.disconnect();
    };
  }, []);

  // -------------------------------------------------------------------------
  // WebSocket message handler
  // -------------------------------------------------------------------------
  const handleMessage = useCallback((event: MessageEvent) => {
    let message: { type: string; payload: Record<string, unknown> };

    try {
      message = JSON.parse(event.data);
    } catch {
      return;
    }

    if (!message || typeof message.type !== "string" || !message.payload) {
      return;
    }

    const now = Date.now();

    switch (message.type) {
      case "telemetry": {
        const value = message.payload.value as number;
        const timestamp = new Date(message.payload.timestamp as string).getTime();
        setDemoState((prev) => ({
          ...prev,
          sensorHistory: [
            ...prev.sensorHistory.slice(-(MAX_SPARKLINE_POINTS - 1)),
            { timestamp, value },
          ],
          lastMessageAt: now,
        }));
        break;
      }
      case "health_index_update": {
        const healthIndex = message.payload.health_index as number;
        setDemoState((prev) => ({
          ...prev,
          healthIndex,
          lastMessageAt: now,
        }));
        break;
      }
      case "correction": {
        setDemoState((prev) => ({
          ...prev,
          correctionActive: true,
          lastMessageAt: now,
        }));

        // Clear correction active after a brief period
        if (correctionTimerRef.current) {
          clearTimeout(correctionTimerRef.current);
        }
        correctionTimerRef.current = setTimeout(() => {
          setDemoState((prev) => ({ ...prev, correctionActive: false }));
        }, CORRECTION_ACTIVE_DURATION_MS);
        break;
      }
      default:
        // Consume other message types silently
        setDemoState((prev) => ({ ...prev, lastMessageAt: now }));
        break;
    }
  }, []);

  // -------------------------------------------------------------------------
  // WebSocket connect/disconnect lifecycle
  // -------------------------------------------------------------------------
  const connect = useCallback(() => {
    if (unmountedRef.current) return;

    setConnectionStatus("connecting");

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      if (unmountedRef.current) {
        ws.close();
        return;
      }
      hasEverConnectedRef.current = true;
      attemptRef.current = 0;
      setConnectionStatus("connected");
      setShowStaticFallback(false);

      // Clear the never-connected timer
      if (neverConnectedTimerRef.current) {
        clearTimeout(neverConnectedTimerRef.current);
        neverConnectedTimerRef.current = null;
      }
    };

    ws.onmessage = handleMessage;

    ws.onclose = () => {
      if (unmountedRef.current) return;

      setConnectionStatus("disconnected");

      // Only reconnect if still visible
      if (isVisible) {
        const delay = computeBackoff(attemptRef.current);
        attemptRef.current += 1;

        reconnectTimerRef.current = setTimeout(() => {
          if (!unmountedRef.current && isVisible) {
            connect();
          }
        }, delay);
      }
    };

    ws.onerror = () => {
      // onclose will fire after onerror, which handles reconnection
    };
  }, [handleMessage, isVisible]);

  const disconnect = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }

    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    attemptRef.current = 0;
    setConnectionStatus("disconnected");
  }, []);

  // -------------------------------------------------------------------------
  // Connect when visible, disconnect when not
  // -------------------------------------------------------------------------
  useEffect(() => {
    if (isVisible) {
      connect();

      // Start the never-connected timeout
      if (!hasEverConnectedRef.current) {
        neverConnectedTimerRef.current = setTimeout(() => {
          if (!hasEverConnectedRef.current && !unmountedRef.current) {
            setShowStaticFallback(true);
          }
        }, NEVER_CONNECTED_TIMEOUT_MS);
      }
    } else {
      disconnect();
    }

    return () => {
      // Cleanup on visibility change
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isVisible]);

  // -------------------------------------------------------------------------
  // Cleanup on unmount
  // -------------------------------------------------------------------------
  useEffect(() => {
    unmountedRef.current = false;

    return () => {
      unmountedRef.current = true;
      disconnect();

      if (correctionTimerRef.current) {
        clearTimeout(correctionTimerRef.current);
      }
      if (neverConnectedTimerRef.current) {
        clearTimeout(neverConnectedTimerRef.current);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  const isReconnecting =
    connectionStatus === "disconnected" &&
    hasEverConnectedRef.current &&
    isVisible;

  const healthPercent = Math.round(demoState.healthIndex * 100);

  return (
    <section
      ref={containerRef}
      role="region"
      aria-label="Live telemetry demo preview"
      className="w-full flex justify-center"
    >
      <GlowCard
        glowColor="cyan"
        isActive={connectionStatus === "connected" && demoState.sensorHistory.length > 0}
        className="glass rounded-lg p-4 w-full max-w-[600px] max-h-[400px]"
      >
        {/* Header row */}
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium text-white/80">
            Live Engine Telemetry
          </h3>
          <div className="flex items-center gap-2">
            {!prefersReducedMotion && (
              <PulseIndicator
                status={connectionStatus === "disconnected" && isReconnecting ? "connecting" : connectionStatus}
                size="sm"
              />
            )}
            {prefersReducedMotion && (
              <PulseIndicator status={connectionStatus} size="sm" />
            )}
            <span
              className="text-xs font-medium text-white/60 uppercase tracking-wide"
              aria-live="polite"
            >
              {connectionStatus === "connected"
                ? "Live"
                : isReconnecting
                  ? "Reconnecting…"
                  : connectionStatus === "connecting"
                    ? "Connecting…"
                    : "Offline"}
            </span>
          </div>
        </div>

        {/* Static fallback */}
        {showStaticFallback && connectionStatus !== "connected" && (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <p className="text-sm text-white/60">
              Live telemetry unavailable
            </p>
            <p className="text-xs text-white/50 mt-1">
              Start the backend to see real-time data
            </p>
          </div>
        )}

        {/* Main content */}
        {!showStaticFallback && (
          <div className="grid grid-cols-1 sm:grid-cols-[1fr_auto] gap-4">
            {/* Sparkline chart */}
            <div className="flex flex-col">
              <span className="text-xs text-white/50 mb-1">
                Sensor Readings
              </span>
              <MiniSparkline
                data={demoState.sensorHistory}
                width={200}
                height={60}
                className="rounded"
              />
            </div>

            {/* Metrics panel */}
            <div className="flex flex-col gap-3 items-center justify-center">
              {/* Health index */}
              <div className="text-center">
                <AnimatedCounter
                  value={healthPercent}
                  label="Health Index"
                  format={(v) => `${Math.round(v)}%`}
                  className="text-center"
                />
              </div>

              {/* Correction activity */}
              <div className="flex items-center gap-1.5">
                <PulseIndicator
                  status={demoState.correctionActive ? "connected" : "disconnected"}
                  size="sm"
                />
                <span
                  className="text-xs text-white/60"
                  aria-live="polite"
                  aria-atomic="true"
                >
                  {demoState.correctionActive ? "Correcting" : "Idle"}
                </span>
              </div>
            </div>
          </div>
        )}

        {/* Reconnecting overlay */}
        {isReconnecting && !showStaticFallback && (
          <div
            className="mt-2 text-center"
            aria-live="assertive"
            aria-atomic="true"
          >
            <span className="text-xs text-white/60">
              Reconnecting… showing last known values
            </span>
          </div>
        )}
      </GlowCard>
    </section>
  );
}
