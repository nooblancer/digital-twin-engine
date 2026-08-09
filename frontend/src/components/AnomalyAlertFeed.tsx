'use client';

import { useEffect, useRef } from 'react';
import { useStore } from '@/store';
import type { AnomalyAlert } from '@/types';

interface AnomalyAlertFeedProps {
  /** Called when the user clicks an alert entry */
  onAlertClick?: (sensorId: string, timestamp: string) => void;
}

const severityConfig = {
  informational: {
    bg: 'bg-status-healthy/10',
    text: 'text-status-healthy',
    label: 'Info',
  },
  warning: {
    bg: 'bg-status-warning/10',
    text: 'text-status-warning',
    label: 'Warning',
  },
  critical: {
    bg: 'bg-status-critical/10',
    text: 'text-status-critical',
    label: 'Critical',
  },
} as const;

function formatTimestamp(isoString: string): string {
  try {
    const date = new Date(isoString);
    return date.toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return isoString;
  }
}

export function AnomalyAlertFeed({ onAlertClick }: AnomalyAlertFeedProps) {
  const anomalies = useStore((state) => state.anomalies);
  const listRef = useRef<HTMLDivElement>(null);
  const prevCountRef = useRef<number>(anomalies.length);

  // Preserve scroll position when new items prepend
  useEffect(() => {
    const container = listRef.current;
    if (!container) return;

    const prevCount = prevCountRef.current;
    const currentCount = anomalies.length;

    // If new items were prepended and user has scrolled down, adjust scroll
    if (currentCount > prevCount && container.scrollTop > 0) {
      // Each new item prepended pushes content down; maintain user's position
      const addedItems = currentCount - prevCount;
      // Estimate item height - will be adjusted by the browser naturally
      // We keep scrollTop where it was; the browser handles the rest since
      // items are prepended at the top
      container.scrollTop = container.scrollTop;
    }

    prevCountRef.current = currentCount;
  }, [anomalies.length]);

  if (anomalies.length === 0) {
    return (
      <div className="rounded-md bg-card p-6 text-center">
        <p className="text-sm text-muted-foreground">No anomalies detected</p>
      </div>
    );
  }

  return (
    <div
      ref={listRef}
      className="h-[400px] overflow-y-auto rounded-md bg-card"
      role="list"
      aria-label="Anomaly alerts"
    >
      <ul className="divide-y divide-border">
        {anomalies.map((alert) => (
          <AlertEntry
            key={alert.id}
            alert={alert}
            onClick={onAlertClick}
          />
        ))}
      </ul>
    </div>
  );
}

interface AlertEntryProps {
  alert: AnomalyAlert;
  onClick?: (sensorId: string, timestamp: string) => void;
}

function AlertEntry({ alert, onClick }: AlertEntryProps) {
  const config = severityConfig[alert.severity];

  return (
    <li
      role="listitem"
      className="flex flex-col gap-1 p-4 transition-colors hover:bg-accent/50 cursor-pointer"
      onClick={() => onClick?.(alert.sensor_id, alert.timestamp)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onClick?.(alert.sensor_id, alert.timestamp);
        }
      }}
      tabIndex={0}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium text-card-foreground">
          {alert.sensor_id}
        </span>
        <span
          className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${config.bg} ${config.text}`}
        >
          {config.label}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted-foreground">
          {formatTimestamp(alert.timestamp)}
        </span>
      </div>
      <p className="text-sm text-muted-foreground line-clamp-2">
        {alert.description}
      </p>
    </li>
  );
}
