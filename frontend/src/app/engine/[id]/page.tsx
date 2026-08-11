'use client';

import { useState, useCallback } from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useStore } from '@/store';
import { useWebSocket } from '@/hooks/useWebSocket';
import { EngineSchematic } from '@/components/EngineSchematic';
import { PredictionComparison } from '@/components/visualizations/PredictionComparison';
import { ConfidenceBandChart } from '@/components/visualizations/ConfidenceBandChart';
import { KalmanGainIndicator } from '@/components/visualizations/KalmanGainIndicator';
import { InnovationMeter } from '@/components/visualizations/InnovationMeter';
import { FaultInjectionPanel } from '@/components/visualizations/FaultInjectionPanel';
import { WhatIfStressSlider } from '@/components/visualizations/WhatIfStressSlider';
import { MonteCarloFanChart } from '@/components/visualizations/MonteCarloFanChart';
import { DegradationCurveProjection } from '@/components/visualizations/DegradationCurveProjection';
import { RULCountdown } from '@/components/visualizations/RULCountdown';
import type { SimulationResult } from '@/types/simulation';

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

  // Simulation state — WhatIfStressSlider sets this, distributed to child charts
  const [simulationResult, setSimulationResult] = useState<SimulationResult | null>(null);

  const handleSimulationResult = useCallback((result: SimulationResult) => {
    setSimulationResult(result);
  }, []);

  function handleEngineChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const newId = Number(e.target.value);
    selectEngine(newId);
    setSimulationResult(null); // Reset simulation when switching engines
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

        {/* RUL Countdown — Prominent placement near health index */}
        <RULCountdown
          expectedRul={simulationResult?.expected_rul ?? (isCriticalRUL ? rul : null)}
          confidenceInterval90={simulationResult?.confidence_interval_90 ?? null}
        />

        {/* Fault Injection Panel — Collapsible sidebar section */}
        <details className="rounded-lg border border-border bg-card">
          <summary className="px-6 py-4 cursor-pointer text-lg font-medium hover:text-cyan-400 transition-colors">
            Fault Injection Controls
          </summary>
          <div className="px-6 pb-6">
            <FaultInjectionPanel />
          </div>
        </details>

        {/* What-If Stress Slider — Above projection charts */}
        <section className="rounded-lg border border-border bg-card p-6">
          <WhatIfStressSlider
            engineId={engineId}
            onSimulationResult={handleSimulationResult}
          />
        </section>

        {/* Monte Carlo Fan Chart — New visualization card */}
        <section className="rounded-lg border border-border bg-card p-6">
          <h2 className="text-lg font-medium mb-4">Monte Carlo Projection</h2>
          <MonteCarloFanChart
            percentiles={simulationResult?.percentiles ?? null}
          />
        </section>

        {/* Degradation Curve with Future Projection — Replaces basic trajectory chart */}
        <section className="rounded-lg border border-border bg-card p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-medium">Degradation Curve &amp; Projection</h2>
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
          <DegradationCurveProjection
            historicalData={trajectory}
            projectionPercentiles={simulationResult?.percentiles ?? null}
          />
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
