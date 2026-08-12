'use client';

import { useEffect, useRef, useState } from 'react';
import { useWebSocket } from '@/hooks/useWebSocket';
import { useStore } from '@/store';
import { GlassStatusBar } from '@/components/dashboard/GlassStatusBar';
import { BentoGrid, type BentoGridItem } from '@/components/dashboard/BentoGrid';
import { GlowCard } from '@/components/ui/GlowCard';
import { PredictiveAlertNotification } from '@/components/dashboard/PredictiveAlertNotification';
import { RootCausePanel } from '@/components/dashboard/RootCausePanel';
import { TurbofanSchematic } from '@/components/engine/TurbofanSchematic';
import { EnhancedLineChart } from '@/components/visualizations/EnhancedLineChart';
import { TelemetryWaterfall } from '@/components/visualizations/TelemetryWaterfall';
import { SensorChart } from '@/components/SensorChart';
import { AnomalyAlertFeed } from '@/components/AnomalyAlertFeed';
import type { SubsystemHealthData } from '@/components/engine/TurbofanSchematic';

/**
 * Mission Control Dashboard — Bento Grid layout with glassmorphism styling.
 *
 * Components placed in bento slots:
 * - TurbofanSchematic: 3x2 (primary visual)
 * - EnhancedLineChart: 2x1
 * - TelemetryWaterfall: 2x2
 * - RootCausePanel: 1x2
 * - Existing charts/alerts: 1x1 in GlowCards
 *
 * Validates: Requirements 5.3, 7.1, 7.2, 7.3, 7.5, 14.1, 14.3
 */
