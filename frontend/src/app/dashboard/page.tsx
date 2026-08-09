'use client';

import { useWebSocket } from '@/hooks/useWebSocket';
import { useStore } from '@/store';
import { DataSourceSwitcher } from '@/components/DataSourceSwitcher';
import { SensorChart } from '@/components/SensorChart';
import { AnomalyAlertFeed } from '@/components/AnomalyAlertFeed';
import { SensorHealthCards } from '@/components/SensorHealthCards';
import { PipelineHealthMonitor } from '@/components/PipelineHealthMonitor';
import { HistoricalTrendExplorer } from '@/components/HistoricalTrendExplorer';
import { PredictionHorizonView } from '@/components/PredictionHorizonView';
import type { ConnectionStatus } from '@/types';

const STATUS_DOT_COLOR: Record<ConnectionStatus, string> = {
  connected: 'bg-[hsl(var(--status-healthy))]',
  disconnected: 'bg-[hsl(var(--status-critical))]',
  connecting: 'bg-[hsl(var(--status-warning))]',
  reconnecting: 'bg-[hsl(var(--status-warning))]',
};

const STATUS_LABEL: Record<ConnectionStatus, string> = {
  connected: 'Connected',
  disconnected: 'Disconnected',
  connecting: 'Connecting',
  reconnecting: 'Reconnecting',
};

function ConnectionIndicator() {
  const status = useStore((state) => state.connection.status);
  const isConnected = status === 'connected';

  return (
    <div
      className={`flex items-center gap-2 rounded px-2 py-1 text-xs font-medium transition-opacity duration-200 ${
        isConnected ? 'opacity-60' : 'opacity-100 bg-card'
      }`}
      role="status"
      aria-label={`WebSocket ${STATUS_LABEL[status]}`}
    >
      <span
        className={`h-2 w-2 rounded-full ${STATUS_DOT_COLOR[status]} ${
          !isConnected ? 'animate-pulse' : ''
        }`}
      />
      <span className="text-muted-foreground">{STATUS_LABEL[status]}</span>
    </div>
  );
}

function SkeletonPanel({ className }: { className?: string }) {
  return (
    <div
      className={`animate-pulse rounded-lg border border-border bg-card ${className ?? 'h-64'}`}
    />
  );
}

export default function DashboardPage() {
  // Establish WebSocket connection on mount
  useWebSocket();

  const sensorHealth = useStore((state) => state.sensorHealth);
  const sensorData = useStore((state) => state.sensorData);

  // Get sensor IDs that have data for charts
  const activeSensorIds = Object.keys(sensorData);
  // Use first active sensor for prediction horizon view
  const firstSensorId = activeSensorIds[0] ?? null;

  // Show skeleton state if no data has arrived yet
  const hasData = activeSensorIds.length > 0;

  return (
    <div className="space-y-4">
      {/* Top bar: Data Source Switcher + Connection Status */}
      <header className="flex items-center justify-between rounded-lg border border-border bg-card px-4 py-3">
        <DataSourceSwitcher />
        <ConnectionIndicator />
      </header>

      {/* Main content grid */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Left / Main area (2/3 width on large screens) */}
        <div className="space-y-4 lg:col-span-2">
          {/* Sensor Charts */}
          <section aria-label="Sensor Charts">
            {hasData ? (
              <div className="space-y-4">
                {activeSensorIds.slice(0, 4).map((sensorId) => (
                  <div
                    key={sensorId}
                    className="rounded-lg border border-border bg-card p-4"
                  >
                    <h3 className="mb-2 text-sm font-medium text-foreground">
                      {sensorId}
                    </h3>
                    <SensorChart sensorId={sensorId} />
                  </div>
                ))}
              </div>
            ) : (
              <div className="space-y-4">
                <SkeletonPanel className="h-72" />
                <SkeletonPanel className="h-72" />
              </div>
            )}
          </section>

          {/* Historical Trend Explorer */}
          <section aria-label="Historical Trend Explorer">
            <HistoricalTrendExplorer />
          </section>
        </div>

        {/* Right sidebar (1/3 width on large screens) */}
        <aside className="space-y-4">
          {/* Anomaly Alert Feed */}
          <section aria-label="Anomaly Alerts">
            <h2 className="mb-2 text-sm font-medium text-foreground">
              Anomaly Alerts
            </h2>
            <AnomalyAlertFeed />
          </section>

          {/* Pipeline Health Monitor */}
          <section aria-label="Pipeline Health">
            <PipelineHealthMonitor />
          </section>

          {/* Prediction Horizon View */}
          <section aria-label="Prediction Horizon">
            {firstSensorId ? (
              <PredictionHorizonView sensorId={firstSensorId} />
            ) : (
              <div className="rounded-lg border border-border bg-card p-4">
                <h3 className="text-sm font-medium text-foreground mb-3">
                  Prediction Horizon
                </h3>
                <p className="text-sm text-muted-foreground">
                  Waiting for sensor data...
                </p>
              </div>
            )}
          </section>
        </aside>
      </div>

      {/* Bottom: Sensor Health Cards (full width) */}
      <section aria-label="Sensor Health">
        <h2 className="mb-3 text-sm font-medium text-foreground">
          Sensor Health
        </h2>
        {Object.keys(sensorHealth).length > 0 ? (
          <SensorHealthCards />
        ) : (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <SkeletonPanel key={i} className="h-16" />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
