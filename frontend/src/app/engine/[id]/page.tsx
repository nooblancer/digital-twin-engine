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
import { BentoGrid } from '@/components/dashboard/BentoGrid';
import type { BentoGridItem } from '@/components/dashboard/BentoGrid';
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

        {/* v1.3 Simulation Components — BentoGrid Layout */}
        <SimulationBentoSection
          engineId={engineId}
          simulationResult={simulationResult}
          onSimulationResult={handleSimulationResult}
          rul={rul}
          isCriticalRUL={isCriticalRUL}
          trajectory={trajectory}
          degradationRate={degradationRate}
        />

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

/** Props for the simulation bento section. */
interface SimulationBentoSectionProps {
  engineId: number;
  simulationResult: SimulationResult | null;
  onSimulationResult: (result: SimulationResult) => void;
  rul: number;
  isCriticalRUL: boolean;
  trajectory: { cycle: number; healthIndex: number }[];
  degradationRate: number | null;
}

/**
 * SimulationBentoSection — Renders the v1.3 simulation components in a
 * BentoGrid layout with the assigned spans:
 *   RULCountdown: 1x1
 *   WhatIfStressSlider: 2x1
 *   MonteCarloFanChart: 2x2
 *   DegradationCurveProjection: 2x2
 *   FaultInjectionPanel: 1x2
 *
 * Each component fills its grid cell without overflow or clipping.
 * Responsive collapse to single-column is handled by BentoGrid CSS.
 */
function SimulationBentoSection({
  engineId,
  simulationResult,
  onSimulationResult,
  rul,
  isCriticalRUL,
  trajectory,
  degradationRate,
}: SimulationBentoSectionProps) {
  const items: BentoGridItem[] = [
    {
      id: 'rul-countdown',
      size: '1x1',
      component: (
        <div className="h-full w-full flex flex-col">
          <RULCountdown
            expectedRul={simulationResult?.expected_rul ?? (isCriticalRUL ? rul : null)}
            confidenceInterval90={simulationResult?.confidence_interval_90 ?? null}
          />
        </div>
      ),
    },
    {
      id: 'what-if-slider',
      size: '2x1',
      component: (
        <div className="h-full w-full flex flex-col overflow-hidden">
          <WhatIfStressSlider
            engineId={engineId}
            onSimulationResult={onSimulationResult}
          />
        </div>
      ),
    },
    {
      id: 'fault-injection',
      size: '1x2',
      component: (
        <div className="h-full w-full overflow-y-auto">
          <FaultInjectionPanel />
        </div>
      ),
    },
    {
      id: 'monte-carlo-fan',
      size: '2x2',
      component: (
        <div className="h-full w-full flex flex-col">
          <MonteCarloFanChart
            percentiles={simulationResult?.percentiles ?? null}
            height={440}
          />
        </div>
      ),
    },
    {
      id: 'degradation-curve',
      size: '2x2',
      component: (
        <div className="h-full w-full flex flex-col">
          <div className="flex items-center justify-between px-4 pt-3 pb-1 shrink-0">
            <h2 className="text-sm font-medium text-[hsl(210,20%,92%)]">
              Degradation Curve &amp; Projection
            </h2>
            {degradationRate !== null && (
              <span
                data-testid="degradation-rate"
                className={`text-xs font-mono ${
                  degradationRate > 0.02
                    ? 'text-red-400'
                    : 'text-[hsl(210,20%,78%)]'
                }`}
              >
                {degradationRate.toFixed(4)} HI/cycle
              </span>
            )}
            {degradationRate === null && (
              <span className="text-xs text-[hsl(215,12%,58%)] italic">
                Degradation rate unavailable
              </span>
            )}
          </div>
          <div className="flex-1 min-h-0">
            <DegradationCurveProjection
              historicalData={trajectory}
              projectionPercentiles={simulationResult?.percentiles ?? null}
              height={400}
            />
          </div>
        </div>
      ),
    },
  ];

  return <BentoGrid items={items} className="engine-bento" />;
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