export default function DashboardPage() {
  // Establish WebSocket connection on mount
  useWebSocket();

  const sensorData = useStore((state) => state.sensorData);
  const engines = useStore((state) => state.engines);
  const totalEventCount = useStore((state) => state.totalEventCount);
  const predictiveAlerts = useStore((state) => state.predictiveAlerts);
  const dismissAlert = useStore((state) => state.dismissAlert);

  // Track data arrival for GlowCard isActive pulses
  const prevEventCountRef = useRef(totalEventCount);
  const [dataArrived, setDataArrived] = useState(false);

  useEffect(() => {
    if (totalEventCount > prevEventCountRef.current) {
      setDataArrived(true);
      const timer = setTimeout(() => setDataArrived(false), 500);
      prevEventCountRef.current = totalEventCount;
      return () => clearTimeout(timer);
    }
  }, [totalEventCount]);

  // Get sensor IDs for chart rendering
  const activeSensorIds = Object.keys(sensorData);
  const firstSensorId = activeSensorIds[0] ?? null;

  // Build EnhancedLineChart data from the first available sensor
  const chartData = firstSensorId
    ? (sensorData[firstSensorId] ?? []) as unknown as Array<Record<string, number | string>>
    : [];
  const chartSeries = [
    { dataKey: 'raw', color: '#00d4ff', name: 'Raw' },
    { dataKey: 'predicted', color: '#7c3aed', name: 'Predicted' },
    { dataKey: 'corrected', color: '#10b981', name: 'Corrected' },
  ];

  // Get first engine ID for RootCausePanel
  const engineIds = Object.keys(engines).map(Number);
  const primaryEngineId = engineIds[0] ?? 1;

  // Build subsystem health data for TurbofanSchematic
  const engine = engines[primaryEngineId];
  const subsystemsData: SubsystemHealthData[] = engine?.subsystems
    ? engine.subsystems.map((s) => ({
        id: s.name.toLowerCase().replace(/\s+/g, '_'),
        name: s.name,
        healthIndex: s.healthScore,
        sensors: [],
      }))
    : [
        { id: 'fan', name: 'Fan', healthIndex: 1.0, sensors: [] },
        { id: 'lpc', name: 'LPC', healthIndex: 1.0, sensors: [] },
        { id: 'hpc', name: 'HPC', healthIndex: 1.0, sensors: [] },
        { id: 'combustor', name: 'Combustor', healthIndex: 1.0, sensors: [] },
        { id: 'hpt', name: 'HPT', healthIndex: 1.0, sensors: [] },
        { id: 'lpt', name: 'LPT', healthIndex: 1.0, sensors: [] },
        { id: 'nozzle', name: 'Nozzle', healthIndex: 1.0, sensors: [] },
      ];

  // Build bento grid items
  const bentoItems: BentoGridItem[] = [
    {
      id: 'turbofan-schematic',
      size: '3x2',
      component: (
        <GlowCard
          glowColor="cyan"
          isActive={dataArrived}
          className="h-full p-4 hover-depth"
        >
          <h3 className="text-sm font-medium text-white/80 mb-2">
            Engine Schematic
          </h3>
          <TurbofanSchematic
            subsystems={subsystemsData}
            showAirflow
            className="h-[calc(100%-2rem)]"
          />
        </GlowCard>
      ),
    },
    {
      id: 'root-cause-panel',
      size: '1x2',
      component: (
        <GlowCard
          glowColor="violet"
          isActive={dataArrived}
          className="h-full hover-depth"
        >
          <RootCausePanel engineId={primaryEngineId} className="h-full" />
        </GlowCard>
      ),
    },
    {
      id: 'enhanced-line-chart',
      size: '2x1',
      component: (
        <GlowCard
          glowColor="cyan"
          isActive={dataArrived}
          className="h-full p-4 hover-depth"
        >
          <h3 className="text-sm font-medium text-white/80 mb-2">
            {firstSensorId ?? 'Sensor Data'}
          </h3>
          <EnhancedLineChart
            data={chartData}
            series={chartSeries}
            height={150}
            showGlowDot
            gradientFill
            className="h-[calc(100%-2rem)]"
          />
        </GlowCard>
      ),
    },
    {
      id: 'telemetry-waterfall',
      size: '2x2',
      component: (
        <GlowCard
          glowColor="emerald"
          isActive={dataArrived}
          className="h-full p-4 hover-depth overflow-hidden"
        >
          <h3 className="text-sm font-medium text-white/80 mb-2">
            Telemetry Waterfall
          </h3>
          <div className="h-[calc(100%-2rem)] overflow-hidden">
            <TelemetryWaterfall visibleSteps={30} className="scale-[0.85] origin-top-left" />
          </div>
        </GlowCard>
      ),
    },
    {
      id: 'anomaly-alerts',
      size: '1x1',
      component: (
        <GlowCard
          glowColor="red"
          isActive={dataArrived}
          className="h-full p-3 hover-depth overflow-auto"
        >
          <h3 className="text-sm font-medium text-white/80 mb-2">
            Anomaly Alerts
          </h3>
          <AnomalyAlertFeed />
        </GlowCard>
      ),
    },
    {
      id: 'sensor-chart-1',
      size: '1x1',
      component: (
        <GlowCard
          glowColor="cyan"
          isActive={dataArrived}
          className="h-full p-3 hover-depth"
        >
          {activeSensorIds[1] ? (
            <>
              <h3 className="text-xs font-medium text-white/60 mb-1">
                {activeSensorIds[1]}
              </h3>
              <SensorChart sensorId={activeSensorIds[1]} />
            </>
          ) : (
            <div className="flex items-center justify-center h-full text-white/30 text-sm">
              Waiting for data…
            </div>
          )}
        </GlowCard>
      ),
    },
  ];

  return (
    <div className="grid-pattern min-h-screen bg-mission-bg">
      {/* Sticky glassmorphism status bar */}
      <GlassStatusBar />

      {/* Bento Grid Layout */}
      <BentoGrid items={bentoItems} className="mt-0 max-w-[1600px] mx-auto" />

      {/* PredictiveAlertNotification overlay — fixed positioned */}
      <PredictiveAlertNotification
        alerts={predictiveAlerts}
        onDismiss={dismissAlert}
      />
    </div>
  );
}
