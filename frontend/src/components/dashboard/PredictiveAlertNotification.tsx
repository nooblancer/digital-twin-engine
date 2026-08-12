"use client";

import * as React from "react";
import { useCallback, useEffect, useRef } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { useStore } from "@/store";
import type {
  PredictiveAlert,
  AlertSeverity,
  MaintenanceRecommendationsResponse,
} from "@/types/mission-control";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/** Default polling interval: 30 seconds */
const DEFAULT_POLL_INTERVAL_MS = 30_000;

/** Max visible notifications */
const MAX_VISIBLE = 5;

/** Auto-dismiss timings per severity (ms). Critical = null (no auto-dismiss). */
const AUTO_DISMISS_MS: Record<AlertSeverity, number | null> = {
  low: 10_000,
  medium: 30_000,
  critical: null,
};

/** Severity sort priority: lower number = higher priority (shown first) */
const SEVERITY_PRIORITY: Record<AlertSeverity, number> = {
  critical: 0,
  medium: 1,
  low: 2,
};

/** Color scheme per severity level */
const severityColors: Record<
  AlertSeverity,
  { bg: string; border: string; text: string; label: string }
> = {
  critical: {
    bg: "rgba(239, 68, 68, 0.1)",
    border: "#ef4444",
    text: "#fca5a5",
    label: "Critical",
  },
  medium: {
    bg: "rgba(245, 158, 11, 0.1)",
    border: "#f59e0b",
    text: "#fcd34d",
    label: "Medium",
  },
  low: {
    bg: "rgba(16, 185, 129, 0.1)",
    border: "#10b981",
    text: "#6ee7b7",
    label: "Low",
  },
};

interface PredictiveAlertNotificationProps {
  alerts: PredictiveAlert[];
  onDismiss: (alertId: string) => void;
  /** Polling interval in ms (default: 30000) */
  pollInterval?: number;
  className?: string;
}

/**
 * PredictiveAlertNotification — Toast notification system for predictive maintenance alerts.
 *
 * - Polls `GET /engines/{id}/maintenance-recommendations` every 30s per active engine
 * - Color-coded by severity: crimson=critical, amber=medium, emerald=low
 * - Auto-dismiss: low after 10s, medium after 30s, critical persists until manual dismiss
 * - Stacks notifications in severity order (critical first); max 5 visible
 * - Positioned fixed bottom-right, stacked with 8px gap
 * - Uses Framer Motion AnimatePresence for enter/exit animations
 * - Displays confidence score as percentage alongside alert
 *
 * Validates: Requirements 13.1, 13.2, 13.3, 13.4, 13.5, 13.6
 */
