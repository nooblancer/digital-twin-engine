'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { useStore } from '@/store';
import type { ComponentStatusValue, PipelineHealthResponse } from '@/types';

interface PipelineHealthMonitorProps {
  /** Polling interval in milliseconds (default: 30000) */
  pollInterval?: number;
  /** Health endpoint URL (default: http://localhost:8000/health) */
  endpoint?: string;
}

const PIPELINE_COMPONENTS = [
  { key: 'ingestion_server', label: 'Ingestion Server' },
  { key: 'message_broker', label: 'Message Broker' },
  { key: 'tsdb_writer', label: 'TSDB Writer' },
  { key: 'ml_service', label: 'ML Service' },
  { key: 'correction_engine', label: 'Correction Engine' },
] as const;

const STATUS_COLORS: Record<ComponentStatusValue, string> = {
  healthy: 'hsl(var(--status-healthy))',
  degraded: 'hsl(var(--status-warning))',
  down: 'hsl(var(--status-critical))',
  unknown: 'hsl(var(--status-unknown))',
};

const STATUS_LABELS: Record<ComponentStatusValue, string> = {
  healthy: 'Healthy',
  degraded: 'Degraded',
  down: 'Down',
  unknown: 'Unknown',
};

export function PipelineHealthMonitor({
  pollInterval = 30000,
  endpoint = 'http://localhost:8000/health',
}: PipelineHealthMonitorProps) {
  const pipelineHealth = useStore((state) => state.pipelineHealth);
  const setPipelineHealth = useStore((state) => state.setPipelineHealth);

  const [isLoading, setIsLoading] = useState(true);
  const [connectivityError, setConnectivityError] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchHealth = useCallback(async () => {
    try {
      const response = await fetch(endpoint);

      if (!response.ok) {
        throw new Error(`Health check failed: ${response.status}`);
      }

      const data: PipelineHealthResponse = await response.json();
      setPipelineHealth(data);
      setConnectivityError(false);
    } catch {
      // On error/unreachable: set all components to unknown
      const unknownResponse: PipelineHealthResponse = {
        overall_status: 'unknown',
        components: Object.fromEntries(
          PIPELINE_COMPONENTS.map(({ key }) => [key, 'unknown' as ComponentStatusValue])
        ),
        timestamp: new Date().toISOString(),
      };
      setPipelineHealth(unknownResponse);
      setConnectivityError(true);
    } finally {
      setIsLoading(false);
    }
  }, [endpoint, setPipelineHealth]);

  useEffect(() => {
    // Fetch immediately on mount
    fetchHealth();

    // Set up polling interval
    intervalRef.current = setInterval(fetchHealth, pollInterval);

    return () => {
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [fetchHealth, pollInterval]);

  // Loading state
  if (isLoading) {
    return (
      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="text-sm font-medium text-foreground mb-3">Pipeline Health</h3>
        <div className="space-y-2">
          {PIPELINE_COMPONENTS.map(({ key }) => (
            <div key={key} className="flex items-center gap-2">
              <div
                className="w-2.5 h-2.5 rounded-full animate-pulse"
                style={{ backgroundColor: 'hsl(var(--status-unknown))' }}
              />
              <span className="text-sm text-muted-foreground">Checking...</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  const overallStatus = pipelineHealth?.overall_status ?? 'unknown';

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      {/* Connectivity warning banner */}
      {connectivityError && (
        <div
          className="mb-3 rounded px-3 py-2 text-xs font-medium"
          style={{
            backgroundColor: 'hsl(var(--status-warning) / 0.15)',
            color: 'hsl(var(--status-warning))',
            border: '1px solid hsl(var(--status-warning) / 0.3)',
          }}
          role="alert"
        >
          ⚠ Unable to reach health endpoint. Statuses may be stale.
        </div>
      )}

      {/* Header with overall status */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-foreground">Pipeline Health</h3>
        <span
          className="text-xs font-semibold px-2 py-0.5 rounded"
          style={{
            backgroundColor: `${STATUS_COLORS[overallStatus]}20`,
            color: STATUS_COLORS[overallStatus],
          }}
        >
          {STATUS_LABELS[overallStatus]}
        </span>
      </div>

      {/* Component list */}
      <div className="space-y-2">
        {PIPELINE_COMPONENTS.map(({ key, label }) => {
          const status: ComponentStatusValue =
            pipelineHealth?.components[key] ?? 'unknown';

          return (
            <div key={key} className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div
                  className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                  style={{ backgroundColor: STATUS_COLORS[status] }}
                  aria-label={`${label} status: ${STATUS_LABELS[status]}`}
                />
                <span className="text-sm text-foreground">{label}</span>
              </div>
              <span
                className="text-xs text-muted-foreground"
                style={{ color: STATUS_COLORS[status] }}
              >
                {STATUS_LABELS[status]}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
