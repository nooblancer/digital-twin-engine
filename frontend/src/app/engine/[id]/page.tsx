'use client';

import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { useStore } from '@/store';
import { useWebSocket } from '@/hooks/useWebSocket';
import { EngineSchematic } from '@/components/EngineSchematic';
import { PredictionComparison } from '@/components/visualizations/PredictionComparison';
import { ConfidenceBandChart } from '@/components/visualizations/ConfidenceBandChart';
import { KalmanGainIndicator } from '@/components/visualizations/KalmanGainIndicator';
import { InnovationMeter } from '@/components/visualizations/InnovationMeter';

export default function EngineDashboardPage() {
  // Subscribe to real-time WebSocket updates
  useWebSocket();

  const params = useParams();
  const router = useRouter();
  const engineId = Number(params.id);

  const engines = useStore((state) => state.engines);
  const selectEngine = useStore((state) => state.selectEngine);

  const engine = engines[engineId];
  const engineIds = Object.keys(engines)
    .map(Number)
    .sort((a, b) => a - b);

  const rul = engine?.rul ?? 125;
  const isCriticalRUL = rul < 30;
  const trajectory = engine?.trajectory ?? [];
  const degradationRate = engine?.degradationRate ?? null;
  const subsystems = engine?.subsystems ?? [];

  function handleEngineChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const newId = Number(e.target.value);
    selectEngine(newId);
    router.push(`/engine/${newId}`);
  }

  return (
    <main className="min-h-screen bg-background text-foreground p-6">
      <div className="max-w-6xl mx-auto space-y-8">
        {/* Header with navigation and engine selector */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link
              href="/fleet"
              className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
              aria-label="Back to Fleet Overview"
            >
              <svg
                className="h-4 w-4"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
              </svg>
              Fleet
            </Link>
            <h1 className="text-2xl font-semibold">Engine Dashboard</h1>
          </div>
          <div className="flex items-center gap-3">
            <label
              htmlFor="engine-selector"
              className="text-sm text-muted-foreground"
            >
              Engine Unit:
            </label>
            <select
              id="engine-selector"
              value={engineId}
              onChange={handleEngineChange}
              className="rounded-md border border-border bg-card px-3 py-1.5 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            >
              {engineIds.length === 0 ? (
                <option value={engineId}>Engine {engineId}</option>
              ) : (
                engineIds.map((id) => (
                  <option key={id} value={id}>
                    Engine {id}
                  </option>
                ))
              )}
            </select>
          </div>
        </div>

        {/* RUL Indicator */}
        <section
          aria-label="Remaining Useful Life"
          className={`rounded-lg border p-8 text-center ${
            isCriticalRUL
              ? 'border-destructive bg-destructive/10'
              : 'border-border bg-card'
          }`}
        >
          <p className="text-sm uppercase tracking-wider text-muted-foreground mb-2">
            Remaining Useful Life
          </p>
          <p
            data-testid="rul-value"
            className={`font-bold tabular-nums ${
              isCriticalRUL
                ? 'text-7xl text-destructive'
                : 'text-5xl text-foreground'
            }`}
          >
            {rul}
          </p>
          <p
            className={`mt-1 ${
              isCriticalRUL
                ? 'text-lg text-destructive font-medium'
                : 'text-sm text-muted-foreground'
            }`}
          >
            cycles remaining
          </p>
          {isCriticalRUL && (
            <p className="mt-3 text-sm text-destructive font-medium">
              ⚠ Critical — Immediate maintenance attention required
            </p>
          )}
        </section>

        {/* Health Trajectory Chart */}
        <section className="rounded-lg border border-border bg-card p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-medium">Health Index Trajectory</h2>
            {degradationRate !== null && (
              <div className="text-sm text-muted-foreground">
                Degradation rate:{' '}
                <span
                  data-testid="degradation-rate"
                  className={`font-mono font-medium ${
                    degradationRate > 0.02
                      ? 'text-destructive'
                      : 'text-foreground'
                  }`}
                >
                  {degradationRate.toFixed(4)}
                </span>
                <span className="ml-1">HI/cycle</span>
              </div>
            )}
            {degradationRate === null && (
              <p className="text-sm text-muted-foreground italic">
                Degradation rate unavailable (&lt;20 cycles)
              </p>
            )}
          </div>

          {trajectory.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <LineChart
                data={trajectory}
                margin={{ top: 8, right: 16, left: 8, bottom: 8 }}
              >
                <CartesianGrid
                  stroke="hsl(220, 10%, 20%)"
                  strokeDasharray="3 3"
                />
                <XAxis
                  dataKey="cycle"
                  label={{
                    value: 'Cycle',
                    position: 'insideBottom',
                    offset: -4,
                    style: { fill: 'hsl(215, 12%, 58%)', fontSize: 12 },
                  }}
                  stroke="hsl(215, 12%, 58%)"
                  tick={{ fontSize: 11 }}
                />
                <YAxis
                  domain={[0, 1]}
                  label={{
                    value: 'Health Index',
                    angle: -90,
                    position: 'insideLeft',
                    style: { fill: 'hsl(215, 12%, 58%)', fontSize: 12 },
                  }}
                  stroke="hsl(215, 12%, 58%)"
                  tick={{ fontSize: 11 }}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: 'hsl(220, 13%, 9%)',
                    border: '1px solid hsl(220, 12%, 18%)',
                    borderRadius: '6px',
                    color: 'hsl(210, 20%, 92%)',
                  }}
                  formatter={(value) => [
                    Number(value).toFixed(4),
                    'Health Index',
                  ]}
                  labelFormatter={(label) => `Cycle ${label}`}
                />
                <Line
                  type="monotone"
                  dataKey="healthIndex"
                  name="Health Index"
                  stroke="hsl(192, 45%, 55%)"
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex items-center justify-center h-[300px] text-muted-foreground text-sm">
              No trajectory data available yet. Waiting for health updates...
            </div>
          )}
        </section>

        {/* Engine Schematic View */}
        <section className="rounded-lg border border-border bg-card p-6">
          <h2 className="text-lg font-medium mb-4">Engine Subsystem Health</h2>
          <EngineSchematic subsystems={subsystems} />
        </section>

        {/* EnKF Correction Analysis (v1.2) */}
        <CorrectionAnalysisSection engineId={engineId} />
      </div>
    </main>
  );
}

