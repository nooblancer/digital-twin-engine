'use client';

import { useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { useWebSocket } from '@/hooks/useWebSocket';
import { useStore } from '@/store';
import type { EngineState } from '@/types/digital-twin';

// --- Classification helpers ---

type HealthClassification = 'nominal' | 'degraded' | 'critical';

function getHealthClassification(healthIndex: number): HealthClassification {
  if (healthIndex >= 0.7) return 'nominal';
  if (healthIndex >= 0.4) return 'degraded';
  return 'critical';
}

const CLASSIFICATION_STYLES: Record<
  HealthClassification,
  { border: string; badge: string; badgeText: string; gauge: string }
> = {
  nominal: {
    border: 'border-[hsl(var(--status-healthy))]',
    badge: 'bg-[hsl(var(--status-healthy))]/15 text-[hsl(var(--status-healthy))]',
    badgeText: 'Nominal',
    gauge: 'bg-[hsl(var(--status-healthy))]',
  },
  degraded: {
    border: 'border-[hsl(var(--status-warning))]',
    badge: 'bg-[hsl(var(--status-warning))]/15 text-[hsl(var(--status-warning))]',
    badgeText: 'Degraded',
    gauge: 'bg-[hsl(var(--status-warning))]',
  },
  critical: {
    border: 'border-[hsl(var(--status-critical))]',
    badge: 'bg-[hsl(var(--status-critical))]/15 text-[hsl(var(--status-critical))]',
    badgeText: 'Critical',
    gauge: 'bg-[hsl(var(--status-critical))]',
  },
};

// --- Components ---

function HealthGauge({
  healthIndex,
  classification,
}: {
  healthIndex: number;
  classification: HealthClassification;
}) {
  const percentage = Math.round(healthIndex * 100);
  const styles = CLASSIFICATION_STYLES[classification];

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">Health Index</span>
        <span className="text-xs font-medium text-foreground">{percentage}%</span>
      </div>
      <div className="h-2 w-full rounded-full bg-muted/50 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-300 ${styles.gauge}`}
          style={{ width: `${percentage}%` }}
          role="progressbar"
          aria-valuenow={percentage}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`Health Index: ${percentage}%`}
        />
      </div>
    </div>
  );
}

function RULCountdown({ rul, isUrgent }: { rul: number; isUrgent: boolean }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span
        className={`text-2xl font-bold tabular-nums ${
          isUrgent ? 'text-[hsl(var(--status-critical))]' : 'text-foreground'
        }`}
      >
        {rul}
      </span>
      <span className="text-xs text-muted-foreground">cycles remaining</span>
    </div>
  );
}

function ClassificationBadge({ classification }: { classification: HealthClassification }) {
  const styles = CLASSIFICATION_STYLES[classification];

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wider ${styles.badge}`}
    >
      {styles.badgeText}
    </span>
  );
}

function EngineCard({ engine }: { engine: EngineState }) {
  const router = useRouter();
  const classification = getHealthClassification(engine.healthIndex);
  const styles = CLASSIFICATION_STYLES[classification];

  return (
    <button
      type="button"
      onClick={() => router.push(`/engine/${engine.engineId}`)}
      className={`w-full text-left rounded-lg border-l-4 ${styles.border} border border-border bg-card p-4 hover:bg-accent/50 transition-colors cursor-pointer focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:ring-offset-background`}
      aria-label={`Engine ${engine.engineId} — ${classification}, ${engine.rul} cycles remaining`}
    >
      {/* Header: Unit ID + Badge */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-foreground">
          Engine {String(engine.engineId).padStart(3, '0')}
        </h3>
        <ClassificationBadge classification={classification} />
      </div>

      {/* RUL Countdown */}
      <div className="mb-3">
        <RULCountdown rul={engine.rul} isUrgent={engine.isUrgent} />
      </div>

      {/* Health Index Gauge */}
      <HealthGauge healthIndex={engine.healthIndex} classification={classification} />

      {/* Provisional indicator */}
      {engine.isProvisional && (
        <p className="mt-2 text-[10px] text-muted-foreground italic">
          Provisional (baseline establishing)
        </p>
      )}
    </button>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <div className="h-12 w-12 rounded-full bg-muted/50 flex items-center justify-center mb-4">
        <svg
          className="h-6 w-6 text-muted-foreground"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={1.5}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z"
          />
        </svg>
      </div>
      <h3 className="text-sm font-medium text-foreground mb-1">No engines detected</h3>
      <p className="text-xs text-muted-foreground max-w-xs">
        Waiting for engine telemetry data. Engines will appear here once the pipeline begins
        streaming sensor data.
      </p>
    </div>
  );
}

// --- Page ---

export default function FleetOverviewPage() {
  // Subscribe to real-time WebSocket updates
  useWebSocket();

  const engines = useStore((state) => state.engines);

  // Sort engines by RUL ascending (most urgent first)
  const sortedEngines = useMemo(() => {
    return Object.values(engines).sort((a, b) => a.rul - b.rul);
  }, [engines]);

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
        {/* Page header */}
        <header className="mb-6">
          <h1 className="text-2xl font-semibold text-foreground">Fleet Overview</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {sortedEngines.length > 0
              ? `Monitoring ${sortedEngines.length} engine${sortedEngines.length !== 1 ? 's' : ''} — sorted by urgency`
              : 'Real-time fleet health monitoring'}
          </p>
        </header>

        {/* Engine card grid */}
        {sortedEngines.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {sortedEngines.map((engine) => (
              <EngineCard key={engine.engineId} engine={engine} />
            ))}
          </div>
        ) : (
          <EmptyState />
        )}
      </div>
    </div>
  );
}