export function PredictiveAlertNotification({
  alerts,
  onDismiss,
  pollInterval = DEFAULT_POLL_INTERVAL_MS,
  className,
}: PredictiveAlertNotificationProps) {
  const engines = useStore((s) => s.engines);
  const addPredictiveAlert = useStore((s) => s.addPredictiveAlert);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const autoDismissTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(
    new Map()
  );
  // Track which recommendation keys we've already alerted on to avoid duplicates
  const seenAlertKeys = useRef<Set<string>>(new Set());

  // Poll maintenance-recommendations for each active engine
  const pollRecommendations = useCallback(async () => {
    const engineIds = Object.keys(engines).map(Number);
    if (engineIds.length === 0) return;

    for (const engineId of engineIds) {
      try {
        const response = await fetch(
          `${API_BASE}/api/engines/${engineId}/maintenance-recommendations`
        );
        if (!response.ok) continue;

        const data: MaintenanceRecommendationsResponse = await response.json();

        for (const rec of data.recommendations) {
          // Create a stable key to avoid duplicate alerts for same recommendation
          const alertKey = `${engineId}-${rec.severity}-${rec.time_to_critical_cycles}`;
          if (seenAlertKeys.current.has(alertKey)) continue;
          seenAlertKeys.current.add(alertKey);

          const alert: PredictiveAlert = {
            id: `${alertKey}-${Date.now()}`,
            engineId,
            severity: rec.severity,
            timeToCriticalCycles: rec.time_to_critical_cycles,
            confidenceScore: rec.confidence_score,
            suggestedAction: rec.suggested_action,
            timestamp: Date.now(),
          };

          addPredictiveAlert(alert);
        }
      } catch {
        // Silently ignore fetch errors — alerts just won't update
      }
    }
  }, [engines, addPredictiveAlert]);

  // Set up polling interval
  useEffect(() => {
    // Initial poll
    pollRecommendations();

    pollRef.current = setInterval(pollRecommendations, pollInterval);

    return () => {
      if (pollRef.current !== null) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [pollRecommendations, pollInterval]);

  // Auto-dismiss logic: set timers for non-critical alerts
  useEffect(() => {
    for (const alert of alerts) {
      const dismissMs = AUTO_DISMISS_MS[alert.severity];
      if (dismissMs === null) continue; // critical = no auto-dismiss
      if (autoDismissTimers.current.has(alert.id)) continue; // already scheduled

      const timer = setTimeout(() => {
        onDismiss(alert.id);
        autoDismissTimers.current.delete(alert.id);
      }, dismissMs);

      autoDismissTimers.current.set(alert.id, timer);
    }

    // Cleanup timers for alerts that were already dismissed externally
    return () => {
      // Only cleanup timers for alerts no longer in the list
      const alertIds = new Set(alerts.map((a) => a.id));
      autoDismissTimers.current.forEach((timer, id) => {
        if (!alertIds.has(id)) {
          clearTimeout(timer);
          autoDismissTimers.current.delete(id);
        }
      });
    };
  }, [alerts, onDismiss]);

  // Cleanup all timers on unmount
  useEffect(() => {
    return () => {
      autoDismissTimers.current.forEach((timer) => {
        clearTimeout(timer);
      });
      autoDismissTimers.current.clear();
    };
  }, []);

  // Sort by severity (critical first), then by timestamp (newest first)
  const sortedAlerts = [...alerts].sort((a, b) => {
    const priorityDiff = SEVERITY_PRIORITY[a.severity] - SEVERITY_PRIORITY[b.severity];
    if (priorityDiff !== 0) return priorityDiff;
    return b.timestamp - a.timestamp;
  });

  // Limit to max visible
  const visibleAlerts = sortedAlerts.slice(0, MAX_VISIBLE);

  return (
    <div
      className={cn(
        "fixed bottom-4 right-4 z-50 flex flex-col-reverse gap-2 pointer-events-none",
        className
      )}
      role="region"
      aria-label="Predictive maintenance alerts"
      aria-live="polite"
    >
      <AnimatePresence mode="popLayout">
        {visibleAlerts.map((alert) => (
          <AlertCard key={alert.id} alert={alert} onDismiss={onDismiss} />
        ))}
      </AnimatePresence>
    </div>
  );
}

// --- Alert Card ---

interface AlertCardProps {
  alert: PredictiveAlert;
  onDismiss: (alertId: string) => void;
}

function AlertCard({ alert, onDismiss }: AlertCardProps) {
  const colors = severityColors[alert.severity];
  const confidencePct = Math.round(alert.confidenceScore * 100);

  return (
    <motion.div
      layout
      initial={{ opacity: 0, x: 50, scale: 0.95 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      exit={{ opacity: 0, x: 50, scale: 0.95 }}
      transition={{ type: "spring", stiffness: 300, damping: 25 }}
      className="pointer-events-auto w-[360px] rounded-lg p-3 backdrop-blur-md"
      style={{
        backgroundColor: colors.bg,
        border: `1px solid ${colors.border}`,
      }}
      role="alert"
      aria-label={`${colors.label} alert for engine ${alert.engineId}`}
    >
      {/* Header row */}
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <SeverityIcon severity={alert.severity} />
          <span
            className="text-sm font-medium"
            style={{ color: colors.text }}
          >
            Engine {alert.engineId} · {colors.label}
          </span>
        </div>
        <button
          onClick={() => onDismiss(alert.id)}
          className="text-white/40 hover:text-white/80 transition-colors text-lg leading-none p-0.5"
          aria-label={`Dismiss alert for engine ${alert.engineId}`}
        >
          ×
        </button>
      </div>

      {/* Message */}
      <p className="text-xs text-white/70 mb-1">
        Will reach critical in{" "}
        <span className="font-semibold text-white/90">
          {alert.timeToCriticalCycles} cycles
        </span>
      </p>

      {/* Footer: confidence + action */}
      <div className="flex items-center gap-2 text-[11px] text-white/50">
        <span
          className="font-medium"
          style={{ color: colors.text }}
        >
          Confidence: {confidencePct}%
        </span>
        <span className="text-white/30">·</span>
        <span className="truncate">{alert.suggestedAction}</span>
      </div>
    </motion.div>
  );
}

// --- Severity Icon ---

function SeverityIcon({ severity }: { severity: AlertSeverity }) {
  const colors = severityColors[severity];

  if (severity === "critical") {
    return (
      <svg
        width="14"
        height="14"
        viewBox="0 0 14 14"
        fill="none"
        aria-hidden="true"
      >
        <circle cx="7" cy="7" r="6" stroke={colors.border} strokeWidth="1.5" />
        <path
          d="M7 4v3.5M7 9.5v.5"
          stroke={colors.border}
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      </svg>
    );
  }

  if (severity === "medium") {
    return (
      <svg
        width="14"
        height="14"
        viewBox="0 0 14 14"
        fill="none"
        aria-hidden="true"
      >
        <path
          d="M7 1.5L12.5 11.5H1.5L7 1.5Z"
          stroke={colors.border}
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
        <path
          d="M7 5.5v2.5M7 9.5v.5"
          stroke={colors.border}
          strokeWidth="1.2"
          strokeLinecap="round"
        />
      </svg>
    );
  }

  // low severity
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 14 14"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="7" cy="7" r="6" stroke={colors.border} strokeWidth="1.5" />
      <path
        d="M5 7h4M7 5v4"
        stroke={colors.border}
        strokeWidth="1.2"
        strokeLinecap="round"
      />
    </svg>
  );
}