function CorrectionAnalysisSection({ engineId }: { engineId: number }) {
  const correctionHistory = useStore((state) => state.correctionHistory);

  // Find sensors belonging to this engine (pattern: engine-00X-sensor_name)
  const enginePrefix = `engine-${String(engineId).padStart(3, '0')}-`;
  const engineSensorIds = Object.keys(correctionHistory).filter((id) =>
    id.startsWith(enginePrefix)
  );

  // Pick the first sensor with data for the detailed charts
  const activeSensorId = engineSensorIds[0] ?? null;

  if (!activeSensorId) {
    return (
      <section className="rounded-lg border border-border bg-card p-6">
        <h2 className="text-lg font-medium mb-4">EnKF Correction Analysis</h2>
        <p className="text-sm text-muted-foreground">
          Waiting for correction data from Engine {engineId}...
        </p>
      </section>
    );
  }

  return (
    <section className="space-y-4">
      <div className="rounded-lg border border-border bg-card p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-medium">EnKF Correction Analysis</h2>
          <span className="text-xs text-muted-foreground font-mono">
            {activeSensorId}
          </span>
        </div>

        {/* Prediction vs Reality Overlay */}
        <div className="mb-6">
          <h3 className="text-sm font-medium text-muted-foreground mb-2">
            Prediction vs Reality
          </h3>
          <PredictionComparison sensorId={activeSensorId} />
        </div>

        {/* Confidence Bands */}
        <div className="mb-6">
          <h3 className="text-sm font-medium text-muted-foreground mb-2">
            Confidence Bands (50% / 75% / 95%)
          </h3>
          <ConfidenceBandChart sensorId={activeSensorId} />
        </div>

        {/* Kalman Gain + Innovation side by side */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <KalmanGainIndicator sensorId={activeSensorId} />
          <div className="rounded-lg border border-white/[0.06] bg-[#12141a] p-4">
            <InnovationMeter sensorId={activeSensorId} />
          </div>
        </div>
      </div>

      {/* Sensor selector for this engine */}
      {engineSensorIds.length > 1 && (
        <p className="text-xs text-muted-foreground text-center">
          Showing {activeSensorId.replace(enginePrefix, '')} — {engineSensorIds.length} sensors tracked for this engine
        </p>
      )}
    </section>
  );
}
